"""Bounded public smoke checks; never create users or call the model."""
import argparse
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request(url):
    try:
        with urlopen(Request(url, headers={"Cache-Control": "no-cache"}), timeout=15) as response:
            return response.status, response.headers, response.read(1_000_000).decode()
    except HTTPError as response:
        return response.code, response.headers, response.read(1_000_000).decode()


def retry(check, attempts=4):
    for attempt in range(attempts):
        try:
            check()
            return
        except (AssertionError, ValueError, OSError, URLError) as error:
            if attempt == attempts - 1:
                raise RuntimeError(f"Deployment smoke check failed: {error}") from error
            time.sleep(3)


def ready(url):
    status, _, body = request(url.rstrip("/") + "/health/ready")
    assert status == 200 and json.loads(body).get("status") == "ready", "Backend is not ready"


def frontend(url, index):
    status, headers, body = request(url.rstrip("/") + "/")
    assert status == 200 and "text/html" in headers.get("Content-Type", ""), "Frontend HTML unavailable"
    # Match this run's Vite bundle, not merely any old HTML returning HTTP 200.
    assets = re.findall(r'(?:src|href)="(/assets/[^"?#]+)"', Path(index).read_text())
    assert assets, "Built index.html contains no Vite assets"
    for asset in assets:
        assert asset in body, "Hosting has not served this build's index.html"
        asset_status, asset_headers, _ = request(url.rstrip("/") + asset)
        assert asset_status == 200 and "text/html" not in asset_headers.get("Content-Type", ""), "Missing frontend asset"
    status, headers, body = request(url.rstrip("/") + "/v1/auth/session")
    assert status == 401 and json.loads(body).get("code") == "unauthenticated", "API rewrite did not reach authentication"
    assert "no-store" in headers.get("Cache-Control", ""), "Private response is cacheable"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-url")
    parser.add_argument("--frontend-url")
    parser.add_argument("--index", default="frontend/dist/index.html")
    args = parser.parse_args()
    if bool(args.backend_url) == bool(args.frontend_url):
        parser.error("Select exactly one of --backend-url or --frontend-url")
    retry(lambda: ready(args.backend_url) if args.backend_url else frontend(args.frontend_url, args.index))
    print("Deployment smoke check passed; no model calls were made.")


if __name__ == "__main__":
    main()
