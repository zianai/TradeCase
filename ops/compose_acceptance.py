"""Synthetic product acceptance through the running Next.js/ARQ/PostgreSQL stack.

The caller starts a fresh Compose project first. This script provisions a local
synthetic user, drives a Case to a persisted human interrupt, runs real backup and
restore into another new project, then resumes the restored workflow. It does not
print bearer tokens or database passwords. Both stacks remain for inspection; the
operator removes only these explicitly named projects after acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIGEST = (
    "import hashlib,pathlib; root=pathlib.Path('/app/src/tradecase'); h=hashlib.sha256(); "
    "[(h.update(p.relative_to(root).as_posix().encode()+b'\\0'),h.update(p.read_bytes())) "
    "for p in sorted(root.rglob('*.py'))]; print(h.hexdigest())"
)


def local_package_digest():
    root = ROOT / "src" / "tradecase"
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def run(args, *, env=None):
    result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    if result.returncode:
        # Commands use private env files, never credential values in argv. Tokens
        # are read only on a successful cat; do not print arbitrary stdout here.
        raise RuntimeError("Acceptance subprocess failed: " + str(args[:3]) + "\n" + result.stderr[-12000:])
    return result


def wait_case(client, identity, status, headers):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        response = client.get(f"/api/cases/{identity}", headers=headers)
        response.raise_for_status()
        case = response.json()
        if case["status"] == status:
            return case
        if case["status"] == "FAILED":
            raise RuntimeError("Synthetic workflow failed; inspect sanitized workflow/task events")
        time.sleep(0.3)
    raise RuntimeError("Synthetic workflow did not reach " + status)


def wait_http(client):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            response = client.get("/api/health")
            if response.status_code == 200 and response.json().get("database") is True:
                return
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(0.3)
    raise RuntimeError("Next.js proxy did not reach a healthy API")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--web-url", default="http://127.0.0.1:3380")
    parser.add_argument("--restore-project")
    parser.add_argument("--restore-api-port", type=int, default=8881)
    parser.add_argument("--restore-web-port", type=int, default=3381)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--smoke-only", action="store_true",
                        help="Run/approve through the current stack without backup or restore")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if urlsplit(args.web_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("acceptance is restricted to a local synthetic deployment")
    if not args.project.startswith("tradecase-") or (not args.smoke_only and (
        not args.restore_project or not args.restore_project.startswith("tradecase-restore-") or not args.backup_dir
    )):
        raise ValueError("explicit TradeCase acceptance and new restore project names are required")
    env_file = str(args.env_file.absolute())
    compose = ["docker", "compose", "--env-file", env_file, "-p", args.project, "-f", "ops/compose.yaml"]
    started = time.monotonic()
    print("Starting synthetic acceptance through Next.js proxy and ARQ worker", flush=True)
    source_digest = run([*compose, "exec", "-T", "api", "python", "-c", PACKAGE_DIGEST]).stdout.strip()
    assert source_digest == local_package_digest(), "Running backend source differs from reviewed local files"
    token_file = "/app/.tradecase/acceptance-token-" + uuid4().hex
    run([*compose, "exec", "-T", "api", "python", "-m", "tradecase.platform.cli", "provision-user",
         "--tenant", "synthetic-docker-acceptance", "--name", "Synthetic acceptance operator",
         "--token-file", token_file])
    token = run([*compose, "exec", "-T", "api", "cat", token_file]).stdout.strip()
    headers = {"Authorization": "Bearer " + token}
    with httpx.Client(base_url=args.web_url, trust_env=False, timeout=20) as client:
        wait_http(client)
        html = client.get("/")
        html.raise_for_status()
        assert "TradeCase" in html.text
        settings = client.get("/api/settings", headers=headers).json()
        assert settings["queue_mode"] == "arq" and settings["runtime"] == "fake"
        assert not settings["outbound_enabled"]
        response = client.post("/api/cases", headers={**headers, "Idempotency-Key": uuid4().hex},
                               json={"title": "Synthetic Docker restore acceptance", "fixture": "case_strong"})
        response.raise_for_status()
        case_id = response.json()["id"]
        response = client.post(f"/api/cases/{case_id}/run", headers=headers)
        response.raise_for_status()
        workflow_id = response.json()["workflow_run_id"]
        case = wait_case(client, case_id, "NEEDS_REVIEW", headers)
        initial_seconds = round(time.monotonic() - started, 3)
        evidence = client.get(f"/api/cases/{case_id}/evidence", headers=headers).json()
        assert evidence["claims"] and evidence["sources"]
        source = evidence["sources"][0]
        snapshot = client.get(source["snapshot_url"], headers=headers)
        snapshot.raise_for_status()
        assert hashlib.sha256(snapshot.content).hexdigest() == source["snapshot_hash"]
        tasks = client.get(f"/api/cases/{case_id}/tasks", headers=headers).json()
        assert any(task["status"] == "WAITING_HUMAN" for task in tasks)
        agents = client.get(f"/api/cases/{case_id}/agent-runs", headers=headers).json()
        assert len(agents) == 3 and all(agent["provider"] == "fake" for agent in agents)
        approvals = client.get("/api/approvals", headers=headers).json()
        approval = next(a for a in approvals if a["case_id"] == case_id and a["status"] == "PENDING")
        events = client.get(f"/api/cases/{case_id}/events?format=json", headers=headers).json()
        assert client.get(f"/api/cases/{case_id}/events?format=json",
                          headers={**headers, "Last-Event-ID": str(events[-1]["sequence"])}).json() == []
    print("Workflow persisted at human approval; evidence hashes and event replay verified", flush=True)

    env = {**os.environ, "TRADECASE_COMPOSE_ENV_FILE": env_file, "TRADECASE_COMPOSE_PROJECT": args.project}
    integrity, backup, restore = {"checked": 0}, None, None
    if args.smoke_only:
        restored_url = args.web_url
    else:
        backup = run(["sh", "ops/backup.sh", str(args.backup_dir.absolute())], env=env)
        assert (args.backup_dir / "database.dump").exists() and (args.backup_dir / "objects.tar.gz").exists()
        print("Quiesced PostgreSQL and object backup completed", flush=True)
        restore = run(["sh", "ops/restore.sh", str(args.backup_dir.absolute()), args.restore_project], env=env)
        integrity = next(json.loads(line) for line in restore.stdout.splitlines() if line.startswith('{"checked":'))
        assert integrity["checked"] > 0 and integrity["errors"] == []
        print("Restored into separate project; object references verified", flush=True)
        restore_env = {**env, "TRADECASE_API_PORT": str(args.restore_api_port),
                       "TRADECASE_WEB_PORT": str(args.restore_web_port)}
        restored_compose = ["docker", "compose", "--env-file", env_file, "-p", args.restore_project,
                            "-f", "ops/compose.yaml"]
        run([*restored_compose, "up", "-d", "--no-build", "--wait", "api", "worker", "frontend"], env=restore_env)
        restored_digest = run([*restored_compose, "exec", "-T", "api", "python", "-c", PACKAGE_DIGEST],
                              env=restore_env).stdout.strip()
        assert restored_digest == source_digest, "Restore must run the same backend source release"
        restored_url = f"http://127.0.0.1:{args.restore_web_port}"
    with httpx.Client(base_url=restored_url, trust_env=False, timeout=20) as client:
        wait_http(client)
        case = wait_case(client, case_id, "NEEDS_REVIEW", headers)
        assert case["workflow_run_id"] == workflow_id
        restored_evidence = client.get(f"/api/cases/{case_id}/evidence", headers=headers).json()
        assert len(restored_evidence["sources"]) == len(evidence["sources"])
        response = client.post("/api/approvals/" + approval["id"] + "/decide",
                               headers={**headers, "Idempotency-Key": uuid4().hex},
                               json={"decision": "approve", "artifact_hash": approval["artifact_hash"],
                                     "case_version": approval["case_version"]})
        response.raise_for_status()
        final = wait_case(client, case_id, "READY_TO_FOLLOW_UP", headers)
        assert final["workflow_run_id"] == workflow_id
        follows = [row for row in client.get("/api/follow-ups", headers=headers).json() if row["case_id"] == case_id]
        assert len(follows) == 1
        assert client.get("/api/metrics", headers=headers).json()["external_sends"] == 0
        blocked = client.post(f"/api/cases/{case_id}/outbound-actions",
                              headers={**headers, "Idempotency-Key": uuid4().hex},
                              json={"approval_id": approval["id"], "artifact_hash": approval["artifact_hash"],
                                    "case_version": approval["case_version"]})
        assert blocked.status_code == 403
        report = client.get(f"/api/cases/{case_id}/export?format=markdown", headers=headers)
        report.raise_for_status()
        assert "SYNTHETIC" in report.text
    print("Workflow resumed to follow-up; external writes remained disabled", flush=True)
    result = {"mode": "synthetic_real_compose_smoke" if args.smoke_only else "synthetic_real_compose",
              "source_project": args.project, "restore_project": None if args.smoke_only else args.restore_project,
              "workflow_run_id": workflow_id, "case_id": case_id, "initial_status": "NEEDS_REVIEW",
              "final_status": final["status"], "restored_status": None if args.smoke_only else final["status"],
              "same_workflow_after_restore": not args.smoke_only, "source_count": len(evidence["sources"]),
              "backend_package_sha256": source_digest,
              "claim_count": len(evidence["claims"]), "research_agent_runs": len(agents),
              "follow_up_count": len(follows), "external_sends": 0, "outbound_denial_http": blocked.status_code,
              "request_to_review_seconds": initial_seconds, "elapsed_seconds": round(time.monotonic()-started, 3),
              "frontend_proxy": True, "postgres_and_arq": True, "actual_backup_restore": not args.smoke_only,
              "restored_objects_verified": integrity["checked"],
              "backup_finished": bool(backup and "Backup created" in backup.stdout),
              "restore_integrity_checked": bool(restore and "Restore integrity checked" in restore.stdout)}
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
