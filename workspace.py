"""Local folders for company instructions, skills, and task output."""
from pathlib import Path
import shutil
from company import ROOT
from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import WriteResult, EditResult, DeleteResult, FileUploadResponse


def prepare_workspace(path):
    """Create a local workspace and copy instructions on first use."""
    folder = Path(path).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    for source in [ROOT / "company/AGENTS.md", *sorted((ROOT / "skills").rglob("*.md"))]:
        target = folder / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(source, target)
    (folder / "work").mkdir(exist_ok=True)
    return folder


def recover_old_files(folder, files):
    """Copy older checkpoint-held drafts to disk without overwriting local edits."""
    folder = Path(folder).resolve()
    for name, data in files.items():
        if not name.startswith("/work/"):
            continue
        target = (folder / name.lstrip("/")).resolve()
        if not target.is_relative_to(folder / "work") or target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        content = data["content"]
        target.write_text(content if isinstance(content, str) else "\n".join(content))


def working_files(folder):
    """Read saved text artifacts for the product's file panel."""
    folder = Path(folder).resolve()
    return {"/" + str(p.relative_to(folder)): p.read_text()
            for p in (folder / "work").rglob("*")
            if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(folder)}


class ReferenceBackend(FilesystemBackend):
    """Read company instructions and skills before a writable workspace is added."""

    def write(self, file_path, content):
        """Keep early-stage deliverables in the conversation."""
        return WriteResult(error="References are read-only. Return the draft in chat.")

    def edit(self, file_path, old_string, new_string, replace_all=False):
        """Protect reference documents from edits."""
        return EditResult(error="References are read-only. Return revisions in chat.")

    def delete(self, file_path):
        """Keep company reference documents available."""
        return DeleteResult(error="References are read-only.")

    def upload_files(self, files):
        """Reject file uploads until a writable workspace is configured."""
        return [FileUploadResponse(path=path, error="permission_denied") for path, _ in files]


def reference_backend(path):
    """Load current company references into a read-only backend."""
    folder = prepare_workspace(Path(path) / "references")
    for source in [ROOT / "company/AGENTS.md", *sorted((ROOT / "skills").rglob("*.md"))]:
        shutil.copyfile(source, folder / source.relative_to(ROOT))
    return ReferenceBackend(root_dir=folder, virtual_mode=True)


def load_references():
    """Give the notebook read-only access to company instructions and skills.

    Return keyword arguments for create_deep_agent. Writable working files are
    configured separately in the Persistence chapter.
    """
    return {"backend": reference_backend(ROOT / "workspace" / "notebook")}
