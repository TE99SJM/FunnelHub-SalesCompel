"""Synthetic snapshots only. PostgreSQL tests require an explicit disposable DSN."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine, inspect, select, text

from app.database import Base
from app.legacy_import import Snapshot, ImportRefused, apply, verify, cipher, digest_file, private_value
from app.security import hash_password, verify_password

PASSWORD_HASH = hash_password("synthetic-migration-password")


@pytest.fixture()
def legacy(tmp_path):
    source = tmp_path / "snapshot.db"
    media = tmp_path / "source-media"
    media.mkdir()
    (media / "one.png").write_bytes(b"synthetic image")
    (media / "one.jpg").write_bytes(b"synthetic derivative")
    engine = create_engine(f"sqlite:///{source}")
    tables = [t for t in Base.metadata.sorted_tables if t.name != "crm_projections"]
    Base.metadata.create_all(engine, tables=tables)
    payloads = {
        "users": dict(id=7, email="owner@example.invalid", name="Owner", password_hash=PASSWORD_HASH),
        "channels": dict(id=11, name="Synthetic shop"),
        "contacts": dict(id=31, first_name="Test", email="one@example.invalid", source_channel_id=11,
                         external_source="square", external_id="customer-one"),
        "funnels": dict(id=19, name="Pipeline"),
        "funnel_stages": dict(id=23, funnel_id=19, name="Open"),
        "deals": dict(id=37, funnel_id=19, stage_id=23, contact_id=31, title="Synthetic deal"),
        "activities": dict(id=41, contact_id=31, deal_id=37, summary="Follow-up"),
        "posts": dict(id=43, title="Planned", channel_id=11, status="scheduled"),
        "integrations": dict(id=47, provider="square", channel_id=11, enabled=True, last_status="running",
            secrets=cipher("synthetic-source-key").encrypt(json.dumps({"access_token": "never-log-this-token",
                                                                      "oauth_state": "stale-state"}).encode()).decode()),
        "orders": dict(id=53, external_id="order-one", contact_id=31, deal_id=37, channel_id=11),
        "emails": dict(id=59, account="owner@example.invalid", uid=4, uidvalidity=5, gm_msgid="mail-one", contact_id=31),
        "conversations": dict(id=61, source="test", integration_id=47, external_id="thread-one", contact_id=31),
        "messages": dict(id=67, conversation_id=61, external_id="message-one", body="Synthetic message"),
        "media_files": dict(id=71, token="old-public-token", stored_name="one.png", jpeg_name="one.jpg", size=15),
        "publish_jobs": dict(id=73, title="Held", media_ids="[71]", status="posting"),
        "publish_targets": dict(id=79, job_id=73, integration_id=47, post_id=43, platform="youtube", status="posting"),
        "notify_settings": dict(id=83, config='{"enabled":true,"twilio_enabled":true}'),
        "channel_metrics": dict(id=89, channel_id=11, key="views", label="Views", value=12),
        "metric_snapshots": dict(id=97, channel_id=11, key="views", day=__import__("datetime").date(2026, 1, 1), value=12),
        "stat_snapshots": dict(id=101, metric="views", day=__import__("datetime").date(2026, 1, 1), value=12),
        "composer_drafts": dict(id=103, title="Saved", media_ids="[71]", target_ids="[47]"),
    }
    with engine.begin() as conn:
        for table in tables:
            conn.execute(table.insert(), payloads[table.name])
    engine.dispose()
    return source, media


def change(source, sql, params=()):
    with sqlite3.connect(source) as db:
        db.execute(sql, params)


def test_assess_is_read_only_and_masks_rows(legacy):
    source, media = legacy
    before = digest_file(source)
    report = Snapshot(source, media).report()
    assert report["table_counts"]["contacts"] == 1
    assert report["media_files"] == 2
    assert before == digest_file(source)
    assert not Path(str(source) + "-wal").exists()
    assert "never-log" not in json.dumps(report)
    assert "example.invalid" not in json.dumps(report)


@pytest.mark.parametrize("sql,code", [
    ("UPDATE contacts SET source_channel_id=999", "SOURCE_FOREIGN_KEY_FAILURE"),
    ("UPDATE contacts SET first_name=NULL", "NULL_IN_REQUIRED_COLUMN"),
    ("UPDATE integrations SET enabled=3", "INVALID_BOOLEAN"),
    ("UPDATE contacts SET created_at='bad-date'", "INVALID_DATE"),
    ("UPDATE contacts SET first_name='" + "x" * 81 + "'", "TEXT_TOO_LONG"),
    ("UPDATE publish_jobs SET media_ids='[999]'", "MISSING_MEDIA_REFERENCE"),
    ("UPDATE composer_drafts SET target_ids='[999]'", "MISSING_DRAFT_TARGET"),
    ("UPDATE integrations SET config='[]'", "INVALID_SOURCE_JSON"),
    ("ALTER TABLE contacts ADD COLUMN future_value TEXT", "SOURCE_COLUMNS_UNSUPPORTED"),
    ("CREATE TABLE future_table (id INTEGER)", "SOURCE_SCHEMA_UNSUPPORTED"),
    ("UPDATE media_files SET stored_name='../escape'", "UNSAFE_MEDIA_PATH"),
    ("UPDATE media_files SET size=999", "MEDIA_SIZE_MISMATCH"),
])
def test_invalid_sources_fail_closed(legacy, sql, code):
    source, media = legacy
    if "first_name=NULL" in sql:
        # Bypass source NOT NULL via a known-schema table reconstruction.
        with sqlite3.connect(source) as db:
            ddl = db.execute("SELECT sql FROM sqlite_master WHERE name='contacts'").fetchone()[0]
            db.execute("PRAGMA writable_schema=ON")
            db.execute("UPDATE sqlite_master SET sql=? WHERE name='contacts'", (ddl.replace("first_name VARCHAR(80) NOT NULL", "first_name VARCHAR(80)"),))
    change(source, sql)
    with pytest.raises(ImportRefused, match=code):
        Snapshot(source, media)


def test_wal_and_symlink_refused(legacy, tmp_path):
    source, media = legacy
    wal = Path(str(source) + "-wal")
    wal.touch()
    with pytest.raises(ImportRefused, match="STANDALONE"):
        Snapshot(source, media)
    wal.unlink()
    (media / "one.png").unlink()
    (media / "one.png").symlink_to(source)
    with pytest.raises(ImportRefused, match="LINKED_MEDIA"):
        Snapshot(source, media)


def test_duplicate_provider_identity_refused_but_email_is_not_merged(legacy):
    source, media = legacy
    with sqlite3.connect(source) as db:
        row = db.execute("SELECT * FROM contacts").fetchone()
        db.execute("INSERT INTO contacts VALUES (" + ",".join("?" for _ in row) + ")", (32, *row[1:]))
    with pytest.raises(ImportRefused, match="DUPLICATE_PROVIDER"):
        Snapshot(source, media)
    change(source, "UPDATE contacts SET external_id='customer-two' WHERE id=32")
    snapshot = Snapshot(source, media)
    assert snapshot.report()["duplicate_contact_email_groups"] == 1
    assert len(snapshot.rows["contacts"]) == 2


def test_reconnect_default_holds_and_reencryption(legacy):
    snapshot = Snapshot(*legacy)
    rows = snapshot.transformed()
    assert rows["integrations"][0]["secrets"] == ""
    assert not rows["integrations"][0]["enabled"]
    assert not json.loads(rows["notify_settings"][0]["config"])["enabled"]
    assert rows["publish_jobs"][0]["status"] == "canceled"
    assert rows["publish_targets"][0]["status"] == "canceled"
    assert rows["posts"][0]["status"] == "draft"
    assert rows["users"][0]["password_hash"] == PASSWORD_HASH
    assert rows["media_files"][0]["token"] != "old-public-token"
    assert not rows["crm_projections"][0]["pending"]
    again = snapshot.transformed("synthetic-source-key", "synthetic-target-key")
    assert rows["crm_projections"] == again["crm_projections"]
    sec = json.loads(cipher("synthetic-target-key").decrypt(again["integrations"][0]["secrets"].encode()))
    assert sec == {"access_token": "never-log-this-token"}
    with pytest.raises(ImportRefused, match="DECRYPTION_FAILED"):
        snapshot.transformed("incorrect-key", "synthetic-target-key")


def test_older_added_columns_get_defaults(legacy):
    source, media = legacy
    change(source, "ALTER TABLE channels DROP COLUMN total_views")
    change(source, "ALTER TABLE channels DROP COLUMN display_metrics")
    assert Snapshot(source, media).rows["channels"][0]["total_views"] == 0


def test_private_files_and_cli_error_redaction(legacy, tmp_path):
    key = tmp_path / "key"
    key.write_text("never-log-this-token")
    key.chmod(0o644)
    with pytest.raises(ImportRefused, match="PERMISSIONS"):
        private_value(key)
    key.chmod(0o600)
    assert private_value(key) == "never-log-this-token"
    cli = Path(__file__).resolve().parents[4] / "scripts/funnelhub/import_legacy.py"
    result = subprocess.run([sys.executable, str(cli), "apply", "--snapshot", str(legacy[0]),
                             "--source-media", str(legacy[1])], capture_output=True, text=True)
    assert result.returncode == 2
    assert json.loads(result.stdout)["code"] == "TARGET_ARGUMENTS_REQUIRED"
    assert not result.stderr


@pytest.fixture()
def pg():
    url = os.getenv("FUNNELHUB_MIGRATION_TEST_URL")
    if not url:
        pytest.skip("explicit disposable PostgreSQL migration DSN not supplied")
    engine = create_engine(url, hide_parameters=True)
    yield engine
    engine.dispose()


def test_postgres_roundtrip_reconcile_sequences_replay_and_rollback(legacy, tmp_path, pg):
    snapshot = Snapshot(*legacy)
    schema = "fh_rehearsal_" + uuid.uuid4().hex
    media = tmp_path / "imported-media"
    private = {"dsn": pg.url.render_as_string(hide_password=False),
               "source-key": "synthetic-source-key", "target-key": "synthetic-target-key"}
    for name, value in private.items():
        (tmp_path / name).write_text(value)
        (tmp_path / name).chmod(0o600)
    cli = Path(__file__).resolve().parents[4] / "scripts/funnelhub/import_legacy.py"
    process = subprocess.run([sys.executable, str(cli), "apply", "--snapshot", str(legacy[0]),
        "--source-media", str(legacy[1]), "--dsn-file", str(tmp_path / "dsn"), "--schema", schema,
        "--target-media", str(media), "--source-key-file", str(tmp_path / "source-key"),
        "--target-key-file", str(tmp_path / "target-key"), "--disposable-target"], capture_output=True, text=True)
    assert process.returncode == 0, process.stdout
    assert not process.stderr and "never-log-this-token" not in process.stdout
    result = json.loads(process.stdout)
    run_id = result["run_id"]
    assert verify(pg, schema, run_id, media)["reconciled"]
    assert digest_file(legacy[0]) == snapshot.fingerprint
    assert (media / "one.png").read_bytes() == (legacy[1] / "one.png").read_bytes()
    assert (media / "one.png").stat().st_mode & 0o777 == 0o600
    with pg.connect().execution_options(schema_translate_map={None: schema}) as conn:
        assert verify_password("synthetic-migration-password", conn.scalar(select(Base.metadata.tables["users"].c.password_hash)))
        assert conn.execute(select(Base.metadata.tables["orders"])).mappings().one()["contact_id"] == 31
        assert conn.execute(select(Base.metadata.tables["emails"])).mappings().one()["contact_id"] == 31
        assert conn.scalar(text(f"SELECT nextval('{schema}.contacts_id_seq')")) == 32
        assert conn.scalar(text(f"SELECT nextval('{schema}.orders_id_seq')")) == 54
    with pytest.raises(ImportRefused, match="SCHEMA_ALREADY_EXISTS"):
        apply(snapshot, pg, schema, tmp_path / "other-media")
    assert not (tmp_path / "other-media").exists()
    with pytest.raises(ImportRefused, match="RUN_ID_MISMATCH"):
        verify(pg, schema, str(uuid.uuid4()), media, rollback=True)
    assert verify(pg, schema, run_id, media, rollback=True)["mode"] == "rolled-back"
    assert not media.exists()
    assert not inspect(pg).has_schema(schema)
    assert digest_file(legacy[0]) == snapshot.fingerprint


def test_postgres_changed_target_refuses_rollback(legacy, tmp_path, pg):
    schema = "fh_rehearsal_" + uuid.uuid4().hex
    media = tmp_path / "imported-media"
    result = apply(Snapshot(*legacy), pg, schema, media)
    with pg.begin() as conn:
        conn.execute(text(f"UPDATE {schema}.contacts SET first_name='Changed' WHERE id=31"))
    with pytest.raises(ImportRefused, match="TARGET_DATA_CHANGED"):
        verify(pg, schema, result["run_id"], media, rollback=True)
    with pg.begin() as conn:
        conn.execute(text(f"UPDATE {schema}.contacts SET first_name='Test' WHERE id=31"))
    (media / "extra.txt").write_text("operator-added file")
    with pytest.raises(ImportRefused, match="TARGET_MEDIA_CHANGED"):
        verify(pg, schema, result["run_id"], media, rollback=True)
    (media / "extra.txt").unlink()
    with pg.begin() as conn:
        conn.execute(text(f"ALTER TABLE {schema}.contacts ADD COLUMN operator_note text"))
    with pytest.raises(ImportRefused, match="TARGET_SCHEMA_CHANGED"):
        verify(pg, schema, result["run_id"], media, rollback=True)
    with pg.begin() as conn:
        conn.execute(text(f"ALTER TABLE {schema}.contacts DROP COLUMN operator_note"))
    verify(pg, schema, result["run_id"], media, rollback=True)


def test_postgres_rollback_never_cascades_to_other_schemas(legacy, tmp_path, pg):
    from sqlalchemy.exc import DBAPIError
    schema = "fh_rehearsal_" + uuid.uuid4().hex
    outside = "fh_rehearsal_" + uuid.uuid4().hex
    media = tmp_path / "imported-media"
    result = apply(Snapshot(*legacy), pg, schema, media)
    with pg.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA {outside}'))
        conn.execute(text(f'CREATE TABLE {outside}.reference (id int REFERENCES {schema}.contacts(id))'))
        conn.execute(text(f'INSERT INTO {outside}.reference VALUES (31)'))
    with pytest.raises(DBAPIError):
        verify(pg, schema, result["run_id"], media, rollback=True)
    assert verify(pg, schema, result["run_id"], media)["reconciled"]
    with pg.begin() as conn:
        assert conn.scalar(text(f'SELECT id FROM {outside}.reference')) == 31
        conn.execute(text(f'DROP TABLE {outside}.reference'))
        conn.execute(text(f'DROP SCHEMA {outside}'))
    verify(pg, schema, result["run_id"], media, rollback=True)


def test_postgres_failure_rolls_back_schema_and_preserves_private_files(legacy, tmp_path, pg):
    snapshot = Snapshot(*legacy)
    schema = "fh_rehearsal_" + uuid.uuid4().hex
    media = tmp_path / "imported-media"
    (legacy[1] / "one.png").write_bytes(b"changed")
    with pytest.raises(ImportRefused, match="SOURCE_MEDIA_CHANGED"):
        apply(snapshot, pg, schema, media)
    assert not inspect(pg).has_schema(schema)
    assert (media / ".funnelhub-import.json").is_file()
    # Staging files intentionally survive an uncertain outcome for inspection.


@pytest.mark.parametrize("schema", ["public", "funnelhub", "fh_rehearsal_x;DROP SCHEMA public", "fh_rehearsal_"])
def test_production_schema_refused_before_target_access(legacy, tmp_path, schema):
    with pytest.raises(ImportRefused, match="REHEARSAL_SCHEMA_REQUIRED"):
        apply(Snapshot(*legacy), None, schema, tmp_path / "new-media")
