# Iteration 04 — Guided Google Cloud Backend Deployment

Status: complete, closed by the user on 2026-10-28 with the scope limited to backend infrastructure and deployment. The user applied Cloud Run and its invocation permission, then verified HTTP 200 from both live and ready endpoints. Firebase Hosting, browser acceptance, and the remaining operational review move to [Iteration 05](05-firebase-hosting.md); they are not claimed as verified here. Shared rate limits remain explicitly deferred for the personal trial.

Project decisions: [Definitions](../doc/definitions.md). Local baseline: [Iteration 03](03-users-and-chat-ui.md).

## Goal

Deploy the existing Python backend and PostgreSQL database to Google Cloud and learn how infrastructure, permissions, secrets, image publication, and migrations fit together. Start with one environment named production, used personally for testing with approximately two concurrent users. Frontend publication is a separate iteration.

Optimize for understandable infrastructure and low reasonable cost. The USD 300 trial credit is a funding source, not a spending target. Do not introduce resources simply to consume the credit.

## Mandatory guided working agreement

This iteration is a user-operated learning exercise, not an autonomous implementation task.

- The user executes every implementation command. The assistant must not run terminal commands, authenticate, provision resources, build images, deploy applications, run migrations, or execute tests on the user's behalf during this guided iteration. This includes read-only implementation checks: provide the command and let the user run it.
- The user supervises every file creation and edit. The default is to explain the file and provide a small, reviewable snippet or patch for the user to apply. The assistant must not silently create or edit implementation files. A direct user request to edit a specific file or batch permits that edit only; it does not authorize executing the rest of the iteration.
- This initial specification is explicitly authorized. No infrastructure or application implementation follows automatically from writing it.
- Work in small batches: a few related commands or files at a time, never the entire deployment in one batch. One learning outcome should normally fit in one batch.
- Before each batch, explain its purpose, the affected files/resources, which tool performs each action, whether it creates ongoing cost, and what success should look like.
- After each batch, wait for the user's result or confirmation. Explain relevant output, resolve problems, and only then introduce the next batch. Never interpret silence as successful execution.
- Inspect Terraform plans together before the user applies them. Explain creations, changes, replacements, and deletions. Do not use automatic approval as the default workflow.
- Adjust this specification as practical choices change. Explain the reason for a change instead of treating the first draft as immutable.
- Keep durable progress notes in this document, recording only user-reported or otherwise verified outcomes. Do not mark an entire phase complete because its files exist.
- Stop after the requested batch. Do not start later phases, GitHub Actions, or staging automatically. Do not commit or push without an explicit request.

The assistant's role is to teach, propose, review, and troubleshoot. The user's role is to operate the terminal, supervise files, inspect plans, and perform browser actions.

## Starting point

The user reports the following setup is complete:

- Personal Google Cloud trial active, initially USD 300 for 90 days. Check remaining credit and expiration before provisioning; these values are not permanent.
- Project ID `wencho8-chatbot-prod`, display name `agent-chatbot-prod`, linked to the trial billing account.
- Monthly USD 50 alert-only budget, scoped to the project, with actual-spend thresholds at 50%, 90%, and 100%. Promotional credits are excluded from the budget calculation so they do not hide consumption. This is not a hard spending cutoff.
- Terraform 1.17.0 installed manually for macOS ARM64. Its executable currently uses `~/.local/bin`; verify availability in a fresh shell and guide any persistent PATH adjustment separately.
- Personal gcloud login stored separately using `CLOUDSDK_CONFIG="$HOME/.config/gcloud-chatbot"`, with the personal project selected.
- The normal work gcloud account/configuration must remain untouched. Do not add this personal configuration override globally to `.zshrc`.

CLI login is not automatically the same as Terraform credentials. Personal Application Default Credentials still need to be established and explicitly selected for Terraform without replacing work credentials.

## Initial architecture and sizing

The diagram includes the planned frontend integration, implemented separately in iteration 05. Iteration 04 ends at the deployed backend and database.

```text
Browser
  -> Firebase Hosting: compiled React assets
     -> /v1/** rewrite -> Cloud Run: FastAPI + LangGraph
                           -> Cloud SQL PostgreSQL through a connector
                           -> Secret Manager
                           -> OpenAI Responses API

Terraform -> infrastructure and remote state in Cloud Storage
Docker / deployment CLIs -> build and publish application artifacts
Cloud Logging / Monitoring -> inspect runtime behavior and resource usage
```

