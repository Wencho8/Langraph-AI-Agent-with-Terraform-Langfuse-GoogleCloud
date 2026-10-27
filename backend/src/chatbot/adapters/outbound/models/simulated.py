import asyncio
from collections.abc import AsyncIterator
from xml.etree import ElementTree

from chatbot.domain.agent import ModelCompleted, ModelEvent, ModelItem, ModelRequest, TextDelta


class SimulatedModel:
    """Deterministic async transport exercise, not an evaluation of finance behavior."""

    provider = "simulated"
    name = "deterministic"

    def __init__(self, chunk_delay: float):
        self.chunk_delay = chunk_delay

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        name = ElementTree.fromstring(request.profile_context).findtext("display_name") if request.profile_context else None
        latest = request.items[-1].data["content"]
        parts = [
            f"Simulated reply{' for ' + name if name else ''}. ",
            f"Received {len(request.items)} messages in this conversation. ",
            "Latest message: ", *[word + " " for word in latest.split()],
        ]
        delivered = []
        for part in parts:
            await asyncio.sleep(self.chunk_delay)
            delivered.append(part)
            yield TextDelta(part)
        text = "".join(delivered)
        yield ModelCompleted(text, (ModelItem.message("assistant", text),))

    async def close(self):
        pass
