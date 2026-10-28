# Iteration 05 — Firebase Hosting

Status: functionally complete and closed by the user on 2026-10-28. Firebase Hosting is deployed and the user reports that browser acceptance works. RAM/log/cost inspection and rollback/teardown guidance remain explicit operational follow-ups, not verified completion claims. GitHub Actions is deferred to iteration 06 and does not start automatically.

Project decisions: [Definitions](../doc/definitions.md). Prerequisite: [Iteration 04 — Backend Deployment](04-guided-google-cloud-deployment.md), completed.

## Goal

Publish the existing React frontend on Firebase Hosting and connect it to the deployed FastAPI backend. Verify the full browser experience without changing the authentication design or adding new product features.

## Starting point before this iteration

- Existing Google Cloud project: `wencho8-chatbot-prod`; reuse its trial billing account.
- Backend: `chatbot-backend`, region `us-central1`, URL `https://chatbot-backend-dasag4h7iq-uc.a.run.app`.
- The user applied the backend and verified HTTP 200 from `/health/live` and `/health/ready`.
- PostgreSQL schema and passwordless IAM access are configured; migration execution `chatbot-migrate-xbqs5` succeeded.
- Planned frontend origin: `https://wencho8-chatbot-prod.web.app`, already configured in the backend. The site has not been published or verified.
- React + TypeScript + Vite + Tailwind frontend exists under `frontend/`; authentication remains in Python/PostgreSQL, with the `__session` cookie.

## Guided working agreement

- Continue in small supervised batches. Explain the files, tools, costs, and expected result before each batch.
- The user executes all Terraform, gcloud, Firebase, build, and deployment commands, including cloud checks. The assistant provides commands and reviews the returned output.
- The assistant creates or edits implementation files only after the user approves the proposed batch. Writing this spec does not authorize those files.
- Inspect Terraform plans together before applying. Keep personal CLI/ADC/Firebase credentials separate from work credentials; never change the work configuration or log out the work account.
- Do not stage, commit, push, start CI/CD, or provision staging without an explicit request.
- Record only verified or user-reported outcomes. Stop after each batch for the user's result.

## Scope and tool ownership

| Tool | Responsibility |
| --- | --- |
| Terraform | Associate Firebase with the existing project and manage supported Hosting infrastructure/APIs/permissions. Confirm provider support and required permissions before choosing the concrete resources. Reuse the production state; do not create another cloud project. |
| Firebase CLI | Authenticate as the personal user, select the explicit project, and publish compiled frontend assets plus Hosting routing configuration. Publication is separate from provisioning. |
| Local build tools | Build the existing frontend into `dist/`; do not deploy the Vite development server. |
| gcloud | Review backend configuration/logs and perform explicit backend operations if required. |
| Browser | Personal authorization, console inspection, and end-to-end user tests. |

Do not manually recreate Terraform-owned resources in the console. Explain any unsupported operation and its ownership before proceeding. Do not enable Firebase Authentication, Analytics, Firestore, App Hosting, or unrelated services.

## Small implementation batches

| Batch | Work | Checkpoint |
| --- | --- | --- |
| 1. Personal access and Hosting infrastructure | Confirm the personal Firebase CLI identity, project, current trial/billing requirements, APIs, and Terraform support. Propose the minimum files and review the infrastructure plan. | Firebase is associated with the existing project and the intended Hosting site exists. |
| 2. Routing and build configuration | Propose Hosting configuration that serves compiled static assets, rewrites `/v1/**` to `chatbot-backend` in `us-central1`, and places the SPA fallback after API routing. Configure caching deliberately. | The user can review exactly which files are published and where API calls go. |
| 3. Manual publication | Build and deploy only Hosting to the explicit personal project. Confirm the actual HTTPS domain and backend `APP_ORIGIN`; update Terraform only if needed. | The frontend loads at its Firebase URL and reaches the existing backend. |
| 4. Browser acceptance | Test registration, login, chat, streaming, history, logout, and isolation with two separate browser sessions. The user explicitly performs the real OpenAI check. | The deployed experience works with secure sessions and incremental responses. |
| 5. Brief operational handoff | Review existing dashboards/logs/costs and document manual updates, rollback limitations, and intentional teardown. | The user knows how to inspect and repeat the deployment without adding a monitoring or load-testing project. |

## Integration requirements

