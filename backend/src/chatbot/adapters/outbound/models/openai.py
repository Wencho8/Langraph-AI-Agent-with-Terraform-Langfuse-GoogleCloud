"""One stateless async Responses request. Tool orchestration lives in the graph."""

from collections.abc import AsyncIterator

import httpx
import openai

from chatbot.domain.agent import ModelCompleted, ModelEvent, ModelItem, ModelRequest, TextDelta, TokenUsage, ToolCall
from chatbot.domain.errors import (
    ContextLimit, InvalidModelResponse, ModelTimedOut, OutputLimit,
    ProviderAuthentication, ProviderRateLimited, ProviderRefused, ProviderRejected, ProviderUnavailable,
)


def map_api_error(error: openai.OpenAIError):
    if isinstance(error, openai.APITimeoutError):
        return ModelTimedOut()
    if isinstance(error, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return ProviderAuthentication()
    if isinstance(error, openai.RateLimitError):
        return ProviderRateLimited()
    if isinstance(error, openai.BadRequestError) and error.code in {"context_length_exceeded", "context_window_exceeded"}:
        return ContextLimit()
    if isinstance(error, openai.APIConnectionError) or (
        isinstance(error, openai.APIStatusError) and error.status_code >= 500
    ):
        return ProviderUnavailable()
    return ProviderRejected()


def token_usage(value) -> TokenUsage:
    if value is None:
        return TokenUsage()
    return TokenUsage(
        input_tokens=value.input_tokens, output_tokens=value.output_tokens, total_tokens=value.total_tokens,
        cached_tokens=getattr(getattr(value, "input_tokens_details", None), "cached_tokens", None),
        reasoning_tokens=getattr(getattr(value, "output_tokens_details", None), "reasoning_tokens", None),
    )


class OpenAIModel:
    provider = "openai"

    def __init__(self, client, *, model: str, max_output_tokens: int, reasoning_effort: str | None = None):
        self.client = client
        self.name = model
        self.max_output_tokens = max_output_tokens
        self.reasoning_effort = reasoning_effort

    def _serialize(self, items: tuple[ModelItem, ...]) -> list[dict]:
        serialized = []
        for item in items:
            if item.kind == "message":
                transcript = [ModelItem.from_dict(value) for value in item.data.get("transcript", [])]
                if transcript and all(value.provider in {None, self.provider} for value in transcript):
                    # The saved provider message already contains the assistant text.
                    serialized.extend(self._serialize(tuple(transcript)))
                else:
                    serialized.append({"role": item.data["role"], "content": item.data["content"]})
            elif item.kind == "provider_output" and item.provider == self.provider:
                serialized.append(item.data)
            elif item.kind == "tool_result" and item.provider == self.provider:
                serialized.append({"type": "function_call_output", **item.data})
            else:
                raise InvalidModelResponse()
        return serialized

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        inputs = self._serialize(request.items)
        if request.profile_context:
            inputs.insert(0, {"role": "user", "content": request.profile_context})
        options = dict(
            model=self.name, instructions=request.instructions, input=inputs, stream=True,
            store=False, max_output_tokens=self.max_output_tokens,
            include=["reasoning.encrypted_content"],
        )
        if self.reasoning_effort is not None:
            options["reasoning"] = {"effort": self.reasoning_effort}
        if request.tools:
            options["tools"] = [
                {"type": "function", "name": tool.name, "description": tool.description,
                 "parameters": tool.parameters, "strict": True}
                for tool in request.tools
            ]
        try:
            stream = await self.client.responses.create(**options)
            async with stream:
                chunks: list[str] = []
                argument_parts: dict[str, list[str]] = {}
                completed_arguments: dict[str, str] = {}
                async for event in stream:
                    if event.type == "response.output_text.delta":
                        chunks.append(event.delta)
                        yield TextDelta(event.delta)
                    elif event.type == "response.refusal.delta":
                        raise ProviderRefused()
                    elif event.type == "response.function_call_arguments.delta":
                        argument_parts.setdefault(event.item_id, []).append(event.delta)
                    elif event.type == "response.function_call_arguments.done":
                        completed_arguments[event.item_id] = event.arguments
                    elif event.type in {"response.failed", "response.incomplete"}:
                        reason = getattr(getattr(event.response, "incomplete_details", None), "reason", None)
                        if reason == "max_output_tokens":
                            raise OutputLimit()
                        raise InvalidModelResponse()
                    elif event.type == "error":
                        raise ProviderRejected()
                    elif event.type == "response.completed":
                        response = event.response
                        if response.status != "completed":
                            raise InvalidModelResponse()
                        calls, items, final_text = [], [], []
                        for item in response.output:
                            raw = item.model_dump(mode="json", exclude_none=True)
                            if item.type == "function_call":
                                if not item.call_id or not item.name:
                                    raise InvalidModelResponse()
                                fragments = argument_parts.get(item.id)
                                done_arguments = completed_arguments.get(item.id)
                                if fragments is not None and "".join(fragments) != item.arguments:
                                    raise InvalidModelResponse()
                                if done_arguments is not None and done_arguments != item.arguments:
                                    raise InvalidModelResponse()
                                calls.append(ToolCall(item.call_id, item.name, item.arguments))
                            elif item.type == "message":
                                for content in item.content:
                                    if content.type == "refusal":
                                        raise ProviderRefused()
                                    if content.type != "output_text":
                                        raise InvalidModelResponse()
                                    final_text.append(content.text)
                            elif item.type != "reasoning":
                                raise InvalidModelResponse()
                            items.append(ModelItem("provider_output", raw, self.provider))
                        if len({call.id for call in calls}) != len(calls):
                            raise InvalidModelResponse()
                        text = "".join(final_text)
                        if "".join(chunks) != text:
                            raise InvalidModelResponse()
                        request_id = stream.response.headers.get("x-request-id")
                        yield ModelCompleted(text, tuple(items), tuple(calls), token_usage(response.usage), request_id)
                        return
                # Receiving text without a terminal provider response is not success.
                raise InvalidModelResponse()
        except openai.OpenAIError as exc:
            raise map_api_error(exc) from None
        except httpx.TimeoutException:
            raise ModelTimedOut() from None
        except httpx.HTTPError:
            raise ProviderUnavailable() from None

    async def close(self):
        await self.client.close()
