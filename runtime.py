"""Notebook plumbing: readable outputs, virtual file seeding and explicit live-call switch."""

import os
from uuid import uuid4

from deepagents.backends.utils import create_file_data
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from company import ROOT


class PreviewModel(BaseChatModel):
    """Compile configurations without credentials. Never pretends to answer prompts."""

    model_name: str = "nswork:preview"

    @property
    def _llm_type(self):
        """Identify this non-generating configuration model to LangChain."""
        return "configuration-preview-only"

    def bind_tools(self, tools, **kwargs):
        """Accept tool definitions so configurations can compile without a provider call."""
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        """Reject generation until the caller explicitly enables a live provider model."""
        raise RuntimeError("Preview mode cannot generate responses. Set RUN_LIVE=True to use your model.")


def make_model(live, specialist=False):
    """Create the configured provider model, or a non-generating model for inspecting configuration."""
    load_dotenv(ROOT / ".env", override=True)
    if not live:
        return PreviewModel()
    name = os.getenv("HARNESS_MODEL") or ("anthropic:claude-sonnet-4-6" if os.getenv("ANTHROPIC_API_KEY") else "openai:gpt-5.4")
    if specialist:
        name = os.getenv("HARNESS_SPECIALIST_MODEL") or name
    provider = name.split(":", 1)[0]
    key_name = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(provider)
    if key_name and not os.getenv(key_name):
        raise ValueError(f"Set {key_name} in .env, then rerun setup. Never paste keys into a notebook cell.")
    options = {"max_tokens": 1800, "timeout": 90, "max_retries": 1}
    if name.startswith("openai:gpt-5"):
        options.update(max_tokens=6000, reasoning_effort="low", use_responses_api=True)
    return init_chat_model(name, **options)


def seed_files():
    """Load company instructions and skill documents into the thread’s virtual filesystem."""
    paths = [ROOT / "company/AGENTS.md", *sorted((ROOT / "skills").rglob("*.md"))]
    return {"/" + str(path.relative_to(ROOT)): create_file_data(path.read_text()) for path in paths}


def new_thread(label):
    """Create a unique conversation ID so its messages and working files stay together."""
    return {"configurable": {"thread_id": f"{label}-{uuid4().hex[:8]}"}, "recursion_limit": 200}


def show(result):
    """Display new messages only; do not flood the screen with the graph state."""
    messages = result.get("messages", [])
    start = max((i for i, message in enumerate(messages) if message.type == "human"), default=-1)
    for message in messages[start + 1:]:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                print(f"→ {call['name']}: {str(call['args'])[:250]}")
            if message.content:
                content = message.content
                if isinstance(content, list):
                    content = "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
                print(content)
        elif isinstance(message, ToolMessage):
            print(f"← {message.name or 'tool'}: {str(message.content)[:300]}")
    for interrupt in result.get("__interrupt__", []):
        print("PAUSED FOR HUMAN REVIEW:", interrupt.value)


def ask(agent, question, config=None, *, live=False):
    """Submit a request with initial company files, then display tool activity and the answer. Skip model calls when live is false."""
    if not live:
        print("PREVIEW: configuration built; model call skipped. Set RUN_LIVE=True for real output.")
        return {}
    inputs = {"messages": [{"role": "user", "content": question}]}
    if config is not None:
        snapshot = agent.get_state(config)
        if snapshot.next:
            raise RuntimeError("This thread has pending work. Resolve its approval before sending another prompt.")
        if not snapshot.values:
            inputs["files"] = seed_files()
    else:
        inputs["files"] = seed_files()
    result = agent.invoke(inputs, config=config or {"recursion_limit": 200})
    show(result)
    return result


def review(agent, result, config, decision="reject", *, live=False):
    """Resume a paused tool call with an explicit human approval or rejection."""
    from langgraph.types import Command

    if not live:
        print("PREVIEW: no pending live approval.")
        return {}
    if decision not in {"approve", "reject"}:
        raise ValueError("Choose approve or reject.")
    interrupts = result.get("__interrupt__", [])
    if not interrupts:
        print("No approval was requested. Inspect the trace; the model may not have called send_proposal.")
        return result
    # One human decision per requested action, including nested-agent interrupts.
    resume = {i.id: {"decisions": [{"type": decision} for _ in i.value["action_requests"]]} for i in interrupts}
    result = agent.invoke(Command(resume=resume), config=config)
    show(result)
    return result


def inspect_work(agent, config):
    """Summarize saved messages and working-file paths for one conversation."""
    values = agent.get_state(config).values
    return {"messages_saved": len(values.get("messages", [])),
            "working_files": sorted(p for p in values.get("files", {}) if p.startswith("/work/"))}
