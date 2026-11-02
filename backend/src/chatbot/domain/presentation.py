from dataclasses import dataclass


@dataclass(frozen=True)
class ChartReady:
    block: dict


@dataclass(frozen=True)
class ChartResult:
    result: dict
    block: dict


def append_text(blocks: list[dict], text: str):
    if not text:
        return
    if blocks and blocks[-1]["type"] == "text":
        blocks[-1] = {"type": "text", "text": blocks[-1]["text"] + text}
    else:
        blocks.append({"type": "text", "text": text})
