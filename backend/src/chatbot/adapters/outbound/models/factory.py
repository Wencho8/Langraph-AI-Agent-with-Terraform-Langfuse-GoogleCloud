from chatbot.application.ports import ChatModel
from chatbot.config import Settings
from .simulated import SimulatedModel


def create_model(settings: Settings) -> ChatModel:
    if settings.model_provider == "simulated":
        return SimulatedModel(settings.simulated_chunk_delay_seconds)
    from openai import AsyncOpenAI
    from .openai import OpenAIModel

    client = AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value().strip(),
        max_retries=0, timeout=settings.model_timeout_seconds,
    )
    return OpenAIModel(client, model=settings.model_name, max_output_tokens=settings.model_max_output_tokens,
                       reasoning_effort=settings.model_reasoning_effort)
