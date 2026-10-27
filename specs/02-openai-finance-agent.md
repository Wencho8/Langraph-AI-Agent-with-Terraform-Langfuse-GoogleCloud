# Iteration 02 — OpenAI Finance Agent

Status: specified; implementation has not started. This change is documentation only.

Project decisions: [Definitions](../doc/definitions.md). Baseline: [Iteration 01](01-initial-backend-setup.md).

## Goal

Use `make chat` to talk to a finance-focused OpenAI model with native async streaming, the current user's name, and their complete persisted history. Keep the simulated provider for local development and tests.

Prepare the provider contract and LangGraph for repeated tool calls within one turn, but register **zero application or hosted-provider tools**. A real first tool belongs to a later iteration.

## Scope and exclusions

Include the OpenAI adapter, model selection by configuration, XML instructions, minimal user profile, typed execution events, bounded tool-loop infrastructure, persistence adjustments, usage/timing logs, and focused tests.

Keep one Uvicorn worker, the existing HTTP endpoints, SSE event names, PostgreSQL locks, and one conversation per user. No frontend, real authentication, Google Cloud provisioning, RAG, memory, summaries, external tool integrations, or additional services/containers.

## Architecture

```text
HTTP route
  -> ChatOrchestrator
     -> conversation repository and lock ports
     -> AgentRunner port -> LangGraphAgent
        -> ChatModel port -> OpenAI model adapter or simulated model adapter
        -> tool registry/executor -> empty in the running application
```

- Introduce a `ChatModel` protocol for one model request, including instructions, profile context, history, available tool definitions, and a stream of typed results.
- Model and agent events must represent text deltas, completed structured tool requests, usage, response completion, and safe failures. Plain strings alone cannot express all these outcomes.
- Keep OpenAI SDK classes and wire-format translation inside its outbound adapter. Domain/application contracts must not import SDK objects.
- Use a small factory to choose `simulated` or `openai`. Create and close the async provider client in the application lifecycle, not per message.
- Reuse the compiled graph, with independent state, counters, continuation data, and profile for each invocation. Never store the current user's history or name on the shared model client.
- The graph owns the model/tools cycle. The provider adapter performs one Responses request at a time; do not add another agent runner or automatic tool loop inside it.

## OpenAI integration

- Use the official `openai` Python package, `AsyncOpenAI`, and the Responses API with streaming.
- Use `gpt-6.1-terra` as the configured default for `OPENAI_MODEL`. Allow an explicit override such as `gpt-6.1-sol` or a supported model snapshot. Keep the default in settings, not embedded in graph or provider request code. Never silently switch models after a provider failure.
- Validate `MODEL_PROVIDER` as the closed choice `simulated` or `openai`. Validate `OPENAI_MODEL` as a trimmed, non-empty string rather than a closed model enum, so changing models or snapshots does not require a code change. Only the API key is additionally required when OpenAI is selected; actual model access is determined by the provider on an explicit real request.
- Fail startup clearly for missing configuration. Do not make paid model calls to validate startup or readiness.
- Keep PostgreSQL as conversation storage. Send the complete required history explicitly, with `store=false`; do not use OpenAI Conversations or shared `previous_response_id` state. This setting is not a claim about all provider retention policies.
- Include application instructions in every model request, including tool continuations. Keep user/assistant content in its original role.
- Send no tool definitions when the registry is empty. Do not enable web search, file search, code execution, or other hosted tools.
- Assemble function-call argument fragments into a complete call before validation or execution. Preserve call identifiers and required provider continuation items, including opaque reasoning-related items when returned. Request the appropriate encrypted continuation material when required for stateless execution by the selected model; do not log or display it as user-facing reasoning.
- Treat a provider `response.completed` event as model completion, not persistence success. A failed/incomplete response, output limit, interrupted connection, or malformed tool call must not become a successful saved answer merely because some text arrived.
- Close the response stream on cancellation, timeout, or failure. Preserve bounded execution and lock cleanup from iteration 01.
- Disable automatic SDK retries initially (`max_retries=0`) so attempts and latency remain explicit. Do not silently replay a response after partial text has been streamed.
- Do not send optional model tuning parameters unless explicitly configured and supported by the selected model.

