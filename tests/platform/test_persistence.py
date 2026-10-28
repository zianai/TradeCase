"""Actual schema, tenant integrity, immutable versions and migration round trips."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from tradecase.platform.db import (
    Approval,
    Artifact,
    ArtifactVersion,
    Base,
    Case,
    Database,
    EventLog,
    Inquiry,
    Organization,
    OutboundAction,
    Source,
    utcnow,
)


def seeded_db(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'domain.db'}")
    db.create_schema()
    with db.session() as session:
        session.add_all([Organization(id="org1", name="One"), Organization(id="org2", name="Two")])
        session.flush()
        session.add_all([Inquiry(id="inq1", tenant_id="org1", raw_hash="a" * 64),
                         Inquiry(id="inq2", tenant_id="org2", raw_hash="b" * 64)])
        session.flush()
        session.add_all([Case(id="case1", tenant_id="org1", inquiry_id="inq1"),
                         Case(id="case2", tenant_id="org2", inquiry_id="inq2")])
    return db


def test_schema_has_business_entities_and_timezone(tmp_path):
    db = seeded_db(tmp_path)
    assert set(Base.metadata.tables) == set(inspect(db.engine).get_table_names())
    assert "source_cache" in Base.metadata.tables
    assert db.ping()
    with db.session() as session:
        case = session.get(Case, "case1")
        assert case.created_at.utcoffset().total_seconds() == 0
        assert case.version == 1 and case.status == "NEW"


def test_composite_tenant_foreign_key_rejects_cross_tenant_reference(tmp_path):
    db = seeded_db(tmp_path)
    with pytest.raises(IntegrityError), db.session() as session:
        session.add(Case(id="bad", tenant_id="org1", inquiry_id="inq2"))
    with pytest.raises(IntegrityError), db.session() as session:
        session.add(Source(tenant_id="org2", case_id="case1"))


def test_immutable_original_and_artifact_version(tmp_path):
    db = seeded_db(tmp_path)
    with pytest.raises(ValueError, match="immutable"), db.session() as session:
        session.get(Inquiry, "inq1").raw_hash = "c" * 64
    with db.session() as session:
        session.add(Artifact(id="draft", tenant_id="org1", case_id="case1", kind="draft"))
        session.flush()
        session.add(ArtifactVersion(id="version", tenant_id="org1", case_id="case1", artifact_id="draft",
                                    version=1, content_hash="c" * 64, storage_ref="object"))
    with pytest.raises(ValueError, match="immutable"), db.session() as session:
        session.get(ArtifactVersion, "version").data = {"replacement": True}


def test_events_monotonic_with_reconnect_cursor(tmp_path):
    db = seeded_db(tmp_path)
    with db.session() as session:
        session.add(EventLog(id="first", tenant_id="org1", case_id="case1", event_type="created"))
        session.add(EventLog(id="other", tenant_id="org2", case_id="case2", event_type="created"))
        session.add(EventLog(id="last", tenant_id="org1", case_id="case1", event_type="ready"))
    with db.session() as session:
        events = session.scalars(select(EventLog).where(EventLog.tenant_id == "org1", EventLog.sequence > 1)
                                 .order_by(EventLog.sequence)).all()
        assert [event.id for event in events] == ["last"]


def test_external_effect_has_two_independent_deduplication_constraints(tmp_path):
    db = seeded_db(tmp_path)
    with db.session() as session:
        session.add(Artifact(id="a", tenant_id="org1", case_id="case1", kind="draft"))
        session.flush()
        session.add(ArtifactVersion(id="av", tenant_id="org1", case_id="case1", artifact_id="a", version=1,
                                    content_hash="a" * 64, storage_ref="ref"))
        session.flush()
        session.add(Approval(id="p", tenant_id="org1", case_id="case1", artifact_version_id="av",
                             artifact_hash="a" * 64, case_version=1, action_scope="mail_send"))
        session.flush()
        session.add(OutboundAction(tenant_id="org1", case_id="case1", approval_id="p", artifact_hash="a" * 64,
                                   idempotency_key="key1", logical_fingerprint="f" * 64))
    with pytest.raises(IntegrityError), db.session() as session:
        session.add(OutboundAction(tenant_id="org1", case_id="case1", approval_id="p", artifact_hash="a" * 64,
                                   idempotency_key="key2", logical_fingerprint="g" * 64))


def test_alembic_upgrade_downgrade_and_upgrade(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADECASE_DATABASE_URL", raising=False)
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    db = Database(url)
    assert set(Base.metadata.tables) <= set(inspect(db.engine).get_table_names())
    command.check(cfg)
    command.downgrade(cfg, "base")
    assert inspect(db.engine).get_table_names() == ["alembic_version"]
    command.upgrade(cfg, "head")
    assert db.ping()


def test_naive_timestamp_rejected(tmp_path):
    from sqlalchemy.exc import StatementError
    db = seeded_db(tmp_path)
    with pytest.raises(StatementError, match="timezone"), db.session() as session:
        session.add(EventLog(tenant_id="org1", case_id="case1", event_type="test", created_at=utcnow().replace(tzinfo=None)))
