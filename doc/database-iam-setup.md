# PostgreSQL privilege setup with IAM

Status: configuration and helper prepared. The user must apply the reviewed Terraform plan and explicitly run the SQL setup. No password is required, and the migration job must not run before this setup succeeds.

## Identity boundaries

- `sql_admin_email` is the personal Google user registered as `CLOUD_IAM_USER`. Its `cloudsqlsuperuser` database role is administrative and is not given to the application accounts. It is also a member of the migration database role so it can use `SET LOCAL ROLE` to configure the defaults for that role's future objects.
- `chatbot-migrations` authenticates as its own IAM service account and receives usage/create on the application's `public` schema.
- `chatbot-runtime` authenticates as a different IAM service account and receives schema usage and table data privileges, not schema creation or administrative role membership.
- Cloud IAM `cloudsql.client` and `cloudsql.instanceUser` authorize the connection/login path. PostgreSQL roles and SQL grants are separate permissions.

The helper connects through the Cloud SQL Python Connector with automatic IAM authentication and public IP. It never resets the built-in `postgres` password, reads the OpenAI key, or launches Alembic. It runs locally outside the application image, so this setup does not require another image build.

## 1. Select personal credentials in the current terminal

From the repository root:

```sh
export CLOUDSDK_CONFIG="$HOME/.config/gcloud-chatbot"
export CLOUDSDK_PYTHON="/opt/homebrew/bin/python3.13"
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.config/gcloud-chatbot/application_default_credentials.json"
```

These are session-local selections, not global shell configuration. The helper's apply mode requires an explicitly selected credential file; do not rely on an ambient work ADC fallback.

## 2. Review and apply the administrator configuration

```sh
terraform -chdir=infra/environments/production fmt
terraform -chdir=infra/environments/production validate
terraform -chdir=infra/environments/production plan -out=sql-admin.tfplan
```

Expected: three additions (one IAM SQL user and two project IAM memberships), no changes/deletions to existing resources, and a new `sql_admin_user` output. Review the personal email and the admin-only database roles before applying. If the plan differs, stop and inspect it.

After the user approves that plan:

```sh
terraform -chdir=infra/environments/production apply sql-admin.tfplan
```

## 3. Preview the SQL grants

The default mode prints SQL without connecting to Google Cloud. `uv run` may initialize the local Python environment from the backend dependency lockfile.

```sh
uv run --project backend python scripts/bootstrap_database.py \
  --instance wencho8-chatbot-prod:us-central1:chatbot-postgres \
  --database chatbot \
  --admin-user wenchoavalos8@gmail.com \
  --migrations-user chatbot-migrations@wencho8-chatbot-prod.iam \
  --runtime-user chatbot-runtime@wencho8-chatbot-prod.iam
```

The script grants connection/schema access, switches the current transaction's role to the migration identity, and configures default table/sequence data access for runtime. PostgreSQL defaults belong to the role that creates the objects: changing only the administrator's defaults would not cover tables created by Alembic. It also grants access to existing migration-owned tables/sequences, so it can be repeated after migrations. All statements run in one transaction in apply mode; SQL errors roll the transaction back. No tables are created or dropped.

## 4. Apply the reviewed SQL grants

Only after administrator Terraform setup succeeds and the preview is reviewed:

```sh
uv run --project backend python scripts/bootstrap_database.py \
  --instance wencho8-chatbot-prod:us-central1:chatbot-postgres \
  --database chatbot \
  --admin-user wenchoavalos8@gmail.com \
  --migrations-user chatbot-migrations@wencho8-chatbot-prod.iam \
  --runtime-user chatbot-runtime@wencho8-chatbot-prod.iam \
  --apply
```

Success ends with `SQL privileges configured. No migrations were executed.` The helper checks the authenticated SQL username and the ability to switch to the migration role before applying grants. If it fails, stop and share the error without credential contents; do not broaden application roles or weaken connector enforcement as a workaround.

After success, return to the guided flow to execute `chatbot-migrate` explicitly and verify its logs, schema, and runtime access. Creating the Cloud Run Job or granting permissions alone does not execute migrations.

## References

- [Managing Cloud SQL IAM users and database role assignments](https://docs.cloud.google.com/sql/docs/postgres/add-manage-iam-users)
- [PostgreSQL SET ROLE](https://www.postgresql.org/docs/17/sql-set-role.html)
- [PostgreSQL default privileges](https://www.postgresql.org/docs/17/sql-alterdefaultprivileges.html)
