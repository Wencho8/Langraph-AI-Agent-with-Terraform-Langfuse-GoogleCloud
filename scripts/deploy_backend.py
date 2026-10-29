"""Migrate, deploy without traffic, promote, and restore traffic on smoke failure.

Cloud mutations happen only when this CLI is explicitly executed by the operator
or the main-branch deployment job. Schema downgrades are never automatic.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from check_deployment import ready, retry


def gcloud(args, *command):
    result = subprocess.run(
        ["gcloud", "run", *command, "--project=" + args.project,
         "--region=" + args.region, "--quiet", "--format=json"],
        check=True, capture_output=True, text=True, timeout=600,
    )
    return json.loads(result.stdout) if result.stdout.strip() else {}


def serving_revision(service):
    traffic = [entry for entry in service["status"].get("traffic", []) if entry.get("percent", 0) > 0]
    if len(traffic) != 1 or traffic[0]["percent"] != 100 or not traffic[0].get("revisionName"):
        raise RuntimeError("Expected one explicitly resolved revision serving 100% of traffic")
    return traffic[0]["revisionName"]


def summary(message):
    print(message, flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as destination:
            destination.write(message + "\n\n")


def deploy(args):
    previous = gcloud(args, "services", "describe", args.service)
    old_revision = serving_revision(previous)
    url = previous["status"]["url"]
    candidate = args.service + "-" + args.suffix
    if candidate == old_revision:
        raise RuntimeError("Candidate must be a new revision")
    summary(f"Backend image: `{args.image}`. Previous revision: `{old_revision}`.")

    # Migration failure stops before changing the service image or live traffic.
    gcloud(args, "jobs", "update", args.job, "--image=" + args.image)
    gcloud(args, "jobs", "execute", args.job, "--wait")
    summary("Migration job completed successfully (Alembic is a no-op if already current).")

    gcloud(args, "services", "update", args.service, "--image=" + args.image,
           "--revision-suffix=" + args.suffix, "--no-traffic")
    current = gcloud(args, "services", "describe", args.service)
    actual_serving = serving_revision(current)
    if actual_serving != old_revision:
        raise RuntimeError(f"Traffic changed during deployment: expected {old_revision}, got {actual_serving}; "
                           "refusing to promote over another release")
    # With --no-traffic a scale-to-zero revision may be Retired and the service's
    # latestReadyRevisionName may still refer to the serving revision. Check the
    # revision we created; activation and readiness are verified after promotion.
    actual_created = current["status"].get("latestCreatedRevisionName")
    if actual_created != candidate:
        raise RuntimeError(f"Latest created revision changed: expected {candidate}, got {actual_created}; "
                           "refusing to promote over another release")

    try:
        # Pin an explicit revision so an overlapping LATEST update is not promoted.
        gcloud(args, "services", "update-traffic", args.service, "--to-revisions=" + candidate + "=100")
        if serving_revision(gcloud(args, "services", "describe", args.service)) != candidate:
            raise RuntimeError("Candidate did not receive all traffic")
        retry(lambda: ready(url))
    except Exception:
        try:
            current = gcloud(args, "services", "describe", args.service)
            if serving_revision(current) == candidate:
                gcloud(args, "services", "update-traffic", args.service,
                       "--to-revisions=" + old_revision + "=100")
                if serving_revision(gcloud(args, "services", "describe", args.service)) != old_revision:
                    raise RuntimeError("Previous revision was not restored")
                retry(lambda: ready(url))
                summary(f"Smoke/promotion failed; traffic restored to `{old_revision}`. Database migrations were NOT reverted.")
            else:
                summary("Rollback skipped: this candidate does not own current traffic. Inspect the service manually.")
        except Exception:
            summary("Automatic traffic rollback could not be verified. Manual inspection is required; migrations were NOT reverted.")
            raise
        raise
    summary(f"Backend deployed and ready: `{candidate}` at {url}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--service", default="chatbot-backend")
    parser.add_argument("--job", default="chatbot-migrate")
    parser.add_argument("--image", required=True)
    parser.add_argument("--suffix", required=True)
    args = parser.parse_args()
    expected_image = re.escape(f"{args.region}-docker.pkg.dev/{args.project}/chatbot/backend")
    if not re.fullmatch(expected_image + r"@sha256:[0-9a-f]{64}", args.image):
        parser.error("Use an immutable backend digest from this project's chatbot repository")
    if not re.fullmatch(r"[a-z][a-z0-9-]*[a-z0-9]", args.suffix) or len(args.service + "-" + args.suffix) > 63:
        parser.error("Invalid or overlong revision suffix")
    try:
        deploy(args)
    except subprocess.CalledProcessError as error:
        # gcloud may print useful diagnostics, but never dump credential files or env.
        if error.stderr:
            print(error.stderr, flush=True)
        raise SystemExit("Backend release failed; frontend publication will not run.") from error


if __name__ == "__main__":
    main()
