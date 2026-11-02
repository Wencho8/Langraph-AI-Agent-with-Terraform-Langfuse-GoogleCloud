"""Provider-independent market boundary; values are JSON-compatible snapshots."""
from typing import Protocol


class MarketDataError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class MarketData(Protocol):
    async def search(self, query: str, kind: str) -> list[dict]: ...
    async def quote(self, instrument_id: str) -> dict: ...
    async def history(self, instrument_id: str, start: str, end: str) -> dict: ...
    async def close(self) -> None: ...
