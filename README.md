# NS Work: build a company harness

Run the Northstar company harness from the [harness engineering video](../../build-your-own-harness.md). The notebook and chat interface share the recorded configuration: Context, Actions, Boundaries, and Persistence.

## Set up

Use Python 3.12. From this folder:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Set `OPENAI_API_KEY` in your local `.env`. The recorded notebook uses `gpt-5.4`; provider access and usage charges apply when you submit requests. Keep credentials in `.env`, which Git ignores. Install the Python and Jupyter extensions recommended in `.vscode/extensions.json` if you use VS Code.

The dependencies are pinned to the video version, including `deepagents==0.7.21`. Install these versions before following the notebook. Later SDK releases can change configuration APIs.

## Follow the notebook

Open [00_NS_Work.ipynb](00_NS_Work.ipynb), select `.venv/bin/python` as your kernel, and run the cells in order. The configuration cells construct the harness without sending a model request. Each `update_ui(...)` cell opens the matching chapter's interface and prints its local URL. Requests submitted in that interface use the configured provider.

Stage changes start fresh conversations. Early stages hold conversation state in memory. Persistence saves individual task state in SQLite and working files on disk. Reuse the proposal example across stages without expecting a conversation to migrate between them.

The UI uses the saved configuration in `agent.py` and `stages.py`. If you change a notebook setting, make the corresponding source change before using the UI.

## Run the complete interface

```sh
.venv/bin/python server.py
```

Open http://127.0.0.1:8502. If the port is occupied, run `NSWORK_PORT=8503 .venv/bin/python server.py` and open port 8503. Keep this teaching app bound to localhost.

Try these requests:

- Sales: “Use our proposal skill to prepare an Acme proposal from the customer record. Mark pricing and timeline as awaiting confirmation. Save it to /work/proposal.md. Do not send it.”
- Engineering: “Use our triage skill to investigate Beacon's sync issue. Cite the issue and customer records.”
- Finance: “What is the revenue total for 2026-Q3? Cite the record.”

The role selector demonstrates application-owned access rules. Production deployments need authenticated identity and server-owned role/session mapping.

## Find the configuration

| Responsibility | Files | Behavior |
|---|---|---|
| Context | `company/AGENTS.md`, `skills/`, `agent.py` | Company guidance and reusable proposal/triage procedures |
| Actions | `company.py`, `tools/`, `agent.py` | Role-aware company tools, planning, and a proposal reviewer |
| Boundaries | `agent.py`, `tools/binding.py`, `company.py` | Role checks, protected reference files, human approval, and model-call limits |
| Persistence | `workspace.py`, `server.py`, `agent.py` | Local working files, SQLite task checkpoints, and context summarization |

The reviewer has customer lookup and its own call limit. The shared configuration disables the automatic general-purpose delegate. Parent and reviewer call limits are separate and do not implement a shared spending budget.

See [the tool catalog](TOOLS.md) for names, inputs, access, and source files. See [the walkthrough](WALKTHROUGH.md) for the chapter sequence.

## Check without model calls

After installing the pinned dependencies, run:

```sh
.venv/bin/python verify.py
```

This check uses scripted messages with real Deep Agents graphs in temporary storage. It executes the notebook configuration cells, compiles all 5 stages for all 3 roles, checks access rules and protected files, writes a working file, reopens a SQLite checkpoint, delegates to the reviewer, and rejects a proposal send. It makes no provider requests and starts no UI server. It uses a placeholder key only to construct the notebook's model object.

## Execution scope

Company records are synthetic. `send_proposal` writes to a local outbox; it does not send email. Files are stored under `.runtime/workspace/<task-id>/` in the complete interface. The notebook uses `workspace/notebook/`. SQLite checkpoints save task state separately from file contents, so restoring a checkpoint does not roll back files. Deleting an interface task also removes its workspace.

The Context and Actions stages use read-only company references. Persistence adds writable working files. The final configuration summarizes older context at about 12,000 tokens and retains 6 recent messages; short verification requests do not exercise that threshold. Summarization preserves a working context rather than guaranteeing verbatim recall.

The local filesystem backend does not provide an isolated host-execution sandbox. Production authentication, deployment, remote execution isolation, and production evaluations require additional work.

## Build another interface

Give this prompt to your coding agent:

> Build a local chat interface for the existing NS Work harness in agent.py. Put the server in server.py and the frontend in web/. Use the existing harness builder. Include a message composer, role profile, task history, saved artifacts, human-approval controls, and inline activity from real tool events. Use blue for Context, green for Actions, coral for Boundaries, and purple for Persistence. Keep provider credentials on the server. Show actual execution events and public results. Local profiles demonstrate role policies; production needs authenticated identity.

## References

- [Deep Agents customization](https://docs.langchain.com/oss/python/deepagents/customization)
- [Skills](https://docs.langchain.com/oss/python/deepagents/skills)
- [Filesystem permissions](https://docs.langchain.com/oss/python/deepagents/permissions)
- [Human approval](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop)
- [Backends](https://docs.langchain.com/oss/python/deepagents/backends)