| Area | Initial decision |
| --- | --- |
| Environment | Production only; staging is a later iteration. |
| Region | `us-central1` (Iowa) for regional backend/database resources; keep related resources together. Firebase Hosting serves assets through its CDN. |
| Cloud Run | One app container, 1 vCPU, 512 MiB RAM initially, one Uvicorn worker, request-based billing, minimum zero and maximum one instance. Validate memory during real startup and use. |
| Application admission | Preserve the current default of four active turns per process; expected personal use is around two concurrent users. |
| Cloud Run request concurrency | Eight concurrent requests per instance, separate from the application's four active-turn limit. Cloud Run request timeout is 60 seconds. |
| Cloud SQL | PostgreSQL 17, Enterprise edition, `db-g1-small`, approximately 1.7 GiB RAM and shared CPU, 10 GiB SSD, one zone, no read replicas. |
| Database connection | Public IP through a Cloud SQL connector/proxy, encrypted and authorized. No unrestricted authorized network, public port exposure workaround, VPC, VPN, or NAT gateway. |
| Conversation coordination | Retain PostgreSQL advisory locks on dedicated connections. Do not add Valkey in this iteration. |
| Rate limits | By explicit user decision, retain bounded process-local chat/auth limits for this personal trial with one worker and maximum one instance. Counters reset on restart and are independent during revision overlap; strict shared enforcement is deferred. |
| Frontend (iteration 05) | Firebase Hosting with its supplied HTTPS domain; no custom domain and no Firebase Authentication. Not deployed in iteration 04. |
| Secrets | Secret Manager; Terraform manages secret containers/access, while the user loads values separately. |
| Observability | Google Cloud Logging and Monitoring; explicitly inspect SQL and Cloud Run memory. |

`db-g1-small` is chosen over the smaller `db-f1-micro` to provide more memory headroom without dedicated-core pricing. Shared-core instances do not have a Cloud SQL SLA. The environment name production does not imply an enterprise availability commitment.

Cloud Run minimum zero and request-based billing are independent choices. Minimum zero allows scale-to-zero; it can introduce cold-start latency. Model waiting time remains part of the active request's billable duration. Cloud SQL continues consuming resources while running, even when the chatbot is unused.

Maximum one instance is a scaling setting, not a complete coordination mechanism or guaranteed absolute spending cap. Deployments can overlap revisions. Keep PostgreSQL conversation locks shared and correct; accept that the deferred shared rate limiter leaves independent/resettable counters during restarts and revision overlap.

## Tool boundaries

| Tool | Responsibility |
| --- | --- |
| Terraform | APIs, state bucket, IAM/service accounts, Artifact Registry repository, Cloud SQL resources, Secret Manager containers/access, and Cloud Run service/job configuration. Firebase infrastructure belongs to iteration 05. |
| gcloud | Personal authentication and ADC setup, Docker registry authentication, loading secret versions, invoking migration jobs, and checking cloud resources/logs. |
| Docker and local build tools | Build the deployable backend image. Images built on the ARM Mac must include the platform required by Cloud Run. |
| Browser | Interactive account authorization, console inspection, cost/memory review, and testing the public application. |

Do not manually recreate Terraform-managed infrastructure in the console as a shortcut. If an operation must happen outside Terraform, explain why and record the ownership boundary. Do not enable unrelated Firebase services or analytics by default.

## Phases and checkpoints

Every phase below is divided into smaller guided batches when implemented. The table is a roadmap, not a command sequence to run all at once.

