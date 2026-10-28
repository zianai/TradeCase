"""Opt-in real PostgreSQL/Redis and backup recovery tests; synthetic data only.

Run via ops/verify_infrastructure.py, or set TRADECASE_TEST_POSTGRES_URL,
TRADECASE_TEST_REDIS_URL and (for dump/restore) TRADECASE_TEST_PG_CONTAINER.
These tests create and drop only databases named tc_test_<random hex>.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from typing import TypedDict
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from arq.connections import RedisSettings, create_pool
from arq.worker import Worker, func
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from psycopg import sql
from sqlalchemy import inspect, select
from sqlalchemy.engine import make_url

from tradecase.platform.db import Case, Database, Inquiry, Organization, Source, TaskAttempt, utcnow
from tradecase.platform.storage import LocalStorage
from tradecase.platform.tasks import LeaseLost, TaskManager

ROOT = Path(__file__).resolve().parents[2]
_SOCKET_CONNECT = socket.socket.connect


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Override offline guard only for explicitly configured loopback services."""
    allowed = set()
    for name in ("TRADECASE_TEST_POSTGRES_URL", "TRADECASE_TEST_REDIS_URL"):
        value = os.getenv(name)
        if value:
            parsed = urlsplit(value)
            if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.port is None:
                raise ValueError("infrastructure tests require an explicit loopback host and port")
            allowed.add(("127.0.0.1" if parsed.hostname == "localhost" else parsed.hostname, parsed.port))

    def connect(sock, address):
        if not isinstance(address, tuple) or address[:2] not in allowed:
            raise AssertionError("Only explicit isolated test services may receive sockets")
        return _SOCKET_CONNECT(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)


def _dsn(url):
    return str(make_url(url).set(drivername="postgresql").render_as_string(hide_password=False))


