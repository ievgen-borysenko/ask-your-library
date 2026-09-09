"""Graph assembly.

    plan -> act -> observe -> reflect --(next query)-----> act          (loop)
                                     --(clarify)--------> clarify -> plan (ask the user)
                                     --(enough / limit / CRAG gate)-> synthesize -> validate -> END
    plan --(clarify answered, no steps left)--> synthesize
    plan --(catalogue question, ADR-016)--> catalog -> validate -> END   (code, no search)

clarify uses interrupt(), so the graph is compiled with a checkpointer:
without one LangGraph cannot suspend a run and resume it later.
"""
import os

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from .nodes import (act, catalog, clarify, observe, plan, reflect, route_after_plan,
                    route_after_reflect, synthesize, validate)
from .state import AgentState


def enable_tracing_if_key_present() -> None:
    """LangSmith tracing is opt-in by key: LangChain/LangGraph emit traces from
    the environment alone, so nodes stay tracing-agnostic. Set LANGCHAIN_ENDPOINT
    as well if your LangSmith account is not in the default (US) region."""
    if os.environ.get("LANGCHAIN_API_KEY") and "LANGCHAIN_TRACING_V2" not in os.environ:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ.setdefault("LANGCHAIN_PROJECT", "ask-your-library")


def build_graph():
    enable_tracing_if_key_present()
    graph = StateGraph(AgentState)

    graph.add_node("plan", plan)
    graph.add_node("act", act)
    graph.add_node("observe", observe)
    graph.add_node("reflect", reflect)
    graph.add_node("clarify", clarify)
    graph.add_node("catalog", catalog)
    graph.add_node("synthesize", synthesize)
    graph.add_node("validate", validate)

    graph.set_entry_point("plan")
    graph.add_conditional_edges("plan", route_after_plan,
                                {"act": "act", "synthesize": "synthesize", "catalog": "catalog"})
    graph.add_edge("catalog", "validate")
    graph.add_edge("act", "observe")
    graph.add_edge("observe", "reflect")
    graph.add_conditional_edges("reflect", route_after_reflect,
                                {"act": "act", "clarify": "clarify",
                                 "synthesize": "synthesize"})
    graph.add_edge("clarify", "plan")
    graph.add_edge("synthesize", "validate")
    graph.add_edge("validate", END)

    return graph.compile(checkpointer=MemorySaver())
