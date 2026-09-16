#!/usr/bin/env python3
"""Measure an initial and exact repeated durable planning preview."""

from __future__ import annotations

import argparse
import json
import sys
from time import monotonic, sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ACTIVE_STATUSES = {"queued", "running", "cancelling"}


def _request_json(
    base_url: str,
    token: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=30) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise ValueError("the planning API returned a non-object response")
    return value


def _run_preview(
    base_url: str,
    token: str,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> tuple[dict[str, Any], float]:
    started_at = monotonic()
    job = _request_json(
        base_url,
        token,
        "/api/v1/planning/preview/jobs",
        method="POST",
        payload={},
    )
    job_id = str(job["job_id"])
    while job.get("status") in ACTIVE_STATUSES:
        if monotonic() - started_at >= timeout_seconds:
            raise TimeoutError(f"preview job {job_id} exceeded {timeout_seconds:g} seconds")
        sleep(poll_interval_seconds)
        job = _request_json(
            base_url,
            token,
            f"/api/v1/planning/preview/jobs/{job_id}",
        )
    return job, monotonic() - started_at


def _summary(job: dict[str, Any], elapsed_seconds: float) -> dict[str, Any]:
    result = job.get("result")
    result = result if isinstance(result, dict) else {}
    diagnostics = result.get("diagnostics")
    return {
        "job_id": job.get("job_id"),
        "job_status": job.get("status"),
        "plan_status": result.get("status"),
        "elapsed_seconds": elapsed_seconds,
        "score": result.get("score", []),
        "model": diagnostics.get("model", {}) if isinstance(diagnostics, dict) else {},
        "solver": diagnostics.get("solver", {}) if isinstance(diagnostics, dict) else {},
        "preview": diagnostics.get("preview", {}) if isinstance(diagnostics, dict) else {},
        "checks": job.get("checks", []),
        "token": result.get("token"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark the durable planning preview on the deployment device."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--token", required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--poll-interval", type=float, default=0.1)
    args = parser.parse_args()

    first_job, first_elapsed = _run_preview(
        args.base_url,
        args.token,
        timeout_seconds=args.timeout,
        poll_interval_seconds=args.poll_interval,
    )
    repeated_job, repeated_elapsed = _run_preview(
        args.base_url,
        args.token,
        timeout_seconds=args.timeout,
        poll_interval_seconds=args.poll_interval,
    )
    first = _summary(first_job, first_elapsed)
    repeated = _summary(repeated_job, repeated_elapsed)
    report = {
        "first": first,
        "repeated": repeated,
        "same_input_token": first.pop("token", None) == repeated.pop("token", None),
        "targets": {
            "first_at_most_seconds": 30.0,
            "repeated_at_most_seconds": 1.0,
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    first_cache_hit = first.get("preview", {}).get("cache_hit") is True
    passed = (
        not first_cache_hit
        and first.get("job_status") == "completed"
        and repeated.get("job_status") == "completed"
        and report["same_input_token"]
        and first_elapsed <= 30.0
        and repeated_elapsed <= 1.0
        and repeated.get("preview", {}).get("cache_hit") is True
    )
    if first_cache_hit:
        print(
            "The first request was already cached; run after the input token changes "
            "to measure an uncached calculation.",
            file=sys.stderr,
        )
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HTTPError, URLError, KeyError, TypeError, ValueError, TimeoutError) as exc:
        print(f"planning preview benchmark failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
