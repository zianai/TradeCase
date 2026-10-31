"""Workbench CLI calls the same services as the HTTP application."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from fastapi.encoders import jsonable_encoder

from tradecase.platform.config import Settings
from tradecase.platform.contracts import CreateCase
from tradecase.platform.coordinator import CaseRunCoordinator
from tradecase.platform.db import Database
from tradecase.platform.services import CaseService
from tradecase.platform.workflow import checkpoint_saver


def main():
    parser = argparse.ArgumentParser(prog="tradecase-workbench")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    provision = sub.add_parser("provision-user")
    provision.add_argument("--tenant", required=True)
    provision.add_argument("--name", required=True)
    provision.add_argument("--role", default="admin")
    provision.add_argument("--token-file", required=True)
    for name in ("rotate-token", "revoke-user"):
        credential = sub.add_parser(name)
        credential.add_argument("--user-id", required=True)
        credential.add_argument("--token-file", required=True, help="Existing scoped admin credential")
        if name == "rotate-token":
            credential.add_argument("--new-token-file", required=True, help="New private credential destination")
    demo = sub.add_parser("demo")
    demo.add_argument("--token-file", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--token-file", required=True)
    create = sub.add_parser("create")
    create.add_argument("--token-file", required=True)
    create.add_argument("--file", required=True)
    run = sub.add_parser("run")
    run.add_argument("case_id")
    run.add_argument("--token-file", required=True)
    maintenance = sub.add_parser("maintenance")
    maintenance.add_argument("operation", choices=["plan", "purge", "verify", "gc"])
    maintenance.add_argument("--token-file", required=True)
    maintenance.add_argument("--before")
    maintenance.add_argument("--case-id")
    maintenance.add_argument("--version", type=int)
    maintenance.add_argument("--idempotency-key")
    maintenance.add_argument("--apply", action="store_true")
    maintenance.add_argument("--quiesced", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    settings.prepare()
    db = Database(settings.database_url)
    service = CaseService(db, settings)
    if args.command == "init-db":
        from alembic import command
        from alembic.config import Config

        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", settings.database_url)
        command.upgrade(cfg, "head")

        async def setup():
            async with checkpoint_saver(settings.checkpoint_url, setup=True):
                pass

        asyncio.run(setup())
        print("Business and checkpoint migrations applied")
        return
    if args.command == "provision-user":
        path = Path(args.token_file).absolute()
        if path.exists() or path.is_symlink():
            raise ValueError("Token destination must be a new file")
        path.parent.mkdir(parents=True, exist_ok=True)
        user, token = service.provision(args.tenant, args.name, args.role)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(token)
        print(
            json.dumps(
                {"user_id": user["id"], "tenant_id": user["tenant_id"], "role": user["role"], "token_file": str(path)}
            )
        )
        return
    token = Path(args.token_file).read_text().strip()
    actor = service.authenticate(token)
    if args.command == "revoke-user":
        service.rotate_credential(actor, args.user_id, revoke=True)
        print(json.dumps({"user_id": args.user_id, "status": "revoked"}))
        return
    if args.command == "rotate-token":
        path = Path(args.new_token_file).absolute()
        # Reserve a new private destination before invalidating the old credential.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w") as output:
                replacement = service.rotate_credential(actor, args.user_id)
                output.write(replacement)
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        print(json.dumps({"user_id": args.user_id, "token_file": str(path), "status": "rotated"}))
        return
    if args.command == "maintenance":
        from datetime import datetime

        from tradecase.platform.maintenance import MaintenanceService

        maintain = MaintenanceService(service)
        if args.operation == "verify":
            result = maintain.verify_objects(actor)
        elif args.operation == "gc":
            service.require(actor, "admin")
            result = maintain.gc_orphans(dry_run=not args.apply, quiesced=args.quiesced)
        else:
            if not args.before:
                parser.error("maintenance plan/purge requires --before with an ISO UTC cutoff")
            before = datetime.fromisoformat(args.before.replace("Z", "+00:00"))
            if args.operation == "plan":
                result = maintain.candidates(actor, before)
            else:
                if not args.case_id or args.version is None or not args.idempotency_key:
                    parser.error("purge requires --case-id, --version and --idempotency-key")
                result = asyncio.run(
                    maintain.purge(
                        actor,
                        args.case_id,
                        before=before,
                        expected_version=args.version,
                        idempotency_key=args.idempotency_key,
                        dry_run=not args.apply,
                    )
                )
    elif args.command == "list":
        result = service.list(actor["tenant_id"])
    elif args.command in {"create", "demo"}:
        import uuid

        request = (
            CreateCase(title="Synthetic demonstration", fixture="case_strong")
            if args.command == "demo"
            else CreateCase(
                title=Path(args.file).name,
                raw_content=Path(args.file).read_text(),
                source_type="eml" if args.file.endswith(".eml") else "text",
            )
        )
        result = service.create(actor, request, uuid.uuid4().hex)
        if args.command == "demo":
            coordinator = CaseRunCoordinator(service)
            workflow = coordinator.request(actor, result["id"])
            asyncio.run(coordinator.run(actor["tenant_id"], workflow["id"]))
            result = service.get(actor["tenant_id"], result["id"])
    else:
        coordinator = CaseRunCoordinator(service)
        workflow = coordinator.request(actor, args.case_id)
        result = asyncio.run(coordinator.run(actor["tenant_id"], workflow["id"]))
    print(json.dumps(jsonable_encoder(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