## Financial prompt

Store the prompt at `backend/src/chatbot/prompts/finance.xml`, included in the installed Python package. Load it as UTF-8 and validate it at startup. A missing or malformed prompt fails startup before requests are served.

Use one XML root containing these application-owned sections:

| Section | Required behavior |
| --- | --- |
| `role` | A personal-finance and financial-education assistant. |
| `scope` | Budgeting, saving, debt, credit, interest, and introductory investment concepts. |
| `instructions` | Explain clearly, use relevant examples, and ask for important missing facts rather than guessing. |
| `rules` | Briefly redirect unrelated requests; do not invent live financial data, personal information, sources, tool results, or guaranteed returns. |
| `output_format` | Natural language in the user's language, concise by default, with simple Markdown only when useful. Do not require XML or JSON answers. |
| `examples` | A few short examples of a financial question, an unrelated football question, a greeting, and a financial question involving football expenses. |

The financial scope is educational. Do not claim professional adviser status or invent jurisdiction-specific rules. Current prices, exchange rates, account balances, and live financial facts are unavailable without a future data source.

Allow greetings, clarification, and relevant follow-ups. For mixed requests, address the financial part. A suitable unrelated-topic response is: "I focus on finance. I can help with budgeting, saving, or understanding investments," adapted to the user's language.

XML organizes text; it is not an enforcement mechanism. Send its trusted instructions through OpenAI's instructions/developer channel, separately from conversation content. Do not put tool schemas or a list of nonexistent tools in the XML.

## User profile and context

- Add `users.display_name` as a nullable string of up to 120 characters through Alembic; preserve existing users and conversations.
- Give the existing local fixture users the display names Alice and Bob. Seed operations must not overwrite a name that is already populated.
- Carry an immutable principal/profile containing user ID and optional name into each turn. Keep the local header-based identity mechanism; names are loaded from PostgreSQL, not accepted as trusted instructions in chat requests.
- Include only the available name as per-user reference context. Omit it if missing; do not invent a name or financial profile.
- Keep this dynamic context separate from the static instructions and label it as data, not commands. XML-escape values if rendering them inside XML. A name containing XML or instruction-like text must not alter the application prompt.
- Do not add memory, summaries, preferences inferred from history, or empty RAG sections.
- Log a hash/version of the static prompt for traceability, not the user's rendered context or the full prompt text.

## Prepared tool execution

Implement the minimal graph branches and contracts now:

```text
START -> model
           | no tool calls and successful completion -> END
           | tool calls -> validate -> execute registered tools -> model
```

- The runtime registry is empty. Normal OpenAI execution therefore completes without a tool step.
- Define a minimal tool contract with name, description, JSON argument schema, and async handler. Do not ship concrete handlers in the application.
- The model requests tools; the backend validates and executes them. Never resolve callable names through imports, `eval`, or user-controlled module paths.
- Reject unknown tool names, malformed/incomplete arguments, or schema violations without invoking a handler. Use a safe terminal error in this initial implementation.
- Support several requested tools and repeated requests to the same tool. Execute tool batches sequentially initially; parallel tool execution is outside scope.
- Match every result to the original call identifier and preserve provider-required output items for the next model request. Tool output is reference data, not privileged instructions.
- Increment model/tool counters before invocation. One model response may contain multiple tool requests, so a graph step is not a substitute for either counter.
- Before starting a tool, check the deadline, remaining budget, and lock validity. Finish/cancel its task before releasing the conversation lock.
- A test may inject synthetic tool definitions and handlers. They must not be registered or advertised by the normal application startup.

## Configuration and initial limits

Use validated settings and expose relevant values through Compose and `.env.example`. Document how to apply changes with `make start`.

