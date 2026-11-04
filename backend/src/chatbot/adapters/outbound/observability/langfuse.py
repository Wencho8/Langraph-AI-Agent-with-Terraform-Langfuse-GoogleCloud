"""Export explicit chat observations through a dedicated Langfuse tracer."""

import logging
from urllib.parse import urlsplit

import anyio
from langfuse import Langfuse
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

from chatbot.application.ports import TraceStep, TurnTrace, TurnTracing
from chatbot.config import Settings

logger = logging.getLogger("chatbot")


class LangfuseTracing(TurnTracing):
    def __init__(self, client: Langfuse, provider: TracerProvider):
        self.client = client
        self.provider = provider

    @classmethod
    def from_settings(cls, settings: Settings):
        secret = settings.langfuse_secret_key
        if not (settings.langfuse_public_key and secret and secret.get_secret_value() and settings.langfuse_base_url):
            return None
        try:
            base_url = urlsplit(settings.langfuse_base_url)
            if (base_url.scheme != "https" or not base_url.hostname or base_url.username is not None
                    or base_url.path not in {"", "/"} or base_url.query or base_url.fragment):
                raise ValueError("Invalid Langfuse origin")
            provider = TracerProvider(
                resource=Resource({"langfuse.environment": settings.app_env}), shutdown_on_exit=False,
            )
            client = Langfuse(
                public_key=settings.langfuse_public_key, secret_key=secret.get_secret_value(),
                base_url=settings.langfuse_base_url.rstrip("/"), environment=settings.app_env,
                tracer_provider=provider, timeout=2,
            )
            return cls(client, provider)
        except Exception:
            logger.warning("langfuse_initialization_failed")
            return None

    def start_turn(self, request_id: str, turn_id: str):
        observation = start(self.client, "chat-turn", "span", metadata={
            "request_id": request_id, "turn_id": turn_id,
        })
        return LangfuseTurn(observation) if observation is not None else None

    async def close(self):
        try:
            with anyio.move_on_after(3) as scope:
                await anyio.to_thread.run_sync(self._shutdown, abandon_on_cancel=True)
            if scope.cancelled_caught:
                logger.warning("langfuse_shutdown_timed_out")
        except Exception:
            logger.warning("langfuse_shutdown_failed")

    def _shutdown(self):
        try:
            self.client.shutdown()
        finally:
            self.provider.shutdown()


def start(parent, name, kind, **fields):
    try:
        return parent.start_observation(name=name, as_type=kind, **fields)
    except Exception:
        logger.warning("langfuse_observation_start_failed")
        return None


def end(observation, status, metadata, **fields):
    try:
        try:
            observation.update(
                level={"completed": "DEFAULT", "cancelled": "WARNING"}.get(status, "ERROR"),
                status_message=status, metadata=metadata, **fields,
            )
        finally:
            observation.end()
    except Exception:
        logger.warning("langfuse_observation_end_failed")


class LangfuseTurn(TurnTrace):
    def __init__(self, observation):
        self.observation = observation

    def model(self, name, reasoning_effort):
        observation = start(
            self.observation, "model-call", "generation", model=name,
            model_parameters={"reasoning_effort": reasoning_effort} if reasoning_effort else None,
        )
        return LangfuseStep(observation, generation=True) if observation is not None else None

    def tool(self, name):
        observation = start(self.observation, name, "tool")
        return LangfuseStep(observation) if observation is not None else None

    def finish(self, status, *, error_code, duration_ms, first_chunk_ms, usage):
        end(self.observation, status, {
            "error_code": error_code,
            "duration_ms": duration_ms,
            "first_chunk_ms": first_chunk_ms,
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "usage_complete": usage["complete"],
        })


class LangfuseStep(TraceStep):
    def __init__(self, observation, *, generation=False):
        self.observation = observation
        self.generation = generation

    def finish(self, status, *, usage=None, first_text=None):
        fields = {}
        if self.generation:
            fields["completion_start_time"] = first_text
            if usage is not None:
                counts = {"input": usage.input_tokens, "output": usage.output_tokens, "total": usage.total_tokens}
                fields["usage_details"] = {name: value for name, value in counts.items() if value is not None}
        end(self.observation, status, None, **fields)
