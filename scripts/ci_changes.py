"""Select release components from a push; no cloud credentials or mutations."""
import argparse
import os
from pathlib import Path
import subprocess


def components(paths):
    backend = frontend = False
    for path in paths:
        if path.startswith("backend/"):
            backend = True
        if path.startswith("frontend/") or path == "firebase.json":
            frontend = True
        if path.startswith(".github/") or path in {
            "scripts/ci_changes.py", "scripts/deploy_backend.py", "scripts/check_deployment.py",
        }:
            backend = frontend = True
    return {"backend": backend, "frontend": frontend}


def changed_paths(before, after):
    if not before or set(before) == {"0"}:
        command = ["git", "ls-tree", "-r", "--name-only", "-z", after]
    else:
        # A force-pushed 'before' may not be available. Release both rather than
        # silently skipping an application update we cannot classify reliably.
        present = subprocess.run(["git", "cat-file", "-e", before + "^{commit}"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if present.returncode:
            return ["backend/", "frontend/"]
        command = ["git", "diff", "--name-only", "--no-renames", "-z", before, after, "--"]
    return subprocess.check_output(command).decode().rstrip("\0").split("\0")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", default="")
    parser.add_argument("--after", default="HEAD")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    selected = {"backend": True, "frontend": True} if args.force else components(changed_paths(args.before, args.after))
    output = "".join(f"{name}={str(enabled).lower()}\n" for name, enabled in selected.items())
    print(output, end="")
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as destination:
            destination.write(output)


if __name__ == "__main__":
    main()
