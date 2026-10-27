import json
from contextlib import aclosing

import anyio
from starlette.responses import StreamingResponse


class ChatStreamingResponse(StreamingResponse):
    media_type = "text/event-stream"

    def __init__(self, execution):
        self.execution = execution
        super().__init__(
            self.frames(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Request-ID": execution.request_id},
        )

    async def frames(self):
        async with aclosing(self.execution.events()) as events:
            async for event in events:
                yield f"event: {event.kind}\ndata: {json.dumps(event.data)}\n\n"

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Also close suspended generators if sending a frame fails outside the iterator.
            with anyio.CancelScope(shield=True):
                await self.body_iterator.aclose()
                await self.execution.close()
