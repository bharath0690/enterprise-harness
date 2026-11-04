"""Local vector search over docs/*.md, using Chroma and its built-in open-source embedding model.

Embeddings run on this machine (all-MiniLM-L6-v2 via ONNX), so searches cost nothing.
The model (~80 MB) downloads once on first use. The index rebuilds when any document changes.
"""
import hashlib
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parent / "docs"
COLLECTION = "northstar-docs"


def chunk_markdown(text):
    """Split a document into (section, passage) pairs at its ## headings."""
    title, section, lines, chunks = "", "", [], []
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            if lines:
                chunks.append((section or title, "\n".join(lines).strip()))
            section, lines = line[3:].strip(), []
        elif line.strip():
            lines.append(line)
    if lines:
        chunks.append((section or title, "\n".join(lines).strip()))
    return [(s, t) for s, t in chunks if t]


def fingerprint(folder):
    """Hash every document so edits, additions and deletions trigger a rebuild."""
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*.md")):
        digest.update(str(path.relative_to(folder)).encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


class DocsIndex:
    """A persistent Chroma collection built from a folder of Markdown documents."""

    def __init__(self, storage, docs=DOCS):
        self.storage = Path(storage)
        self.docs = Path(docs)
        self._collection = None

    def collection(self):
        """Open the collection, rebuilding it when the documents have changed."""
        if self._collection is not None:
            return self._collection
        import chromadb
        from chromadb.config import Settings

        client = chromadb.PersistentClient(
            path=str(self.storage), settings=Settings(anonymized_telemetry=False),
        )
        current = fingerprint(self.docs)
        try:
            existing = client.get_collection(COLLECTION)
            if (existing.metadata or {}).get("fingerprint") == current:
                self._collection = existing
                return existing
            client.delete_collection(COLLECTION)
        except Exception:
            pass
        collection = client.create_collection(
            COLLECTION, metadata={"fingerprint": current, "hnsw:space": "cosine"},
        )
        ids, texts, metadata = [], [], []
        for path in sorted(self.docs.rglob("*.md")):
            name = str(path.relative_to(self.docs))
            for i, (section, text) in enumerate(chunk_markdown(path.read_text())):
                ids.append(f"{name}#{i}")
                texts.append(f"{section}\n{text}")
                metadata.append({"doc": name, "section": section})
        if ids:
            collection.add(ids=ids, documents=texts, metadatas=metadata)
        self._collection = collection
        return collection

    def search(self, query, limit=4):
        """Return the passages closest in meaning to the query."""
        query = re.sub(r"\s+", " ", query or "").strip()
        if not query:
            return []
        collection = self.collection()
        count = collection.count()
        if not count:
            return []
        found = collection.query(query_texts=[query], n_results=min(limit, count))
        return [
            {"citation": f'[{meta["doc"]} § {meta["section"]}]',
             "doc": meta["doc"], "section": meta["section"],
             "text": text.split("\n", 1)[-1], "score": round(distance, 3)}
            for text, meta, distance in zip(
                found["documents"][0], found["metadatas"][0], found["distances"][0])
        ]
