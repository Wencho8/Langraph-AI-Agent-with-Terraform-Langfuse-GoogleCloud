"""Preview or explicitly apply SQL grants using a personal IAM administrator.

Run locally with `uv run --project backend python scripts/bootstrap_database.py`.
The default prints SQL only. --apply connects to Cloud SQL; the assistant must
never execute that mode during the guided deployment.
"""

import argparse
import asyncio
import os
from pathlib import Path
import re


def identifier(value: str) -> str:
    """Identifiers cannot be query parameters; quote them, never interpolate raw."""
    if not value or value != value.strip() or len(value.encode("utf-8")) > 63 or any(ord(c) < 32 for c in value):
        raise ValueError("SQL identifiers must be nonblank and at most 63 bytes without control characters")
    return '"' + value.replace('"', '""') + '"'


def statements(database: str, migrations_user: str, runtime_user: str) -> list[str]:
    database, migrations, runtime = map(identifier, (database, migrations_user, runtime_user))
    return [
        f"GRANT CONNECT ON DATABASE {database} TO {migrations}, {runtime}",
        f"GRANT USAGE, CREATE ON SCHEMA public TO {migrations}",
        f"GRANT USAGE ON SCHEMA public TO {runtime}",
        # Default privileges belong to the object creator, not the admin running
        # this script. SET LOCAL ROLE also resets automatically at transaction end.
        f"SET LOCAL ROLE {migrations}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {runtime}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {runtime}",
        # Permit repeat runs after migrations, without dropping existing objects.
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {runtime}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {runtime}",
    ]


async def grant_permissions(connection, args):
    actual_user = await connection.fetchval("SELECT current_user")
    if actual_user != args.admin_user:
        raise RuntimeError("Connected SQL identity does not match --admin-user; no grants applied")
    can_set_role = await connection.fetchval(
        "SELECT pg_has_role(current_user, $1, 'SET')", args.migrations_user
    )
    if not can_set_role:
        raise RuntimeError("Admin cannot SET ROLE to the migration user; review sql_admin.tf before continuing")
    async with connection.transaction():
        await connection.execute("SET LOCAL lock_timeout = '5s'")
        await connection.execute("SET LOCAL statement_timeout = '10s'")
        for statement in statements(args.database, args.migrations_user, args.runtime_user):
            await connection.execute(statement)


async def apply(args):
    credential_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not credential_file or not Path(credential_file).is_file():
        raise RuntimeError("Explicitly select your personal ADC file with GOOGLE_APPLICATION_CREDENTIALS first")

    # Import only in --apply mode: preview does not need Google credentials or SDK calls.
    from google.cloud.sql.connector import IPTypes, create_async_connector

    connector = await create_async_connector(
        ip_type=IPTypes.PUBLIC, enable_iam_auth=True, refresh_strategy="LAZY", timeout=10,
    )
    connection = None
    try:
        connection = await connector.connect_async(
            args.instance, "asyncpg", user=args.admin_user, db=args.database, timeout=10,
        )
        await grant_permissions(connection, args)
    finally:
        try:
            if connection is not None:
                await connection.close(timeout=10)
        finally:
            await connector.close_async()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True, help="project:region:instance")
    parser.add_argument("--database", required=True)
    parser.add_argument("--admin-user", required=True, help="Personal Google email registered in PostgreSQL")
    parser.add_argument("--migrations-user", required=True, help="PostgreSQL IAM username ending in .iam")
    parser.add_argument("--runtime-user", required=True, help="PostgreSQL IAM username ending in .iam")
    parser.add_argument("--apply", action="store_true", help="Connect and apply grants; default is preview only")
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r"[^:\s]+:[^:\s]+:[^:\s]+", args.instance):
            raise ValueError("--instance must be project:region:instance")
        for value in (args.database, args.admin_user, args.migrations_user, args.runtime_user):
            identifier(value)
        if len({args.admin_user, args.migrations_user, args.runtime_user}) != 3:
            raise ValueError("Admin, migrations and runtime must be distinct users")
        if not all(value.endswith(".iam") for value in (args.migrations_user, args.runtime_user)):
            raise ValueError("Application IAM usernames must omit the .gserviceaccount.com suffix")
    except ValueError as exc:
        parser.error(str(exc))

    print(f"Target: {args.instance}, database: {args.database}, IAM admin: {args.admin_user}")
    if not args.apply:
        print("Preview only: no connection or changes. SQL runs in one transaction:")
        for statement in statements(args.database, args.migrations_user, args.runtime_user):
            print(statement + ";")
        print("Use --apply only after reviewing the target and statements.")
        return
    asyncio.run(apply(args))
    print("SQL privileges configured. No migrations were executed.")


if __name__ == "__main__":
    main()