- Keep one browser origin: frontend API calls use relative `/v1/...` paths through Hosting rewrites. Do not introduce permissive credentialed CORS or cross-site cookie workarounds.
- Verify the `__session` cookie is forwarded and remains HttpOnly, Secure, and SameSite=Lax. Maintain the exact allowed origin and CSRF token checks.
- Keep private API responses, history, auth responses, and streams out of shared caches. Verify the existing `Cache-Control: no-store` survives the deployed path.
- Preserve the existing 30-second turn deadline, 20-second model timeout, and 60-second Cloud Run timeout. Confirm Hosting's current timeout and streaming behavior before publication.
- Observe chunks arriving incrementally through the real Hosting URL; a complete final answer alone does not prove streaming. If Hosting buffers or breaks streaming, explain the evidence and discuss a routing alternative before changing the architecture.
- Block the input while a response is running and preserve Markdown rendering, error handling, cancellation, and session-expiration behavior.
- Protected endpoints require a valid unrevoked session even when called directly through the Cloud Run URL. A user cannot choose another user's identity or conversation.
- Keep existing bounded process-local rate limits; their restart/revision-overlap limitations are accepted for this trial. Review proxy/client-IP behavior before trusting any forwarded headers.
- Keep production data separate from local fixtures. Register real test accounts; do not upload local users, messages, or development passwords.

## Operational review carried from iteration 04

Pending follow-up after functional closure: the user agreed to close the deployed application work without treating these operational checks as already performed.

- Find Cloud SQL memory usage/components, distinguish active usage from reclaimable cache, and inspect CPU, connections, and disk.
- Find Cloud Run memory/CPU, instance count, requests, latency, startup failures, and errors separately from database metrics.
- Inspect safe application timings, token usage, request/turn IDs, and rejection events without logging secrets or conversation text.
- Review billing and trial consumption; promotional credits are not unlimited free use. Cloud SQL remains running when Cloud Run scales to zero. OpenAI is billed separately.
- Document manual Hosting and backend updates, deliberate migration execution, application rollback versus schema compatibility, and intentional resource removal with deletion protection and residual costs. Do not execute teardown.

Use built-in dashboards or Metrics Explorer and the user's small two-user test. No new dashboard/alert resources are required by default; no extra test containers or load-testing project.

## Functional completion criteria

- The frontend is published on the verified Firebase HTTPS domain, with API rewrites reaching the existing backend.
- Registration, login, secure session/CSRF handling, persisted history, incremental streaming, and logout work in the browser.
- Two users have separate conversations; protected direct backend calls cannot bypass authentication or ownership checks.
- The user completes a chat turn through the deployed application with the configured OpenAI provider. The remaining operational review is tracked separately above.

## Completion evidence

- The user installed Firebase CLI and authenticated as the personal account, leaving work credentials unchanged.
- Terraform initialized `google-beta` v7.46.2 and the user applied the reviewed plan: two API resources and Firebase enablement, three additions with no changes or deletions.
- The project appeared in `firebase projects:list` after a brief propagation delay. `hosting:sites:list` confirmed the automatically created site `wencho8-chatbot-prod`, with URL `https://wencho8-chatbot-prod.web.app`. No separate Hosting site resource was created.
- `firebase.json` publishes `frontend/dist`, rewrites `/v1/**` to `chatbot-backend` in `us-central1`, and places the SPA fallback last. `.gitignore` excludes Firebase cache/debug logs.
- The user built the frontend successfully and Firebase CLI uploaded three files, finalized the version, and released it to Hosting.
- An initial loading screen was reported. Both the Hosting URL and direct backend URL subsequently returned the expected HTTP 401 JSON for unauthenticated `/v1/auth/session`, with `Cache-Control: no-store`. No code fix was made; the cause of that initial delay was not established.
- The user then showed a successful authenticated chat response addressed to their display name and confirmed the browser flow works. Browser acceptance is user-reported; no independent cloud security audit or load test was performed.
- Operational checks listed above remain pending. No CI/CD or staging work was started.

## Repeat the manual frontend release

From the repository root, install/build locally, then publish only Hosting after a successful build:

```bash
npm --prefix frontend ci
npm --prefix frontend run build
firebase deploy --only hosting --project=wencho8-chatbot-prod --account=wenchoavalos8@gmail.com
```

This updates frontend assets and Hosting configuration; backend image updates and database migrations are separate operations.

## Boundaries and next iteration

No GitHub Actions, staging, concrete tools, RAG, custom domain, VPN/VPC, Valkey, advanced tracing stack, or backup/restore project. [Definitions](../doc/definitions.md) assigns GitHub Actions to iteration 06 and staging to iteration 07.

## References to verify during implementation

- [Firebase Hosting quickstart](https://firebase.google.com/docs/hosting/quickstart)
- [Hosting with Cloud Run](https://firebase.google.com/docs/hosting/cloud-run)
- [Hosting cache and cookie behavior](https://firebase.google.com/docs/hosting/manage-cache)
- [Firebase Terraform guide](https://firebase.google.com/docs/projects/terraform/get-started)
- [Cloud Run autoscaling](https://docs.cloud.google.com/run/docs/about-instance-autoscaling)
