from collections import deque
from time import monotonic

from chatbot.application.ports import AuthLimiter
from chatbot.domain.errors import AuthRateLimited


class MemoryAuthLimiter(AuthLimiter):
    def __init__(self, window: float = 60, capacity: int = 4096):
        self.window, self.capacity, self.entries = window, capacity, {}

    def check(self, keys: list[tuple[str, int]]):
        now = monotonic()
        for key, history in list(self.entries.items()):
            while history and history[0] <= now - self.window:
                history.popleft()
            if not history:
                del self.entries[key]
        missing = {key for key, _ in keys if key not in self.entries}
        if len(self.entries) + len(missing) > self.capacity:
            raise AuthRateLimited()
        if any(len(self.entries.get(key, ())) >= limit for key, limit in keys):
            raise AuthRateLimited()
        for key, _ in keys:
            self.entries.setdefault(key, deque()).append(now)