| Phase | Tools | Work and checkpoint |
| --- | --- | --- |
| 1. Local access | Terminal, gcloud, browser | Confirm Terraform PATH, personal gcloud directory/account/project, and separate personal ADC. Explicitly select the personal credential file for Terraform. Check that work configuration is unchanged. No billable app resources. |
| 2. Cost and file layout | Browser, documentation, supervised files | Refresh prices for the chosen region, explain cheaper/more powerful alternatives, agree on infrastructure folders and variables, and record the initial estimate. |
| 3. State bootstrap | Terraform | Create a private regional Cloud Storage state bucket using initial local state, then migrate that state to the GCS backend. Enable versioning, uniform access, and public access prevention. Verify remote state and locking. Small storage costs begin here. |
| 4. APIs and identities | Terraform | Enable required APIs and create narrowly scoped runtime/deployment/migration identities as needed. Explain deploy-time versus runtime permissions. Review the plan and inspect resulting identities. |
| 5. Registry and secret containers | Terraform, gcloud | Create Artifact Registry and Secret Manager resources. The user loads secret values through a procedure that avoids shell history and logs. Confirm access without displaying values. Storage/version-operation costs can begin. |
| 6. Cloud SQL | Terraform, browser | Review the SQL plan and ongoing cost before creation. Create the instance/database and required database identities. Verify region, version, tier, storage, public-IP restrictions, and connection policy. SQL compute/storage billing begins here. |
| 7. Cloud-ready backend | Supervised files, user-run local checks | Add connector configuration, bound SQL pools, preserve dedicated lock connections, document accepted process-local rate-limit limitations, validate production settings, and check focused behavior locally. No extra test containers or paid model calls. |
| 8. Backend image and migrations | Docker, gcloud, Terraform | Build/push an immutable image, configure a one-off Cloud Run migration job, and have the user execute it. Confirm the schema before serving traffic; do not run migrations in each API startup. Compute/image-storage costs apply. |
| 9. Backend service | Terraform, gcloud | Deploy the actual image with secrets, health checks, selected concurrency/timeouts, request-based billing, and scaling settings. Validate startup and readiness without calling the paid model. |

The user completed phases 1–9. Hosting, browser acceptance, and the remaining operational review are carried forward to iteration 05. The backend currently uses the planned origin `https://wencho8-chatbot-prod.web.app`; this does not publish that site.

## Important implementation decisions to explain during the relevant batch

- **Terraform layout:** start with a small bootstrap root and an environment root under an infrastructure directory. Do not build a large reusable module framework before it is useful. Keep environment inputs separate so staging can be added later.
- **State and secrets:** ignore local state, plans, credential files, and real secret files in Git. State can contain sensitive data; access must be restricted. Never pass the OpenAI key into Terraform secret-version resources. Choose database authentication deliberately; prefer IAM database authentication when compatible with the selected async connector, and explain database grants separately from connector/IAM access. Any alternative must avoid placing password values in state.
- **Connector:** select the concrete async-compatible Python connector or Cloud Run proxy path before changing database initialization. Preserve async SQLAlchemy/asyncpg behavior, bounded connections, and connector cleanup. A connector authenticates the connection path; it does not eliminate database login/grant requirements.
- **Rate limiting and client IP:** retain existing bounded in-memory per-user chat and auth username/IP limits by explicit user decision; shared enforcement is deferred beyond this personal trial. Validate the forwarding behavior of Hosting/Cloud Run before trusting proxy headers; never accept arbitrary client-supplied forwarded IPs. Document the initial ingress strategy and the restart/revision-overlap limitations.
- **Public backend:** the browser uses application sessions, not Google IAM identity tokens. Explain the Cloud Run invocation policy required by the Hosting integration and possible direct backend access; auth/ownership checks must apply on every path.
- **Request lifecycle:** preserve the existing 30-second turn deadline and operation limits, with a 60-second Cloud Run timeout. Browser streaming through Hosting is verified in iteration 05.
- **Releases:** use immutable image identifiers and an explicit migration step. Separate resource ownership from publishing image/Hosting releases. Avoid image drift between Terraform and ad hoc deployment commands.
- **Data:** start the cloud database empty and create real accounts through registration. Do not upload local test users, history, or development passwords.
- **Scope:** no frontend deployment, staging, CI/CD, RAG, concrete tools, Valkey, load balancer, custom domain, advanced tracing stack, or backup/restore project. Explain any unavoidable platform defaults and associated cost rather than silently expanding scope.

## Deferred operational review

SQL/Cloud Run RAM inspection, cloud application logs under real chat traffic, costs, manual release/rollback, and intentional teardown guidance remain pending in iteration 05. Closing the backend deployment does not imply those checks were performed. Preserve the requirement to distinguish SQL active memory from reclaimable cache and to review Cloud Run memory separately.

## Completion criteria

- The user has operated the deployment in small reviewed batches and understands which parts are Terraform, CLI publication, or browser inspection.
- Personal CLI/ADC selection is documented and work credentials/configuration remain unchanged.
- Terraform state is remote, private, versioned, and locked; reviewed plans contain only the intended resources.
- The chosen SQL instance and Cloud Run settings match the reviewed configuration. Secrets and database access are restricted; development identity is disabled.
- Shared conversation locks, existing bounded process-local rate limits with documented limitations, migrations, bounded SQL connections, and production auth settings are in place.
- The user successfully executes the cloud migration job and verifies the resulting schema.
- The deployed backend returns HTTP 200 with `alive` and `ready`; readiness verifies PostgreSQL access without calling OpenAI.