@pytest.fixture
def postgres_database(monkeypatch):
    url = os.getenv("TRADECASE_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("real PostgreSQL requires explicit isolated test connection")
    name = "tc_test_" + uuid4().hex
    admin_dsn = _dsn(url)
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    test_url = make_url(url).set(drivername="postgresql+psycopg", database=name).render_as_string(hide_password=False)
    monkeypatch.setenv("TRADECASE_DATABASE_URL", test_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", test_url.replace("%", "%%"))
    command.upgrade(config, "head")
    db = Database(test_url)
    try:
        yield db, config
    finally:
        db.close()
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def _seed(db):
    with db.session() as session:
        session.add(Organization(id="synthetic-org", name="Synthetic isolated acceptance"))
        session.flush()
        session.add(Inquiry(id="synthetic-inquiry", tenant_id="synthetic-org", raw_hash="a" * 64))
        session.flush()
        session.add(Case(id="synthetic-case", tenant_id="synthetic-org", inquiry_id="synthetic-inquiry"))


def test_postgres_migration_round_trip(postgres_database):
    db, cfg = postgres_database
    assert "case_tasks" in inspect(db.engine).get_table_names()
    command.check(cfg)
    command.downgrade(cfg, "base")
    assert inspect(db.engine).get_table_names() == ["alembic_version"]
    command.upgrade(cfg, "head")
    _seed(db)
    with db.session() as session:
        assert session.get(Case, "synthetic-case").status == "NEW"


def test_postgres_competing_workers_and_crash_fencing(postgres_database):
    db, _ = postgres_database
    _seed(db)
    now = utcnow()
    manager = TaskManager(db, clock=lambda: now)
    item = manager.ensure("synthetic-org", "synthetic-case", "identity", "synthetic-fingerprint")
    barrier = Barrier(2)

    def compete(worker):
        barrier.wait()
        return manager.claim("synthetic-org", item.id, worker, lease_seconds=5)

    with ThreadPoolExecutor(2) as pool:
        claims = [result for result in pool.map(compete, ["one", "two"]) if result]
    assert len(claims) == 1
    now += timedelta(seconds=6)
    restarted = TaskManager(Database(db.url), clock=lambda: now)
    try:
        second = restarted.claim("synthetic-org", item.id, "restarted")
        with pytest.raises(LeaseLost):
            manager.complete(claims[0], {"stale": True})
        restarted.complete(second, {"status": "PARTIAL", "synthetic": True})
        assert manager.get("synthetic-org", item.id).result["synthetic"] is True
        with db.session() as session:
            attempts = session.scalars(select(TaskAttempt).order_by(TaskAttempt.attempt_number)).all()
            assert [attempt.status for attempt in attempts] == ["LOST", "SUCCEEDED"]
    finally:
        restarted.db.close()


def test_real_arq_delivery_uses_database_idempotency(postgres_database):
    redis_url = os.getenv("TRADECASE_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("real Redis requires explicit isolated test connection")
    db, _ = postgres_database
    _seed(db)
    manager = TaskManager(db)
    item = manager.ensure("synthetic-org", "synthetic-case", "queued-research", "synthetic-fingerprint")

    async def queue_check():
        queue = "tc_test_queue_" + uuid4().hex
        redis = await create_pool(RedisSettings.from_dsn(redis_url), default_queue_name=queue)

        async def perform(_ctx, task_id):
            lease = manager.claim("synthetic-org", task_id, "arq-worker")
            if lease is None:
                return "already-recorded"
            manager.complete(lease, {"synthetic": True, "delivered": "redis-arq"})
            return "recorded"

        worker = Worker(functions=[func(perform, name="perform")], redis_pool=redis, queue_name=queue, burst=True,
                        max_jobs=2, poll_delay=0.01, handle_signals=False, keep_result=0, log_results=False)
        try:
            first = await redis.enqueue_job("perform", item.id, _job_id=queue + "-1")
            duplicate = await redis.enqueue_job("perform", item.id, _job_id=queue + "-1")
            # Deliberately different queue IDs deliver the same logical task twice.
            await redis.enqueue_job("perform", item.id, _job_id=queue + "-2")
            assert first is not None and duplicate is None
            await worker.async_run()
            assert worker.jobs_complete == 2
            assert manager.get("synthetic-org", item.id).attempt_count == 1
        finally:
            await worker.close()
            await redis.aclose()

    asyncio.run(queue_check())


class RecoveryState(TypedDict, total=False):
    case_id: str
    approved: bool


def _recovery_graph(saver):
    graph = StateGraph(RecoveryState)

    def review(_state):
        decision = interrupt({"approval_id": "synthetic-approval", "artifact_hash": "a" * 64})
        return {"approved": bool(decision["approved"])}

    graph.add_node("review", review)
    graph.add_edge(START, "review")
    graph.add_edge("review", END)
    return graph.compile(checkpointer=saver)


def test_postgres_dump_restore_objects_and_interrupted_checkpoint(postgres_database, tmp_path):
    container = os.getenv("TRADECASE_TEST_PG_CONTAINER")
    if not container:
        pytest.skip("pg_dump/restore test needs the explicitly named isolated test container")
    db, _ = postgres_database
    _seed(db)
    store = LocalStorage(tmp_path / "objects")
    ref = store.put(b"Synthetic evidence retained across database restore")
    with db.session() as session:
        session.add(Source(id="synthetic-source", tenant_id="synthetic-org", case_id="synthetic-case",
                           snapshot_ref=ref.key, snapshot_hash=ref.sha256))
    config = {"configurable": {"thread_id": "stable-synthetic-workflow"}}

    async def checkpoint():
        async with AsyncPostgresSaver.from_conn_string(_dsn(db.url)) as saver:
            await saver.setup()
            graph = _recovery_graph(saver)
            state = await graph.ainvoke({"case_id": "synthetic-case", "approved": False}, config)
            assert state["__interrupt__"]

    asyncio.run(checkpoint())
    source_name = make_url(db.url).database
    user = make_url(db.url).username
    dump = subprocess.run(["docker", "exec", container, "pg_dump", "-U", user, "-d", source_name,
                           "--format=custom", "--no-owner"], check=True, capture_output=True, timeout=60).stdout
    assert dump.startswith(b"PGDMP")
    target_name = "tc_test_" + uuid4().hex
    admin_dsn = _dsn(os.environ["TRADECASE_TEST_POSTGRES_URL"])
    restored_url = make_url(db.url).set(database=target_name).render_as_string(hide_password=False)
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_name)))
    restored = Database(restored_url)
    try:
        subprocess.run(["docker", "exec", "-i", container, "pg_restore", "-U", user, "-d", target_name,
                        "--no-owner", "--exit-on-error"], input=dump, check=True, capture_output=True, timeout=60)
        with restored.session() as session:
            assert session.get(Case, "synthetic-case").tenant_id == "synthetic-org"
            saved = session.get(Source, "synthetic-source")
            assert store.verify(saved.snapshot_ref, saved.snapshot_hash)

        async def resume_restored():
            async with AsyncPostgresSaver.from_conn_string(_dsn(restored_url)) as saver:
                graph = _recovery_graph(saver)
                assert (await graph.aget_state(config)).next == ("review",)
                state = await graph.ainvoke(Command(resume={"approved": True}), config)
                assert state["approved"] is True

        asyncio.run(resume_restored())
    finally:
        restored.close()
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(target_name)))
