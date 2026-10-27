from collections.abc import AsyncIterator, Sequence
from typing import TypedDict

from langgraph.config import get_stream_writer
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from chatbot.domain.errors import ExecutionLimit
from chatbot.domain.models import Message
from .simulated_model import SimulatedModel


class AgentState(TypedDict):
    messages: list[Message]
    response: str
    model_calls: int


class LangGraphAgent:
    def __init__(self, model: SimulatedModel, *, max_model_calls: int, recursion_limit: int):
        self.recursion_limit = recursion_limit

        async def call_model(state: AgentState):
            if state["model_calls"] >= max_model_calls:
                raise ExecutionLimit()
            writer = get_stream_writer()
            parts = []
            async for chunk in model.stream(state["messages"]):
                parts.append(chunk)
                writer({"text": chunk})
            return {"response": "".join(parts), "model_calls": state["model_calls"] + 1}

        graph = StateGraph(AgentState)
        graph.add_node("model", call_model)
        graph.add_edge(START, "model")
        graph.add_edge("model", END)
        # Structure is shared; every invocation supplies independent state. No checkpointer.
        self.graph = graph.compile()

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        try:
            async for event in self.graph.astream(
                {"messages": list(messages), "response": "", "model_calls": 0},
                config={"recursion_limit": self.recursion_limit},
                stream_mode="custom",
            ):
                yield event["text"]
        except GraphRecursionError as exc:
            raise ExecutionLimit() from exc
