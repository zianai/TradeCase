"""Read-only browser acceptance of an already persisted synthetic live response."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    summary = json.loads((root / "summary.json").read_text())
    setup = json.loads((root / "setup.json").read_text())
    if summary["error_class"] or not summary["model_calls_observed"]:
        raise RuntimeError("Only a validated actual response may enter this browser check")
    output = root / "browser"
    output.mkdir(exist_ok=False)
    api_port, web_port = port(), port()
    env = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "LANG", "TMPDIR", "PLAYWRIGHT_BROWSERS_PATH")
        if key in os.environ
    }
    env.update(
        TRADECASE_DATABASE_URL="sqlite:///" + str(root / "case.sqlite"),
        TRADECASE_CHECKPOINT_URL="sqlite:///" + str(root / "checkpoints.sqlite"),
        TRADECASE_STORAGE_ROOT=str(root / "objects"),
        TRADECASE_WORK_ROOT=str(root / "work"),
        TRADECASE_QUEUE_MODE="inline",
        TRADECASE_RUNTIME="fake",
        TRADECASE_DEMO_ENABLED="true",
        TRADECASE_LIVE_MODEL_ENABLED="false",
        TRADECASE_PUBLIC_FETCH_ENABLED="false",
        TRADECASE_OUTBOUND_ENABLED="false",
        OPENAI_AGENTS_DISABLE_TRACING="1",
        OTEL_SDK_DISABLED="true",
        NEXT_TELEMETRY_DISABLED="1",
        ALLOW_TEST_LIVE="off",
        TRADECASE_API_URL=f"http://127.0.0.1:{api_port}",
        TRADECASE_WEB_URL=f"http://127.0.0.1:{web_port}",
        TRADECASE_E2E_TOKEN_FILE=str(root / "api-token.txt"),
        TRADECASE_LIVE_CASE_ID=setup["case_id"],
        TRADECASE_SCREENSHOT_DIR=str(output),
    )
    processes, logs = [], []
    try:
        for name, command, cwd in [
            (
                "api",
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "tradecase.platform.server:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                ],
                REPO,
            ),
            (
                "web",
                [
                    "node",
                    "node_modules/next/dist/bin/next",
                    "start",
                    "--hostname",
                    "127.0.0.1",
                    "--port",
                    str(web_port),
                ],
                REPO / "frontend",
            ),
        ]:
            log = (output / (name + ".log")).open("w")
            logs.append(log)
            processes.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT))
        with httpx.Client(trust_env=False, timeout=3) as client:
            for _ in range(150):
                try:
                    if client.get(env["TRADECASE_WEB_URL"] + "/api/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("Synthetic review stack failed health readiness")
        result = subprocess.run(
            ["node", "node_modules/@playwright/test/cli.js", "test", "followup-live.spec.ts"],
            cwd=REPO / "frontend",
            env=env,
            timeout=180,
        )
        (output / "run.json").write_text(
            json.dumps(
                {
                    "exit_code": result.returncode,
                    "scope": "actual API/browser reading persisted live SDK output; no provider calls or decisions",
                    "loopback_only": True,
                    "service_credentials_inherited": False,
                },
                indent=2,
            )
            + "\n"
        )
        return result.returncode
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
