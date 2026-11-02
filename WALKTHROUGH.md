# Harness walkthrough

Open [00_NS_Work.ipynb](00_NS_Work.ipynb) and work through its cells in order. The running example is Northstar, an analytics company whose sales, engineering, and finance teams need different company operations.

| Stage | Question | Configuration to inspect |
|---|---|---|
| Base | How does the model use an agent loop? | `create_deep_agent(model=model)` |
| Context | What should the harness know about the company and its procedures? | Company `AGENTS.md`, skill directories, and read-only references |
| Actions | Which company operations and specialist work can it perform? | Company tools, `TodoListMiddleware`, and the proposal reviewer |
| Boundaries | Who can do what, and which actions need approval? | Role filtering, tool-level checks, protected reference files, call limits, and `interrupt_on` |
| Persistence | What survives a reply, a long conversation, or a restart? | Working files, SQLite checkpoints, and context summarization |

For Context, provide a customer brief in your own request. After Actions, ask the harness to retrieve Acme's company record. After Boundaries, compare the tools available to Sales, Engineering, and Finance. In Persistence, save a proposal, then return to the same task with a follow-up.

Run the chapter's `update_ui(...)` cell to open its interface. Stage changes start fresh conversations. Use the link that the notebook prints; its port can change when another process occupies the requested port.

`agent.py` holds the complete configuration and `stages.py` builds the intermediate versions. Keep these aligned with the notebook if you adapt the example. The local outbox gives you a way to inspect approval behavior without sending email.
