# Market tools — local review

Iteration 07 uses real IOL market data and GPT-6.1 Terra at high reasoning effort. The local backend env is ignored and mode 0600; credentials never belong in this document. Do not print `docker compose config` or paste env files because rendered configuration includes secrets.

## Start locally

1. Run `make start`. This rebuilds both application images, applies migration `0005_message_blocks` to the ordinary local PostgreSQL, seeds development identities and starts the services. No cloud operation is performed. The new migration preserves accounts, approval flags, sessions, text and history.
2. Open http://localhost:5173 and sign in with an approved local chatbot account. This identity is separate from the broker credentials held by the backend.
3. Ask: “Buscá AL30 y GD30, consultá sus precios e indicá moneda y fecha de la cotización”.
4. Ask: “Compará AL30 y GD30 desde el 1 de enero de 2026 hasta hoy con un gráfico base 100. Explicá qué estoy comparando”.
5. Check the sequence of text/chart/text, chart labels, saved history after reload, unrelated-topic refusal, unsupported US listing requests and missing instruments.
6. Run `make test` when ready. Backend tests use temporary databases inside the existing PostgreSQL, not additional test containers. Provider/model tests use HTTP fixtures and never spend API credits or contact IOL.

If IOL returns an unexpected payload or permission error, the tool returns a bounded error code. It never invents prices, substitutes a different asset or falls back to simulated data. Login/quote were previously verified manually; the AL30/GD30 search, quote, year-to-date history and base-100 chart chain were subsequently validated against live IOL. Other instruments and ON coverage still require live acceptance. Histories use the provider-default settlement because IOL's history endpoint has no settlement selector. T0 historical requests return an explicit limitation.

## Architecture

`app.py` constructs the native async IOL adapter and a per-turn tool-registry factory. One compiled LangGraph is reused. Each invocation creates its own series map and chart counter. OpenAI chooses tools via function calling; the graph executes sequential async handlers and returns their results to the model. Network waits yield the event loop. Token renewal uses an async lock. Shared bounded caches contain only public market responses, not conversation context.

History returns a series reference plus summary to the model. The full bounded daily points stay in invocation memory and are copied into chart snapshots. `show_chart` accepts only references from that invocation, emits a `chart` SSE event, and returns a confirmation to the model. Text deltas continue around it. Complete messages save ordered `blocks` JSONB with legacy text and transcript in the same database transaction; failed partials stay visibly unsaved. Existing ownership checks protect chart history too.

Chart limits: three series, two charts, up to two years/750 daily points per series. No forward filling. Base 100 uses common trading dates and is price evolution, not total return or FX conversion. Unknown currency/time remains unknown. Recharts is loaded only when a chart is rendered.

### Historical comparability and corporate actions

IOL's unadjusted history can cross a stock split. The July–October 2026 YPF series illustrates this: live YPFDD reads returned 53.90 before the split and 5.08 afterward. [YPF confirms a ten-for-one local-share split in August](https://inversores.ypf.com/capital-suscripto.html). Those raw per-share prices cannot directly establish an economic loss of about 90%.

The official Swagger at `https://api.invertironline.com/v2/swagger` accepts `ajustada` and `sinAjustar`. Manual checks of `ajustada` returned an empty YPFDD series and the same discontinuity for YPFD. Do not assume requesting that path proves adjustment, use the futures-only `precioAjuste` field as an equity adjustment, or hard-code a ticker/date/factor into the adapter.

Before issuing a series reference or summary, the application rejects a twofold increase or a halving between consecutive observations with `history_comparability_unverified`. This is a conservative quality gate, not a diagnosis of a split: real extreme moves can also be rejected, and smaller corporate actions can escape it. No prices are rescaled. The model is instructed to withhold the comparison/chart and offer a verified adjusted source or a range that avoids the discontinuity. Base 100 alone does not correct corporate actions. A complete corporate-action feed and reliable adjusted series remain future work.

Previously saved chart snapshots and answer text are preserved; they are not retroactively corrected. New queries use the quality gate after rebuilding the local backend.

### Live progress

Each tool emits a start event before awaiting its handler and a finish event with outcome/duration. The same SSE response carries `tool_status`, `delta`, `chart` and terminal events. The browser shows an expanded, collapsible “Herramientas” panel beneath the thinking/response indicator. Labels come from a frontend allowlist. White/blue circles indicate a running/finished call regardless of outcome; user-facing tool rows omit success/failure labels and timings. Three animated dots appear below the last tool step while the expanded panel has an active turn, including model iterations between tools. They disappear on completion or collapse. Backend status remains available internally. Separate call IDs distinguish repeated use of one tool.

Only tool name, ID, status and timing reach this panel. A safe provider error is shown as failed; a lost connection marks unfinished calls interrupted. Progress remains visible after the final answer within the current page session, including the canonical history refresh, but disappears after reloading the page. No new database schema or infrastructure is required for progress.

Tools currently search Argentine actions, CEDEARs, government bonds, ON and letras through IOL panels. A CEDEAR is not the US listing. US APIs, trading, portfolio access, TIR/duration calculations, candlesticks, chart export, RAG and other providers are outside this iteration.

## Configuration and future cloud enablement

Local settings: `MODEL=openai:gpt-6.1-terra`, `MODEL_REASONING_EFFORT=high`, `MARKET_DATA_PROVIDER=iol`, `IOL_CREDENTIALS` (JSON secret), model output 8192, model deadline 120s, turn deadline 240s, tool deadline 10s. Keep credentials as single-quoted JSON in Compose's env file so dollar signs in a password remain literal.

`MARKET_DATA_PROVIDER=disabled` registers no market tools and requires no broker credentials. Tests enforce this setting unless explicitly exercising fixtures. The simulated model remains an offline testing option; no simulated market provider exists.

Terraform is prepared but not applied: an empty `iol-credentials` Secret Manager container, runtime-only read access, and conditional Cloud Run injection controlled by `enable_iol` (false by default) plus a numeric `iol_secret_version`. Populate the version separately, never via a Terraform secret-version resource or plaintext tfvars. Enable IOL only after the operator reviews/applies the cloud configuration. Prepared Cloud Run timeout is 270s, exceeding the app's 240s deadline. Existing production configuration does not change merely because files were edited.

There is no automatic proof of market-data redistribution rights or complete instrument coverage. Confirm account access/conditions before enabling the integration for other users.

## IOL payload normalization and daily history

The live catalog uses numeric string codes for market/currency and uppercase settlements, unlike the named values in reference endpoints. Normalize the verified BCBA/ARS/USD variants and settlement case at the adapter boundary. Quote requests use `plazo`, not the Swagger-generated `model.plazo` query name; validate the reported settlement.

History mixes older daily snapshots and recent intraday records. Incrementally parse the array, discard unused fields and retain the last reported price per day. Bound transport to 64 MB/100,000 records, each incomplete record buffer to 128 KB and output to 750 daily points. Cooperatively yield during parsing; never hold the entire raw response/list in memory. IOL date-only end bounds are exclusive: an end date of today returns previous completed sessions, which is disclosed to the model.
