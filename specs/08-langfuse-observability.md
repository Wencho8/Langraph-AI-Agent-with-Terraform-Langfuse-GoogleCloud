# Iteration 08 — Langfuse observability

## Goal

Use Langfuse Cloud on the Hobby plan to inspect one trace per chat turn that the backend starts. The trace should show how many tokens the turn used, which tools ran, and where the time went. Validate locally before enabling production tracing.

## What to measure

| Scope | Fields |
| --- | --- |
| Chat turn | Request and turn IDs, environment, total duration, time from turn start to the first text sent by the backend, and final status (completed, failed, timed out, or cancelled). |
| Model call | One generation observation per OpenAI call, with model, reasoning effort, duration, status, time to the first text chunk when available, and the input and output token counts reported by OpenAI. |
| Tool call | One observation per execution, with the registered tool name, duration, and status. Keep repeated calls separate and show their execution order. |

Show turn-level token totals from the individual model calls. Input usage includes the history, prompt, and tool results that the backend sends back to OpenAI. If usage is unavailable for a call, mark the totals as incomplete and show known counts on individual generations. Keep token counts on generation observations for aggregation and use separate metadata for the turn summary so totals are counted once.

## Privacy

Send only the allowlisted fields above and fixed technical error codes. Exclude user messages, assistant text, chat history, system prompts, tool arguments and results, raw exceptions, user names and emails, and credentials. Use request and turn IDs to correlate with Cloud Logging. Inspect an actual test trace for unexpected fields before enabling production.

## Backend integration

Initialize the Langfuse Python SDK once in the FastAPI lifecycle when tracing is configured. Start the turn observation in the orchestrator and attach child observations around the existing OpenAI and tool calls in the LangGraph adapter. Reuse existing timing and usage measurements. Close observations on failure and cancellation as well as success.

Export traces in batches in the background and keep network waits off the streaming path. Tracing failures must leave the chat request and its normal logs usable. Keep Cloud Run's request-based billing and attempt a bounded export at shutdown without blocking the event loop. Traces still queued when CPU is throttled or the instance exits may arrive late or be lost. Use the Langfuse Agent Skill and SDK documentation as implementation references.

## Configuration and rollout

1. **Local.** Read `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL` from the ignored backend `.env`. Label local traces separately from production. With tracing unconfigured, the app runs without exporting traces.
2. **Production.** Use Terraform to declare a Secret Manager secret and give the Cloud Run backend service account access. Set the public key and regional base URL in the backend configuration. The operator loads the secret key as a Secret Manager version outside Terraform, then enables tracing with that version. Keep the secret key out of Git and Terraform state. Langfuse configuration belongs to the backend.
3. **Verification.** Start with a chat message that calls more than one tool. Confirm that the stream works as usual and that the dashboard shows one turn with separate model and tool steps, correct timings and token totals, and no chat content. Exercise a timeout or cancellation and verify that unavailable usage stays unknown. Verify that an unavailable exporter does not interrupt the chat.

For an existing local Compose setup, rebuild the backend and run the focused tests in its running container.

```sh
docker compose --env-file backend/.env --env-file frontend/.env up -d --build --wait backend
docker compose --env-file backend/.env --env-file frontend/.env exec -T backend pytest -q tests/test_langfuse.py
```

In production, plan and apply with `enable_langfuse` still false to create `langfuse-secret-key` and its access grant. In Secret Manager, add the secret key as a version. Once the backend image includes this iteration, set `enable_langfuse = true`, `langfuse_public_key`, and `langfuse_secret_version` to the enabled numeric version. Set `langfuse_base_url` if the project's URL differs from the US default. Review the new plan and apply it, then verify that Cloud Run traffic reaches the revision with tracing configured.

## References

- [Langfuse trace data model](https://langfuse.com/docs/observability/data-model)
- [Langfuse token and cost tracking](https://langfuse.com/docs/observability/features/token-and-cost-tracking)
- [Langfuse background export](https://langfuse.com/docs/observability/features/queuing-batching)
- [Langfuse Agent Skill](https://github.com/langfuse/skills)
- [Cloud Run billing and CPU allocation](https://docs.cloud.google.com/run/docs/configuring/billing-settings)
