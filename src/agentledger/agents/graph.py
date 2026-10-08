"""LangGraph agent: plan -> react (tool loop under budget) -> reflect.
Same shape as witold-andelie/revio agent/graph.py; shared by the buyer and the guardian.

Guarantees the rest of the system relies on:
- every LLM call is metered (RunRecorder.llm_call) before anything else happens with its output;
- every tool_call gets a paired ToolMessage, even when the budget runs out mid-batch;
- tools return strings and never raise into the loop (errors come back to the model as text);
- the loop stops on: model stops calling tools, tool/cost budget, or MAX_ITERATIONS.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agentledger.agents.telemetry import RunRecorder

MAX_ITERATIONS = 40


class AgentState(TypedDict, total=False):
    goal: str
    plan: str
    messages: Annotated[list[BaseMessage], add_messages]
    stop_reason: str
    summary: str


def text_of(message: Any) -> str:
    """Visible text of an AIMessage across providers (str, or a list of content blocks)."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(p for p in parts if p)


def _clean(message: AIMessage) -> AIMessage:
    # Reasoner-style OpenAI-compatible models reject their own reasoning_content as input (revio fix).
    if message.additional_kwargs:
        message.additional_kwargs.pop("reasoning_content", None)
    return message


def build_agent_graph(
    *,
    model: Any,
    tools: Sequence[BaseTool],
    recorder: RunRecorder,
    system_prompt: str,
    plan_instruction: str,
    reflect_instruction: str,
    should_stop: Callable[[], str | None] | None = None,
) -> Any:
    tools_by_name = {t.name: t for t in tools}
    model_with_tools = model.bind_tools(list(tools))

    def plan_node(state: AgentState) -> dict[str, Any]:
        messages = [SystemMessage(system_prompt), HumanMessage(f"{state['goal']}\n\n{plan_instruction}")]
        started = time.perf_counter()
        reply = _clean(model.invoke(messages))
        plan = text_of(reply).strip()
        recorder.llm_call("plan", reply, started, plan)
        return {
            "plan": plan,
            "messages": [SystemMessage(system_prompt),
                         HumanMessage(f"{state['goal']}\n\nYour plan:\n{plan}\n\nExecute it with the tools now.")],
        }

    def react_node(state: AgentState) -> dict[str, Any]:
        messages: list[BaseMessage] = list(state["messages"])
        new: list[BaseMessage] = []
        stop_reason = "model finished"
        for _ in range(MAX_ITERATIONS):
            started = time.perf_counter()
            reply = _clean(model_with_tools.invoke(messages + new))
            recorder.llm_call("react", reply, started, text_of(reply))
            new.append(reply)
            calls = reply.tool_calls or []
            if not calls:
                break
            for call in calls:  # answer EVERY call in the batch before deciding to stop
                tool = tools_by_name.get(call["name"])
                t0 = time.perf_counter()
                if tool is None:
                    result, ok = f"error: unknown tool {call['name']!r}", False
                else:
                    try:
                        result, ok = str(tool.invoke(call.get("args") or {})), True
                    except Exception as exc:  # tool bugs must not kill the run
                        result, ok = f"error: {type(exc).__name__}: {exc}", False
                recorder.tool_call(call["name"], call.get("args") or {}, result, t0, ok)
                new.append(ToolMessage(content=result, tool_call_id=call["id"], name=call["name"]))
            reason = recorder.budget_exhausted() or (should_stop() if should_stop else None)
            if reason:
                stop_reason = reason
                recorder.note("policy", "stop", reason=reason)
                break
        else:
            stop_reason = f"iteration limit {MAX_ITERATIONS}"
            recorder.note("policy", "stop", reason=stop_reason)
        return {"messages": new, "stop_reason": stop_reason}

    def reflect_node(state: AgentState) -> dict[str, Any]:
        messages = list(state["messages"])
        if messages and isinstance(messages[-1], ToolMessage):
            # Some providers (Mistral) reject a user turn directly after tool results.
            messages.append(AIMessage(content="(stopping tool use)"))
        messages.append(HumanMessage(f"Stopped because: {state.get('stop_reason', 'done')}.\n{reflect_instruction}"))
        started = time.perf_counter()
        reply = _clean(model.invoke(messages))
        summary = text_of(reply).strip()
        recorder.llm_call("reflect", reply, started, summary)
        return {"summary": summary}

    graph = StateGraph(AgentState)
    graph.add_node("plan", plan_node)
    graph.add_node("react", react_node)
    graph.add_node("reflect", reflect_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "react")
    graph.add_edge("react", "reflect")
    graph.add_edge("reflect", END)
    return graph.compile()


def as_json(obj: Any) -> str:
    """Compact JSON for tool results: models read it reliably and it is cheap in tokens."""
    return json.dumps(obj, default=str, separators=(",", ":"))
