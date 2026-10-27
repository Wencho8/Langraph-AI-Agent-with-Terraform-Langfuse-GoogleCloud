from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from chatbot.domain.models import UserProfile

REQUIRED_SECTIONS = {"role", "scope", "instructions", "rules", "output_format", "examples"}


@dataclass(frozen=True)
class Prompt:
    instructions: str
    revision: str


def parse_prompt(source: str) -> Prompt:
    try:
        root = ElementTree.fromstring(source)
        if root.tag != "finance_assistant" or {node.tag for node in root} != REQUIRED_SECTIONS:
            raise ValueError("Missing or unexpected prompt section")
        if len(root) != len(REQUIRED_SECTIONS) or any(not "".join(node.itertext()).strip() for node in root):
            raise ValueError("Empty or duplicate prompt section")
    except (ElementTree.ParseError, ValueError):
        raise ValueError("Finance prompt must be valid XML with the required nonempty sections") from None
    return Prompt(source, sha256(source.encode("utf-8")).hexdigest())


def load_prompt() -> Prompt:
    try:
        source = files("chatbot.prompts").joinpath("finance.xml").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise ValueError("Packaged finance.xml is missing or unreadable") from None
    return parse_prompt(source)


def profile_context(user: UserProfile) -> str | None:
    if not user.display_name:
        return None
    return f"<user_profile><display_name>{escape(user.display_name)}</display_name></user_profile>"
