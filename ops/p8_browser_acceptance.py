"""Disposable loopback API + Next browser regression. Never inherits model credentials."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config

from tradecase.platform.config import Settings
from tradecase.platform.db import Database
from tradecase.platform.services import CaseService

ROOT = Path(__file__).resolve().parents[1]


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--tests", nargs="+", default=["p8-provenance.spec.ts", "live-e2e.spec.ts"])
    args = parser.parse_args()
    output = args.evidence.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "TMPDIR", "PLAYWRIGHT_BROWSERS_PATH", "PLAYWRIGHT_CHROMIUM_EXECUTABLE") if key in os.environ}
    env.update(OPENAI_AGENTS_DISABLE_TRACING="1", OTEL_SDK_DISABLED="true", NEXT_TELEMETRY_DISABLED="1", DO_NOT_TRACK="1")
    with tempfile.TemporaryDirectory(prefix="tradecase-p8-") as temporary:
        state = Path(temporary).resolve()
        settings = Settings(database_url="sqlite:///" + str(state / "db.sqlite"),
                            checkpoint_url="sqlite:///" + str(state / "checkpoints.sqlite"),
                            storage_root=state / "objects", work_root=state / "work",
                            demo_enabled=True, queue_mode="local", runtime="fake", live_model_enabled=False,
                            outbound_enabled=False, public_fetch_enabled=False)
        settings.prepare()
        cfg = Config(str(ROOT / "alembic.ini"))
        # env.py reads the environment; change only this isolated child process.
        os.environ["TRADECASE_DATABASE_URL"] = settings.database_url
        command.upgrade(cfg, "head")
        db = Database(settings.database_url)
        _, token = CaseService(db, settings).provision("synthetic-browser-p8", "Synthetic test operator")
        token_file = state / "browser-token"
        token_file.write_text(token)
        token_file.chmod(0o600)
        db.close()
        api_port, web_port = port(), port()
        env.update(TRADECASE_DATABASE_URL=settings.database_url, TRADECASE_CHECKPOINT_URL=settings.checkpoint_url,
                   TRADECASE_STORAGE_ROOT=str(settings.storage_root), TRADECASE_WORK_ROOT=str(settings.work_root),
                   TRADECASE_DEMO_ENABLED="true", TRADECASE_QUEUE_MODE="local", TRADECASE_RUNTIME="fake",
                   TRADECASE_LIVE_MODEL_ENABLED="false", TRADECASE_OUTBOUND_ENABLED="false",
                   TRADECASE_PUBLIC_FETCH_ENABLED="false", TRADECASE_API_URL=f"http://127.0.0.1:{api_port}",
                   TRADECASE_WEB_URL=f"http://127.0.0.1:{web_port}", TRADECASE_E2E_TOKEN_FILE=str(token_file),
                   TRADECASE_SCREENSHOT_DIR=str(output))
        children = []
        logs = []
        try:
            for label, cmd, cwd in [
                ("api", [sys.executable, "-m", "uvicorn", "tradecase.platform.server:app", "--host", "127.0.0.1", "--port", str(api_port)], ROOT),
                ("web", ["node", "node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", str(web_port)], ROOT / "frontend"),
            ]:
                log = (output / (label + ".log")).open("w")
                logs.append(log)
                children.append(subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT))
            with httpx.Client(trust_env=False, timeout=5) as client:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    try:
                        if client.get(env["TRADECASE_WEB_URL"] + "/api/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError("isolated browser stack failed health check")
                latencies = []
                for _ in range(10):
                    start = time.monotonic()
                    assert client.get(env["TRADECASE_WEB_URL"] + "/api/health").status_code == 200
                    latencies.append(round((time.monotonic() - start) * 1000, 3))
                assert client.get(env["TRADECASE_WEB_URL"] + "/api/cases").status_code == 401
            result = subprocess.run(["node", "node_modules/@playwright/test/cli.js", "test", *args.tests],
                                    cwd=ROOT / "frontend", env=env, timeout=300)
            (output / "runtime.json").write_text(json.dumps({
                "mode": "E1 synthetic", "db": "fresh SQLite via Alembic", "binding": "127.0.0.1",
                "health_latency_ms": latencies, "scope": "10 sequential loopback health probes; not an SLA",
                "browser_exit_code": result.returncode, "paid_calls": 0, "external_business_writes": 0,
                "design_approval": "pending", "secret_environment_inherited": False,
            }, indent=2) + "\n")
            return result.returncode
        finally:
            for child in reversed(children):
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            for log in logs:
                log.close()


if __name__ == "__main__":
    raise SystemExit(main())