## Progress and next session

| Milestone | Status |
| --- | --- |
| Personal account/project/budget and isolated gcloud login | Reported complete by user before this iteration. |
| Sizing decisions and this specification | Defined; still adjustable during the exercise. |
| Separate personal ADC and Terraform PATH | User configured personal ADC under the isolated gcloud directory, explicitly selected its credential file, and added the Terraform executable directory to the shell PATH. |
| Terraform files, remote state, and cloud infrastructure | User applied bootstrap, migrated its state to GCS, initialized production with separate GCS state, enabled eight APIs, and created runtime/migration service accounts, initial permissions, Docker repository, OpenAI secret, and Cloud SQL instance/database/IAM users. The user loaded the secret through the console and reported a no-change SQL plan. |
| Backend Cloud SQL connection adapter | Implemented in a user-authorized code batch: explicit direct/cloud mode, native async connector with IAM and lazy refresh, bounded independent API/lock pools, shared Alembic connection setup, and local Compose isolation. The user verified real cloud access through the privilege helper, migration job, and deployed API readiness. |
| Local acceptance and image publication | User ran `make start`, all 86 backend tests passed, and readiness returned ready. The user built Linux AMD64 image `spec4-001` and pushed it to Artifact Registry with digest `sha256:fb17bb407d93120cf0eef05cd34c0e55d686ff53f00bbffd493fd8ec85543000`. |
| Migration job | User applied `chatbot-migrate` using the pinned image and migration IAM identity, then successfully ran execution `chatbot-migrate-xbqs5` and viewed the resulting tables in Cloud SQL Studio. No automatic execution provisioner is defined. |
| Passwordless SQL administrator and privilege helper | User applied the personal IAM administrator, reviewed the SQL preview, and successfully ran `scripts/bootstrap_database.py --apply` to configure grants in one transaction. See the [IAM setup guide](../doc/database-iam-setup.md). Four isolated helper tests passed. |
| Backend Cloud Run service | User applied the service and public invocation permission: two resources added, no changes or deletions. Request billing, 1 vCPU, 512 MiB, service scaling 0–1, request concurrency 8, application active turns 4, and timeout 60 seconds. User verified HTTP 200 with `alive` and `ready` at `https://chatbot-backend-dasag4h7iq-uc.a.run.app`. |
| Shared rate limits | Explicitly deferred by the user; retain the existing memory implementation and accept its limitations for this trial. |
| Frontend deployment, end-to-end acceptance, and remaining operational review | Moved to iteration 05; not started. |

The user explicitly authorized the assistant to implement this backend connection batch and run local tests, without staging/committing or executing Terraform/gcloud. This exception does not authorize cloud commands or automatically starting later batches. Record test results after verification; continue guided cloud work only with the user operating the commands.

Connection-batch verification: the assistant ran 70 isolated local tests using mocked cloud/model clients without starting services or executing Terraform/gcloud. Subsequently, the user started local Compose, ran the full backend suite (86 passed), and verified readiness. The user later verified real Cloud SQL grants, migration execution, and backend runtime database access. The browser flow remains unverified in the cloud.

Next guided work belongs to [Iteration 05 — Firebase Hosting](05-firebase-hosting.md). Iteration 06 is GitHub Actions; iteration 07 is staging. No later iteration starts automatically. Creating/updating the migration job must never execute it implicitly.

## References

- [gcloud configuration directories](https://docs.cloud.google.com/sdk/docs/configurations)
- [Terraform authentication on Google Cloud](https://docs.cloud.google.com/docs/terraform/authentication)
- [Remote Terraform state in Cloud Storage](https://docs.cloud.google.com/docs/terraform/resource-management/store-state)
- [Cloud SQL connection options](https://docs.cloud.google.com/sql/docs/postgres/connection-options)
- [Cloud SQL pricing](https://cloud.google.com/sql/pricing)
- [Cloud Run pricing](https://cloud.google.com/run/pricing)
- [Firebase Hosting with Cloud Run](https://firebase.google.com/docs/hosting/cloud-run)
- [Cloud SQL monitoring](https://docs.cloud.google.com/sql/docs/postgres/monitor-instance)
- [Understanding SQL memory usage](https://docs.cloud.google.com/sql/docs/postgres/optimize-high-memory-usage)
