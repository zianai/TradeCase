"""Run synthetic acceptance against owned, temporary Docker infrastructure."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=180, **kwargs)


def wait(container, command):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = subprocess.run(["docker", "exec", container, *command], capture_output=True, timeout=5)
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise RuntimeError("isolated infrastructure did not become ready")


def main():
    suffix = secrets.token_hex(5)
    pg = "tradecase-test-pg-" + suffix
    redis = "tradecase-test-redis-" + suffix
    password = secrets.token_urlsafe(24)
    owned = []
    env = dict(os.environ)
    try:
        run(["docker", "run", "--detach", "--name", pg, "--label", "tradecase.test=full-delivery",
             "--publish", "127.0.0.1::5432", "--env", "POSTGRES_USER=tradecase",
             "--env", "POSTGRES_DB=tradecase", "--env", "POSTGRES_PASSWORD=" + password,
             "postgres:17.6-bookworm"])
        owned.append(pg)
        run(["docker", "run", "--detach", "--name", redis, "--label", "tradecase.test=full-delivery",
             "--publish", "127.0.0.1::6379", "redis:7.4.6-alpine"])
        owned.append(redis)
        wait(pg, ["pg_isready", "-h", "127.0.0.1", "-U", "tradecase", "-d", "tradecase"])
        wait(redis, ["redis-cli", "ping"])
        pg_port = run(["docker", "port", pg, "5432/tcp"]).stdout.strip().rsplit(":", 1)[1]
        redis_port = run(["docker", "port", redis, "6379/tcp"]).stdout.strip().rsplit(":", 1)[1]
        env.update({
            "TRADECASE_TEST_POSTGRES_URL": f"postgresql+psycopg://tradecase:{password}@127.0.0.1:{pg_port}/tradecase",
            "TRADECASE_TEST_REDIS_URL": f"redis://127.0.0.1:{redis_port}/0",
            "TRADECASE_TEST_PG_CONTAINER": pg,
        })
        # Never print URLs/credentials, and preserve pytest's exit code.
        return subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/platform/test_deployment.py"],
                              cwd=ROOT, env=env, timeout=300).returncode
    finally:
        for container in reversed(owned):
            subprocess.run(["docker", "rm", "--force", "--volumes", container],
                           capture_output=True, timeout=30, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
