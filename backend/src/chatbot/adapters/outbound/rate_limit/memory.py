from collections import defaultdict, deque
from time import monotonic
from uuid import UUID

from chatbot.domain.errors import RateLimited


class MemoryRateLimiter:
    """Single-event-loop, rolling-window limiter. Local/test only; resets on restart."""

    def __init__(self, requests: int, window_seconds: float):
        self.requests = requests
        self.window = window_seconds
        self.submissions: dict[UUID, deque[float]] = defaultdict(deque)

    def check(self, user_id: UUID):
        now = monotonic()
        history = self.submissions[user_id]
        while history and history[0] <= now - self.window:
            history.popleft()
        if len(history) >= self.requests:
            raise RateLimited()
        history.append(now)
