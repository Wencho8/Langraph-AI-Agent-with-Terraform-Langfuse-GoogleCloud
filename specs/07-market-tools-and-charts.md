# Iteration 07 — IOL market tools and inline charts

## Goal and release boundary

Use GPT-6.1 Terra with high reasoning to answer market questions through real, read-only IOL tools and render inline charts. Implement and review locally first. Do not commit, push, deploy, apply Terraform, or create additional test containers. The operator runs the application and cloud commands. Add automated tests with mocked HTTP/model responses and the existing isolated PostgreSQL fixtures.

## Decisions

- `MODEL=openai:gpt-6.1-terra`, `MODEL_REASONING_EFFORT=high`. Preserve model configurability and the simulated model for offline tests only.
- `MARKET_DATA_PROVIDER=iol` locally; `disabled` keeps existing deployments usable until credentials are installed. No simulated market provider and no fabricated fallback on API errors.
- Local IOL credentials belong only in the ignored backend env file (mode 0600), never here, logs, examples, Git, Terraform variables/state, or the browser. Cloud credentials use a Secret Manager JSON secret containing username/password; Terraform manages its empty container and runtime-only access. Access/refresh tokens remain in backend memory and expiry follows the API's `expires_in`.
- Native async HTTP, graph nodes, tools, and database calls. Reuse an async HTTP client, serialize token renewal with an async lock, bound HTTP timeouts and responses. No `requests`, synchronous broker SDK, per-turn loop, or per-request thread.
- Keep the compiled LangGraph model/tools loop and existing allowlisted JSON Schema registry. Four tools: `search_instruments`, `get_quote`, `get_price_history`, `show_chart`.
- Only public market-data reads are exposed. No portfolio, balance, order, transfer, or trade tools. Authentication POSTs are used only internally by the adapter.
- Start with IOL-supported Argentine instruments. US market support is conditional on actual account/catalog coverage; never confuse an Argentine CEDEAR with its US underlying. Other providers are deferred.

## Tool contracts and chart flow

Search returns bounded instrument candidates with market-qualified IDs, ticker, description, currency/type when available. Quote returns source, provider timestamp and retrieval timestamp; unknown metadata remains unknown. History returns bounded daily closes and a per-invocation series reference plus summary. Empty/unsupported instruments and provider failures produce safe structured tool results so the agent can explain or retry within limits.

Each invocation owns its instrument/series references, chart counter, and presentation state; shared adapters never store conversation data. A chart may reference only history retrieved within that invocation. `show_chart` accepts one to three series, title, and absolute/base-100 mode. Backend-owned points and calculations become a typed chart event, not model-generated JavaScript, HTML, or prices. Mixed currencies cannot be plotted on a shared absolute-price axis. Base 100 is a relative price comparison, not total return or currency-adjusted performance. Missing dates are not forward-filled.

Unadjusted prices cannot establish performance across a split or other corporate action. Reject a halving or a twofold increase between consecutive observations before returning a history summary/reference, using `history_comparability_unverified`. Do not rescale automatically or infer the cause. This conservative gate may reject real extreme moves and does not detect all corporate actions. Requesting IOL's adjusted endpoint is insufficient without verification: live YPFDD returned empty and YPFD retained its split discontinuity. Reliable corporate-action adjustment is deferred. On an unverified series, withhold charts/percentage claims and offer a verified source or an unaffected period; preserve existing snapshots as historical output.

Stream ordered Markdown text blocks and chart blocks over SSE, with final canonical blocks on completion. Charts show source, instrument, currency, date range, price-adjustment mode and last provider timestamp where available. Save blocks with the assistant message in JSONB through an Alembic migration, preserving old messages/content and conversation ownership. Historical charts replay saved snapshots; replay never executes tools or refetches prices. Partial failed streams are visibly unsaved.

## Prompt and UI

Extend the existing finance XML sections: tools for current prices/history, clarify ambiguous symbols/markets, distinguish currencies/settlement and CEDEARs/underlyings, disclose missing/stale data, use charts for useful historical comparisons, and never claim unavailable tool results. Tool outputs remain untrusted data. Keep normal Markdown prose; charts are structured blocks rendered by Recharts in React. No external chart service or new frontend credentials.

### Live tool activity

The graph emits tool start/finish events through LangGraph's custom stream. The orchestrator exposes `tool_status` frames on the existing POST/SSE response, alongside text and charts. Include only the call ID, allowlisted tool name, status and elapsed milliseconds. Do not stream arguments, provider payloads, credentials or private model reasoning.

Show a compact activity panel below “Pensando…”/“Respondiendo…”, expanded by default and collapsible without losing the user's choice as events arrive. Friendly labels identify each operation; repeated calls remain separate rows by call ID. The user-facing panel uses a white circle during a call and a blue circle when it ends, regardless of outcome; it shows no OK/failed labels, red/green icons or timings. Three animated dots remain visible throughout the active turn, including model iterations between tool batches and while the panel is collapsed. Internal backend outcomes remain unchanged. Connection loss closes remaining running indicators.

Offer three editable finance/market/chart starter prompts when history is empty. With history, show two compact rounded suggestion chips directly above the composer; disable them while responding or logging out. Selecting a suggestion fills the draft without automatically sending it.

Activity is transient per-turn UI state, preserved across the final history refresh but not saved in message history or replayed after a page reload. Charts/text remain persisted. This adds no migration, Terraform resource or model prompt instruction.

## Initial bounds

Local starting values: 8192 output tokens per model call, 120 seconds per model call, 240 seconds per turn, 10 seconds per tool, four model calls, eight tool calls, graph recursion 12. Bound daily histories to two years/750 points, charts to three series and two charts per turn, search to 20 candidates. Keep cache size/TTL and HTTP response sizes bounded. Measure before adopting cloud limits; cloud request timeout must exceed the application deadline when enabled.

## Expected files

- Domain market/presentation values; application market-data port and market/chart tool construction.
- IOL async outbound adapter; app lifecycle/composition and configuration; OpenAI reasoning parameter.
- LangGraph invocation-local tool context and chart events; orchestrator, HTTP/SSE schemas and PostgreSQL block persistence; migration 0005.
- React message block renderer, Recharts component, typed SSE events, backward-compatible history.
- Backend/frontend env examples, Compose forwarding, dependency locks, Terraform secret/optional configuration, definitions and README review instructions.

## Acceptance

1. Login and the real AL30/GD30 search, quote, historical retrieval and base-100 chart chain have been validated. Other instrument types/ON coverage still require manual checks.
2. Offline tests exercise credential refresh, failures/redaction, nonblocking HTTP, normalization, repeated tool calls, chart isolation/bounds, ordered streaming, history persistence and frontend rendering.
3. User can request a comparison, observe actual model/tool rounds, receive a chart without explicitly asking for one, reload history and see the same chart.
4. Existing authentication/approval, locks, deadlines, token/timing logs and per-user history isolation remain enforced.
5. No secrets are committed and no infrastructure is applied automatically. Live model/broker coverage remains an operator acceptance step.

## References

- https://docs.langchain.com/oss/python/langgraph/workflows-agents
- https://docs.langchain.com/oss/python/langgraph/streaming
- https://developers.openai.com/api/docs/models/gpt-6.1-terra
- https://api.invertironline.com/Help/Autenticacion
- https://recharts.github.io/en-US/
