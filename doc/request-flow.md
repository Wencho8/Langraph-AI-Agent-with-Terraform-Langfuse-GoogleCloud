# Request Flow and Concurrency

## Startup

Uvicorn runs **one worker process with one main event loop**. At startup, `app.py` builds the repository, identity adapter, model client, agent, rate limiter, and orchestrator, and loads the static finance prompt.

These objects are reused across requests through `app.state`; a new orchestrator is not created for every message. Each turn has its own execution object, messages, and state.

## One chat message

```text
POST /v1/chat/messages
  -> HTTP route validates the message and resolves the local user
  -> shared orchestrator checks rate limits and available capacity
  -> lock adapter acquires the user's conversation lock in PostgreSQL
  -> repository creates the turn, saves the user message, and loads all history
  -> agent receives the user's name, full history, and finance instructions
  -> model adapter calls OpenAI or the local simulator and streams response chunks
  -> HTTP adapter sends those chunks as SSE events
  -> repository saves the final assistant message, transcript, and metrics in one transaction
  -> HTTP adapter sends the completed event
  -> execution cleanup releases the lock and the capacity slot
```

`MODEL` selects `simulated` (default, no key) or `openai:<model-id>`. The model client is reused; each call has separate inputs. The local identity header selects a fixture user; it is not real authentication.

The tool registry is empty. The graph is ready to execute registered tools and call the model again within the same turn, under separate call limits and one shared deadline. The HTTP route and orchestrator keep the same flow.

`GET /v1/chat/messages` resolves the current user and calls the orchestrator/repository to read their history. It does not run the agent.

## Concurrent messages

- The event loop coordinates multiple async requests; it does not wait for one entire turn before accepting another.
- The current limit is **four active turns per worker process**. Configure it with `MAX_ACTIVE_TURNS` in `.env` and run `make start` to apply the change.
- With one conversation per user, those four active turns belong to different users. An overlapping turn for the same user is rejected with `409 session_busy`.
- If all four slots are occupied, another submission is rejected with `503 runtime_saturated`.
- Each request has separate conversation data, even though it uses the same orchestrator and compiled agent graph.
- Current limits and the memory rate limiter are process-local. Adding workers would create more orchestrators and separate counters; PostgreSQL locks remain shared.

On a handled error, timeout, or client disconnect, execution cleanup stops generation, attempts to record the failed/cancelled status, and releases resources. Partial assistant output is not saved as a completed message.
