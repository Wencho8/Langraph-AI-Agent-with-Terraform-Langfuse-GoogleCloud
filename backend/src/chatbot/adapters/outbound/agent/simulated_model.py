import asyncio
from collections.abc import AsyncIterator, Sequence

from chatbot.domain.models import Message


class SimulatedModel:
    """Deterministic async output; no API calls and no claimed real token usage."""

    def __init__(self, chunk_delay: float):
        self.chunk_delay = chunk_delay

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        # Yield incrementally from the source, rather than chunking a completed graph result.
        parts = [
            "Simulated reply. ",
            f"Received {len(messages)} messages in this conversation. ",
            "Latest message: ",
            *[word + " " for word in messages[-1].content.split()],
        ]
        for part in parts:
            await asyncio.sleep(self.chunk_delay)
            yield part
