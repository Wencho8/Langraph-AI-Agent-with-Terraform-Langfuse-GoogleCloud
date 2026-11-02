"""Bounded public smoke checks; never create users or call the model."""
import argparse
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request(url, *, method="GET", headers=None):
    try:
        with urlopen(Request(url, method=method, headers={"Cache-Control": "no-cache", **(headers or {})}), timeout=15) as response:
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


def frontend(url, index, api_url):
    status, headers, body = request(url.rstrip("/") + "/")
    assert status == 200 and "text/html" in headers.get("Content-Type", ""), "Frontend HTML unavailable"
    # Match this run's Vite bundle, not merely any old HTML returning HTTP 200.
    assets = re.findall(r'(?:src|href)="(/assets/[^"?#]+)"', Path(index).read_text())
    assert assets, "Built index.html contains no Vite assets"
    for asset in assets:
        assert asset in body, "Hosting has not served this build's index.html"
        asset_status, asset_headers, _ = request(url.rstrip("/") + asset)
        assert asset_status == 200 and "text/html" not in asset_headers.get("Content-Type", ""), "Missing frontend asset"
    status, headers, body = request(api_url.rstrip("/") + "/v1/auth/session", headers={"Origin": url.rstrip("/")})
    assert status == 401 and json.loads(body).get("code") == "unauthenticated", "Direct API did not reach authentication"
    assert "no-store" in headers.get("Cache-Control", ""), "Private response is cacheable"
    assert headers.get("Access-Control-Allow-Origin") == url.rstrip("/"), "API CORS origin mismatch"
    status, headers, _ = request(api_url.rstrip("/") + "/v1/chat/messages", method="OPTIONS", headers={
        "Origin": url.rstrip("/"), "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert status == 200 and headers.get("Access-Control-Allow-Origin") == url.rstrip("/"), "API CORS preflight failed"
    assert "authorization" in headers.get("Access-Control-Allow-Headers", "").lower(), "Bearer header not allowed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-url")
    parser.add_argument("--frontend-url")
    parser.add_argument("--api-url", help="Public API origin used by the published frontend")
    parser.add_argument("--index", default="frontend/dist/index.html")
    args = parser.parse_args()
    if bool(args.backend_url) == bool(args.frontend_url):
        parser.error("Select exactly one of --backend-url or --frontend-url")
    if args.frontend_url and not args.api_url:
        parser.error("--frontend-url requires --api-url")
    retry(lambda: ready(args.backend_url) if args.backend_url else frontend(args.frontend_url, args.index, args.api_url))
    print("Deployment smoke check passed; no model calls were made.")


if __name__ == "__main__":
    main()
