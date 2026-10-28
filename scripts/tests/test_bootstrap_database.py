from contextlib import asynccontextmanager, redirect_stdout
import importlib.util
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "bootstrap_database", Path(__file__).resolve().parents[1] / "bootstrap_database.py"
)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


ARGS = SimpleNamespace(database="chatbot", admin_user="admin@example.com",
                       migrations_user="migrations@fixture.iam", runtime_user="runtime@fixture.iam")


class Connection:
    def __init__(self, *, identity=ARGS.admin_user, can_set_role=True, fail_on=None):
        self.identity, self.can_set_role, self.fail_on = identity, can_set_role, fail_on
        self.events = []

    async def fetchval(self, query, *values):
        return self.identity if query == "SELECT current_user" else self.can_set_role

    @asynccontextmanager
    async def transaction(self):
        self.events.append("BEGIN")
        try:
            yield
        except BaseException:
            self.events.append("ROLLBACK")
            raise
        else:
            self.events.append("COMMIT")

    async def execute(self, statement):
        self.events.append(statement)
        if self.fail_on and self.fail_on in statement:
            raise RuntimeError("simulated SQL failure")


class BootstrapTests(unittest.IsolatedAsyncioTestCase):
    def test_preview_does_not_connect_and_quotes_sql_identifiers(self):
        output = StringIO()
        with redirect_stdout(output), patch.object(bootstrap, "apply") as apply:
            bootstrap.main([
                "--instance", "fixture:us-central1:postgres", "--database", "chatbot",
                "--admin-user", ARGS.admin_user, "--migrations-user", ARGS.migrations_user,
                "--runtime-user", ARGS.runtime_user,
            ])
            apply.assert_not_called()
        self.assertIn("Preview only: no connection or changes", output.getvalue())
        self.assertEqual(bootstrap.identifier('a"; DROP SCHEMA public; --'),
                         '"a""; DROP SCHEMA public; --"')
        for invalid in ("", " padded", "line\nbreak", "x" * 64):
            with self.assertRaises(ValueError):
                bootstrap.identifier(invalid)

    async def test_unexpected_identity_or_missing_role_stops_before_grants(self):
        for connection in (Connection(identity="unexpected@example.com"), Connection(can_set_role=False)):
            with self.assertRaises(RuntimeError):
                await bootstrap.grant_permissions(connection, ARGS)
            self.assertEqual(connection.events, [])

    async def test_defaults_belong_to_migration_identity_and_runtime_gets_no_ddl(self):
        connection = Connection()
        await bootstrap.grant_permissions(connection, ARGS)
        self.assertEqual(connection.events[0], "BEGIN")
        self.assertEqual(connection.events[-1], "COMMIT")
        switch = connection.events.index(f'SET LOCAL ROLE "{ARGS.migrations_user}"')
        defaults = next(i for i, sql in enumerate(connection.events) if sql.startswith("ALTER DEFAULT PRIVILEGES"))
        self.assertLess(switch, defaults)
        self.assertTrue(any("ON ALL TABLES" in sql for sql in connection.events))
        self.assertFalse(any("cloudsqlsuperuser" in sql or "DROP " in sql for sql in connection.events))
        self.assertFalse(any(sql.startswith("GRANT USAGE, CREATE") and ARGS.runtime_user in sql
                             for sql in connection.events))

    async def test_sql_failure_rolls_back_entire_grant_transaction(self):
        connection = Connection(fail_on="ALTER DEFAULT PRIVILEGES")
        with self.assertRaisesRegex(RuntimeError, "simulated"):
            await bootstrap.grant_permissions(connection, ARGS)
        self.assertEqual(connection.events[-1], "ROLLBACK")
        self.assertNotIn("COMMIT", connection.events)


if __name__ == "__main__":
    unittest.main()