| Setting | Initial value or rule |
| --- | --- |
| `MODEL_PROVIDER` | `simulated` by default; `openai` selects the real integration. |
| `OPENAI_API_KEY` | Required only for OpenAI; untracked `.env` locally; never logged or baked into the image. |
| `OPENAI_MODEL` | Defaults to `gpt-6.1-terra` for OpenAI. Override with a non-empty model ID, for example `gpt-6.1-sol`; no closed model enum. |
| `MAX_ACTIVE_TURNS` | Keep `4` per worker process. |
| `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` | Keep `20` submissions per user per rolling `60` seconds, including rejected submissions as in iteration 01. |
| `TURN_TIMEOUT_SECONDS` | Keep `30`; one deadline from admission through generation and final persistence, never reset between graph rounds. |
| `MODEL_TIMEOUT_SECONDS` | Keep `20`, applied separately to each model request, bounded by the remaining turn deadline. Remove the old whole-agent timeout wrapper that currently uses this setting. |
| `TOOL_TIMEOUT_SECONDS` | `5` per future tool invocation, also bounded by the remaining turn deadline. |
| `MAX_MODEL_CALLS` | `4` per turn; an empty registry normally needs one. |
| `MAX_TOOL_CALLS` | `8` per turn; actual count remains zero with the runtime registry empty. |
| `GRAPH_RECURSION_LIMIT` | `12`; a graph runtime bound separate from model/tool counts. |
| `OPENAI_MAX_OUTPUT_TOKENS` | `2048` per model response; preserve provider semantics, including reasoning-token consumption where applicable. Treat an exhausted/incomplete output as a bounded failure. |

These are configurable starting limits, not capacity or cost guarantees. Keep all saved history; do not truncate it to fit the provider. Surface a context-limit error clearly instead. Do not validate model access, account credits, or provider quotas through paid startup requests; surface provider rejections when the user explicitly makes a real request.

## Persistence and HTTP contract

- Keep the four existing tables. Use the next Alembic migration for the display name and small JSONB turn fields for execution metadata and the ordered agent/provider transcript; avoid separate unused tool tables.
- Keep canonical user/assistant text in `messages`. The ordered turn transcript must be able to preserve model output items, tool requests/results, call IDs, and provider-specific continuation data needed for replay. Complete items are distinct from partial streamed deltas.
- Store the final transcript/metadata alongside the successful assistant message and completed turn in a short transaction. Handle failures and partial output as in iteration 01; do not claim durable, resumable side-effecting tool execution in this iteration.
- Reconstruct full model context without duplicating assistant text already represented by a stored provider item. Never replay a completed turn's tool handler merely because its history is loaded.
- Update schema readiness to expect the current migration head rather than the hard-coded `0001_initial` revision.
- Keep `GET/POST /v1/chat/messages`, `started`, `delta`, `completed`, and `error`. Internal model events are translated into these existing HTTP events; do not leak raw SDK events.
- An optional metadata object on `completed` may include provider/model, prompt revision, aggregate usage, and actual model/tool call counts. Emit `completed` only after persistence commits.
- Only complete assistant messages enter canonical history. Provider failure after deltas emits `error`; cancellation and timeout stop work and release the lock/admission slot.

## Errors and observability

- Distinguish upstream authentication/configuration, rate/quota limits, connection failures, timeouts, context/output limits, invalid tool calls, and incomplete generation using safe application error codes.
- Do not confuse an upstream OpenAI rate/quota error with our per-user message rate limit. Before streaming, map configuration/upstream failures to appropriate HTTP errors; after streaming starts, use the SSE error event.
- Record actual provider/model, per-call and total timings, time to first text delta, call counts, outcome, prompt revision, and provider request IDs when available.
- Record provider-reported input/output/total tokens and available cached/reasoning token categories. Sum per-call usage for the turn without double-counting stream completion events.
- Mark missing usage as unavailable/partial rather than zero or guessed. Do not calculate monetary costs from hard-coded pricing.
- Remove hard-coded simulated-provider/model-call assumptions from the orchestrator's logs.
- Never log API keys, names/profile context, conversation bodies, full tool arguments/results, or opaque provider reasoning data by default.

## Planned file changes

Paths below are relative to `backend/`; create only the files needed by the implemented boundaries.

