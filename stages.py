"""Build the same harness at each notebook chapter, without future settings."""
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemPermission
from workspace import reference_backend
from langchain.agents.middleware import TodoListMiddleware, ModelCallLimitMiddleware
from agent import company_context, specialist, execution_middleware, build_harness

STAGES = ("base", "context", "actions", "boundaries", "persistence")


def build_stage(stage, model, company, role, checkpointer, reviewer_model=None, workspace=None):
    """Compile the selected stage. Only Persistence uses the full app builder.

    A checkpointer also carries the UI conversation between HTTP requests.
    Earlier stages receive an in-memory saver; the final stage receives SQLite.
    Actions registers the full company tool catalog. Tool-level role checks stay
    active; Boundaries also filters visibility and adds approval.
    """
    stage = {"ongoing": "persistence"}.get(stage, stage)
    if stage not in STAGES:
        raise ValueError(f"Unknown harness stage: {stage}")
    if stage == "persistence":
        return build_harness(model, company, role, checkpointer, reviewer_model, workspace)
    settings = {"model": model, "checkpointer": checkpointer}
    if stage != "base":
        settings.update(company_context())
        settings["backend"] = reference_backend(workspace or company.database.parent / "workspace")
        settings["system_prompt"] = "Return drafts and findings in chat. Company reference files are read-only."
    if stage in {"actions", "boundaries"}:
        tools = company.tools_for(role)
        lookup = next(t for t in tools if t.name == "customer_brief")
        settings.update(
            tools=list(company.all_tools_for(role).values()),
            subagents=[specialist(reviewer_model or model, lookup)],
            middleware=[TodoListMiddleware(), ModelCallLimitMiddleware(run_limit=10, exit_behavior="end")],
        )
        if stage == "boundaries":
            settings.update(
                tools=tools,
                permissions=[FilesystemPermission(
                    operations=["write"], paths=["/company/**", "/skills/**"], mode="deny",
                )],
                interrupt_on={"send_proposal": {"allowed_decisions": ["approve", "reject"]}},
            )
    return create_deep_agent(**settings)
