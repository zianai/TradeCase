"""Actual loopback HTTPS with a disposable CA, database and no model credentials."""
from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    output = parser.parse_args().evidence.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tradecase-local-tls-") as directory:
        state = Path(directory).resolve()
        env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "TMPDIR") if key in os.environ}
        env.update(TRADECASE_DATABASE_URL="sqlite:///" + str(state / "db.sqlite"),
                   TRADECASE_CHECKPOINT_URL="sqlite:///" + str(state / "checkpoint.sqlite"),
                   TRADECASE_STORAGE_ROOT=str(state / "objects"), TRADECASE_WORK_ROOT=str(state / "work"),
                   TRADECASE_RUNTIME="fake", TRADECASE_QUEUE_MODE="local", TRADECASE_OUTBOUND_ENABLED="false",
                   TRADECASE_PUBLIC_FETCH_ENABLED="false", TRADECASE_LIVE_MODEL_ENABLED="false",
                   OPENAI_AGENTS_DISABLE_TRACING="1", OTEL_SDK_DISABLED="true", ALLOW_TEST_LIVE="off")
        cert, key = state / "cert.pem", state / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-keyout", str(key), "-out", str(cert), "-subj", "/CN=127.0.0.1",
                        "-addext", "subjectAltName=IP:127.0.0.1"],
                       env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        key.chmod(0o600)
        subprocess.run([sys.executable, "-m", "tradecase.platform.cli", "init-db"], cwd=ROOT, env=env, check=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with (output / "api.log").open("w") as log:
            server = subprocess.Popen([sys.executable, "-m", "uvicorn", "tradecase.platform.server:app",
                "--host", "127.0.0.1", "--port", str(port), "--ssl-keyfile", str(key), "--ssl-certfile", str(cert)],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                url = f"https://127.0.0.1:{port}"
                with httpx.Client(verify=ssl.create_default_context(cafile=str(cert)), trust_env=False, timeout=3) as client:
                    for _ in range(150):
                        try:
                            health = client.get(url + "/api/health")
                            if health.status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("isolated TLS server failed readiness")
                    assert health.headers["x-content-type-options"] == "nosniff"
                    assert health.headers["cache-control"] == "no-store"
                    assert health.headers["referrer-policy"] == "no-referrer"
                    assert client.get(url + "/api/cases").status_code == 401
                    assert client.get(url + "/api/cases/unknown/sources/unknown/snapshot").status_code == 401
                try:
                    with httpx.Client(trust_env=False, timeout=3) as untrusted:
                        untrusted.get(url + "/api/health")
                except httpx.ConnectError:
                    pass
                else:
                    raise AssertionError("untrusted self-signed certificate accepted")
                result = {"mode": "E1 synthetic", "binding": "127.0.0.1", "verified_tls_health": 200,
                    "unauthorized_case_and_asset": 401, "unknown_ca_rejected": True,
                    "security_headers": ["nosniff", "no-store", "no-referrer"], "paid_calls": 0,
                    "certificate_scope": "disposable one-day self-signed local CA; no production TLS claim"}
                (output / "tls.json").write_text(json.dumps(result, indent=2) + "\n")
                print(json.dumps(result))
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