| Location | Change |
| --- | --- |
| `src/chatbot/domain/agent.py` | Typed model/agent events, usage, tool calls, and transcript representations. |
| `src/chatbot/domain/models.py` | Minimal principal/profile and turn metadata integration. |
| `src/chatbot/application/ports.py` | Add the model contract and evolve agent/repository contracts for typed output and profile data. |
| `src/chatbot/application/tools.py` | Minimal definitions, validation/execution contract, and empty registry; no concrete tools. |
| `src/chatbot/application/orchestrator.py` | Consume typed agent output, preserve existing coordination, and apply the total deadline and real execution metadata. |
| `src/chatbot/adapters/outbound/models/openai.py` | Async Responses integration and translation to/from provider-independent contracts. |
| `src/chatbot/adapters/outbound/models/simulated.py` | Move/adapt the existing simulated model; keep normal tests offline. |
| `src/chatbot/adapters/outbound/models/factory.py` | Select the configured provider and own no user-specific state. |
| `src/chatbot/adapters/outbound/agent/graph.py` | Inject the model port and implement conditional model/tools routing and counters. |
| `src/chatbot/prompts/finance.xml` and prompt loader | Versioned static XML instructions, package loading, validation, and revision hash. |
| PostgreSQL/identity adapters and `migrations/versions/` | Add/load display names, persist metadata/transcripts, and update schema readiness and seed behavior. |
| HTTP adapters, `app.py`, and `config.py` | Wire the selected provider and profile, manage client lifecycle, and preserve the external chat interface. |
| Dependencies/lockfile, Compose, `.env.example`, README, and tests | SDK dependency, configuration, usage instructions, and focused checks. |

Keep the existing Make commands. `make start` must still work without OpenAI credentials in simulated mode; `make chat` uses whichever provider is configured. Do not add automatic paid smoke tests to startup or `make test`.

## Acceptance criteria

Use the existing test arrangement: focused pytest checks and isolated databases in the current PostgreSQL service, with no extra test containers.

1. Existing startup, history, isolation, locking, cancellation, and rate-limit behavior still passes.
2. Simulated mode runs without OpenAI credentials. OpenAI mode defaults to `gpt-6.1-terra`, accepts an explicit model override, rejects a blank model or missing key, and makes no paid startup call. Tests verify the configured model reaches the adapter without a hidden fallback.
3. A mocked SDK stream produces incremental text, usage, and completion through the graph and HTTP contract. Failed, incomplete, malformed, or interrupted streams never emit a persisted-success event.
4. The provider client is reused safely and closed at shutdown. Timeout/disconnect tests verify work stops before lock release, including across model/tool rounds.
5. The XML prompt loads from the installed package, has the required sections and a stable revision, and malformed/missing files fail clearly.
6. Each request receives only its own user's name and full history. Missing names, XML characters, and instruction-like names do not alter the trusted prompt.
7. Migration from iteration 01 preserves users/messages, fills only missing fixture names, supports metadata/transcripts, and succeeds when re-run.
8. The normal registry is empty and the real provider request advertises no tools. Synthetic fixtures verify multiple calls in one round, repeated calls to one tool, correct result IDs/continuation items, and termination without tools.
9. Fixtures verify unknown tools, invalid arguments, model/tool budgets, graph bounds, and total/per-operation deadlines without executing arbitrary code.
10. Persisted transcripts can be reconstructed without duplicated text or re-executing historical tools. Usage aggregates preserve missing values and do not double-count.
11. Normal tests remain deterministic and offline. A manual, explicitly requested OpenAI check may verify a financial question, an unrelated football question, a greeting, the user's name, and a history follow-up. Do not claim that mocks prove the live model always follows the financial scope.

## Completion and references

The implementation is complete when the local workflow and focused tests pass and the optional real-provider check is reported separately if run. This specification alone does not start implementation or authorize model spending.

Primary API references:

- [OpenAI Python SDK](https://developers.openai.com/api/reference/python)
- [Streaming responses](https://developers.openai.com/api/docs/guides/streaming-responses)
- [Function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [Responses API state and output items](https://developers.openai.com/api/docs/guides/migrate-to-responses)
- [Prompt roles and XML sections](https://developers.openai.com/api/docs/guides/prompt-engineering)
