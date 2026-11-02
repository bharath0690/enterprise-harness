"""Configuration for NS Work, Northstar's harness. Shared by the notebook and chat interface."""
from deepagents import create_deep_agent
from deepagents.middleware.filesystem import FilesystemPermission
from deepagents.middleware.summarization import SummarizationMiddleware
from langchain.agents.middleware import ModelCallLimitMiddleware, TodoListMiddleware

from deepagents.backends import FilesystemBackend
from workspace import prepare_workspace

from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile

# Register only our explicitly configured specialists, without an automatic broad delegate.
for provider in ("openai", "anthropic", "nswork", "nswork:preview"):
    register_harness_profile(provider, HarnessProfile(
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    ))



def company_context():
    """Always-loaded conventions and procedures discovered when relevant."""
    return {
        "memory": ["/company/AGENTS.md"],
        "skills": ["/skills/company/", "/skills/team/"],
    }


def specialist(model, lookup):
    """Define the proposal reviewer with customer lookup and no sending authority."""
    return {
        "name": "proposal-reviewer",
        "description": "Review a proposal against customer facts; flag unsupported commitments.",
        "system_prompt": "Look up the customer. Return evidence, assumptions and corrections.",
        "model": model,
        "tools": [lookup],
        "middleware": [ModelCallLimitMiddleware(run_limit=4, exit_behavior="end")],
    }


def execution_middleware():
    """Planning and a bounded parent-agent run."""
    return [
        TodoListMiddleware(),
        ModelCallLimitMiddleware(run_limit=10, exit_behavior="end"),
    ]


def build_harness(model, company, role, checkpointer, reviewer_model=None, workspace=None):
    """Role comes from the application; each employee uses a separate thread."""
    workspace = prepare_workspace(workspace or company.database.parent / "workspace")
    tools = company.tools_for(role)
    lookup = next(t for t in tools if t.name == "customer_brief")
    subagents = [specialist(reviewer_model or model, lookup)]
    backend = FilesystemBackend(root_dir=workspace, virtual_mode=True)
    file_permissions = [FilesystemPermission(
        operations=["write"], paths=["/company/**", "/skills/**"], mode="deny",
    )]
    agent_middleware = execution_middleware()
    agent_middleware.extend([
        SummarizationMiddleware(
            model=model, backend=backend,
            trigger=("tokens", 12000), keep=("messages", 6),
            trim_tokens_to_summarize=None,
        ),
    ])
    return create_deep_agent(
        model=model,
        **company_context(),
        tools=tools,
        subagents=subagents,
        permissions=file_permissions,
        interrupt_on={"send_proposal": {"allowed_decisions": ["approve", "reject"]}},
        middleware=agent_middleware,
        backend=backend,
        checkpointer=checkpointer,
    )
