"""Release failure scenarios with fake gcloud/HTTP; never touch Google Cloud."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_deployment as smoke
import ci_changes
import deploy_backend as release


ARGS = SimpleNamespace(project="fixture-project", region="us-central1", service="chatbot-backend",
                       job="chatbot-migrate", suffix="gh-new", image="fixture@sha256:" + "a" * 64)
OLD = "chatbot-backend-old"
NEW = "chatbot-backend-gh-new"


class FakeCloud:
    def __init__(self, fail=None):
        self.commands, self.fail = [], fail
        self.serving, self.latest = OLD, OLD

    def __call__(self, args, *command):
        self.commands.append(command)
        if command[:2] == ("jobs", "execute") and self.fail == "migration":
            raise subprocess.CalledProcessError(1, "fake migration")
        if command[:2] == ("services", "update"):
            if self.fail == "startup":
                raise subprocess.CalledProcessError(1, "fake startup")
            self.latest = NEW
            if self.fail == "overlap":
                self.latest = "chatbot-backend-another-release"
        if command[:2] == ("services", "update-traffic"):
            revision = command[-1].removeprefix("--to-revisions=").removesuffix("=100")
            if self.fail == "rollback" and revision == OLD:
                raise subprocess.CalledProcessError(1, "fake rollback")
            self.serving = revision
        return {"status": {"url": "https://backend.invalid", "latestCreatedRevisionName": self.latest,
                           "latestReadyRevisionName": self.serving,
                           "traffic": [{"revisionName": self.serving, "percent": 100}]}}


class ReleaseTests(unittest.TestCase):
    def run_release(self, cloud, ready=None):
        with redirect_stdout(StringIO()), patch.object(release, "gcloud", cloud), \
                patch.object(release, "ready", ready or (lambda url: None)), \
                patch.object(release, "retry", side_effect=lambda check: check()), \
                patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": ""}):
            release.deploy(ARGS)

    def test_migration_failure_keeps_live_service_untouched(self):
        cloud = FakeCloud("migration")
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_release(cloud)
        self.assertEqual(cloud.serving, OLD)
        self.assertFalse(any(cmd[:1] == ("services",) and cmd[1] != "describe" for cmd in cloud.commands))

    def test_failed_startup_never_receives_traffic(self):
        cloud = FakeCloud("startup")
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_release(cloud)
        self.assertEqual(cloud.serving, OLD)
        self.assertFalse(any(cmd[:2] == ("services", "update-traffic") for cmd in cloud.commands))

    def test_success_waits_for_migrations_before_creating_and_promoting_revision(self):
        cloud = FakeCloud()
        self.run_release(cloud)
        operations = [cmd[:2] for cmd in cloud.commands]
        self.assertLess(operations.index(("jobs", "execute")), operations.index(("services", "update")))
        self.assertLess(operations.index(("services", "update")), operations.index(("services", "update-traffic")))
        self.assertIn("--no-traffic", next(cmd for cmd in cloud.commands if cmd[:2] == ("services", "update")))
        self.assertEqual(cloud.serving, NEW)

    def test_failed_smoke_restores_old_revision_but_release_still_fails(self):
        cloud = FakeCloud()
        with patch.object(release, "ready", side_effect=[RuntimeError("not ready"), None]) as check:
            with self.assertRaisesRegex(RuntimeError, "not ready"):
                self.run_release(cloud, check)
        self.assertEqual(cloud.serving, OLD)
        self.assertFalse(any("downgrade" in str(cmd) for cmd in cloud.commands))

    def test_retired_no_traffic_candidate_does_not_need_to_be_latest_ready(self):
        cloud = FakeCloud()
        snapshots = []

        def observed(args, *command):
            result = cloud(args, *command)
            if command[:2] == ("services", "describe") and cloud.latest == NEW and cloud.serving == OLD:
                result["status"]["conditions"] = [
                    {"type": "ConfigurationsReady", "status": "True", "reason": "Retired"},
                ]
                snapshots.append(result)
            return result

        self.run_release(observed)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["status"]["latestCreatedRevisionName"], NEW)
        self.assertEqual(snapshots[0]["status"]["latestReadyRevisionName"], OLD)
        self.assertEqual(cloud.serving, NEW)

    def test_changed_traffic_before_promotion_reports_the_actual_conflict(self):
        cloud = FakeCloud()

        def changed(args, *command):
            result = cloud(args, *command)
            if command[:2] == ("services", "update"):
                cloud.serving = "chatbot-backend-another-release"
            return result

        with self.assertRaisesRegex(RuntimeError, "Traffic changed during deployment"):
            self.run_release(changed)
        self.assertFalse(any(cmd[:2] == ("services", "update-traffic") for cmd in cloud.commands))

    def test_newer_candidate_detected_before_promotion_is_not_overwritten(self):
        cloud = FakeCloud("overlap")
        with self.assertRaisesRegex(RuntimeError, "another release"):
            self.run_release(cloud)
        self.assertFalse(any(cmd[:2] == ("services", "update-traffic") for cmd in cloud.commands))

    def test_newer_traffic_is_not_rewound_on_smoke_failure(self):
        cloud = FakeCloud()

        def changed_during_check(url):
            cloud.serving = "chatbot-backend-newer-release"
            raise RuntimeError("failed smoke")

        with self.assertRaisesRegex(RuntimeError, "failed smoke"):
            self.run_release(cloud, changed_during_check)
        self.assertEqual(cloud.serving, "chatbot-backend-newer-release")

    def test_rollback_failure_is_a_failure_not_a_success(self):
        cloud = FakeCloud("rollback")
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_release(cloud, lambda url: (_ for _ in ()).throw(RuntimeError("not ready")))

    def test_existing_split_traffic_requires_manual_review(self):
        with self.assertRaises(RuntimeError):
            release.serving_revision({"status": {"traffic": [
                {"revisionName": OLD, "percent": 50}, {"revisionName": NEW, "percent": 50},
            ]}})


class SelectionTests(unittest.TestCase):
    def test_docs_and_infrastructure_do_not_release_apps(self):
        self.assertEqual(ci_changes.components(["README.md", "specs/06.md", "infra/production/main.tf"]),
                         {"backend": False, "frontend": False})

    def test_components_and_workflow_changes(self):
        for paths, expected in [
            (["backend/migrations/versions/new.py"], {"backend": True, "frontend": False}),
            (["frontend/src/App.tsx", "firebase.json"], {"backend": False, "frontend": True}),
            ([".github/workflows/ci-deploy.yml"], {"backend": True, "frontend": True}),
        ]:
            self.assertEqual(ci_changes.components(paths), expected)

    def test_unavailable_before_commit_releases_both_components(self):
        with patch.object(ci_changes.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
            self.assertEqual(ci_changes.components(ci_changes.changed_paths("missing", "HEAD")),
                             {"backend": True, "frontend": True})


class SmokeTests(unittest.TestCase):
    def test_frontend_checks_the_build_assets_rewrite_and_private_cache_policy(self):
        with TemporaryDirectory() as directory:
            index = Path(directory) / "index.html"
            index.write_text('<script src="/assets/current.js"></script>')
            responses = [
                (200, {"Content-Type": "text/html"}, index.read_text()),
                (200, {"Content-Type": "text/javascript"}, "bundle"),
                (401, {"Cache-Control": "no-store"}, '{"code":"unauthenticated"}'),
            ]
            with patch.object(smoke, "request", side_effect=responses) as request:
                smoke.frontend("https://frontend.invalid", index)
            self.assertEqual(request.call_args.args[0], "https://frontend.invalid/v1/auth/session")

    def test_http_200_for_old_build_is_not_a_success(self):
        with TemporaryDirectory() as directory:
            index = Path(directory) / "index.html"
            index.write_text('<script src="/assets/current.js"></script>')
            with patch.object(smoke, "request", return_value=(200, {"Content-Type": "text/html"}, "old build")):
                with self.assertRaisesRegex(AssertionError, "this build"):
                    smoke.frontend("https://frontend.invalid", index)

    def test_spa_html_instead_of_missing_javascript_is_not_a_success(self):
        with TemporaryDirectory() as directory:
            index = Path(directory) / "index.html"
            index.write_text('<script src="/assets/current.js"></script>')
            with patch.object(smoke, "request", side_effect=[
                (200, {"Content-Type": "text/html"}, index.read_text()),
                (200, {"Content-Type": "text/html"}, index.read_text()),
            ]):
                with self.assertRaisesRegex(AssertionError, "Missing frontend asset"):
                    smoke.frontend("https://frontend.invalid", index)

    def test_smoke_retries_are_bounded(self):
        from unittest.mock import Mock
        check = Mock(side_effect=OSError("unavailable"))
        with patch.object(smoke.time, "sleep") as sleep:
            with self.assertRaises(RuntimeError):
                smoke.retry(check, attempts=3)
        self.assertEqual(check.call_count, 3)
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
