"""Offline, versioned SQLite import into a NEW PostgreSQL rehearsal schema only.

No web app, scheduler, provider client or source writer is started. The application
schema is reused via SQLAlchemy; this module does not define a second data model.
"""
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import uuid

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, inspect, select, text
from sqlalchemy.schema import CreateSchema, DropSchema

from .database import Base
from . import models  # noqa: F401
from .crm_bridge import CRMProjection
from .routers.drafts import ComposerDraft  # noqa: F401
from .migrate import ADDED_COLUMNS
from .integrations.crypto import fernet_for_key as cipher

VERSION = 1
MARKER = ".funnelhub-import.json"
SCHEMA_PATTERN = r"fh_rehearsal_[a-z0-9_]{1,40}"
NAMESPACE = uuid.UUID("ee6c8af7-b039-4213-b0a5-c6a123ed58ef")


class ImportRefused(Exception):
    """Only fixed error codes are exposed; never include source rows or DB errors."""


def require(condition, code):
    if not condition:
        raise ImportRefused(code)


def digest_file(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def private_value(path):
    path = Path(path)
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not info.st_mode & 0o077, "PRIVATE_FILE_PERMISSIONS_REQUIRED")
    value = path.read_text().strip()
    require(bool(value), "EMPTY_PRIVATE_FILE")
    return value


def json_value(raw, kind):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise ImportRefused("INVALID_SOURCE_JSON") from None
    require(isinstance(value, kind), "INVALID_SOURCE_JSON")
    return value


def convert(column, value):
    if value is None:
        require(column.nullable, "NULL_IN_REQUIRED_COLUMN")
        return None
    kind = column.type
    if isinstance(kind, Boolean):
        require(value in (0, 1) and isinstance(value, int), "INVALID_BOOLEAN")
        return bool(value)
    if isinstance(kind, Integer):
        require(type(value) is int and -(2**31) <= value < 2**31, "INVALID_INTEGER")
    elif isinstance(kind, Float):
        require(isinstance(value, (int, float)) and math.isfinite(value), "INVALID_NUMBER")
    elif isinstance(kind, (Date, DateTime)):
        try:
            value = datetime.fromisoformat(value) if isinstance(kind, DateTime) else date.fromisoformat(value)
            if isinstance(value, datetime) and value.tzinfo:
                value = value.astimezone(timezone.utc).replace(tzinfo=None)
        except (ValueError, TypeError):
            raise ImportRefused("INVALID_DATE") from None
    elif isinstance(kind, (String, Text)):
        require(isinstance(value, str) and "\x00" not in value, "INVALID_TEXT")
        require(not kind.length or len(value) <= kind.length, "TEXT_TOO_LONG")
    return value


def media_path(root, name):
    require(isinstance(name, str) and bool(name) and name not in (".", "..", MARKER) and
            "/" not in name and "\\" not in name and "\x00" not in name, "UNSAFE_MEDIA_PATH")
    path = root / name
    require(path.is_file() and not path.is_symlink(), "MISSING_OR_LINKED_MEDIA")
    return path


class Snapshot:
    """Read and validate one standalone exported snapshot; no live WAL database."""

    def __init__(self, snapshot, media_dir):
        self.path = Path(snapshot).resolve(strict=True)
        self.media_dir = Path(media_dir).resolve(strict=True)
        require(self.media_dir.is_dir(), "MEDIA_DIRECTORY_REQUIRED")
        for suffix in ("-wal", "-shm", "-journal"):
            require(not Path(str(self.path) + suffix).exists(), "STANDALONE_SNAPSHOT_REQUIRED")
        self.fingerprint = digest_file(self.path)
        self.rows = {}
        self.files = {}
        with sqlite3.connect(self.path.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            require(db.execute("PRAGMA quick_check").fetchall()[0][0] == "ok", "SOURCE_INTEGRITY_FAILURE")
            require(not db.execute("PRAGMA foreign_key_check").fetchall(), "SOURCE_FOREIGN_KEY_FAILURE")
            objects = db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
            require(not any(r["type"] in ("view", "trigger") for r in objects), "SOURCE_SCHEMA_UNSUPPORTED")
            tables = {r["name"] for r in objects if r["type"] == "table"}
            known = set(Base.metadata.tables) - {"crm_projections"}
            require({"users", "contacts", "channels"} <= tables <= known, "SOURCE_SCHEMA_UNSUPPORTED")
            self.missing_tables = sorted(known - tables)
            for table in Base.metadata.sorted_tables:
                if table.name not in tables:
                    continue
                columns = {r["name"] for r in db.execute(f'PRAGMA table_info("{table.name}")')}
                added = {name for name, _ in ADDED_COLUMNS.get(table.name, [])}
                require(columns <= set(table.c.keys()) and set(table.c.keys()) - columns <= added,
                        "SOURCE_COLUMNS_UNSUPPORTED")
                rows = []
                for source in db.execute(f'SELECT * FROM "{table.name}" ORDER BY id'):
                    row = {}
                    for col in table.c:
                        value = source[col.name] if col.name in columns else col.default.arg
                        row[col.name] = convert(col, value)
                    require(row["id"] > 0, "NONPOSITIVE_SOURCE_ID")
                    rows.append(row)
                self.rows[table.name] = rows
        require(digest_file(self.path) == self.fingerprint, "SOURCE_CHANGED_DURING_READ")
        self._validate()

    def _validate(self):
        # Some old SQLite databases were opened with FK enforcement off.
        ids_by_table = {name: {r["id"] for r in rows} for name, rows in self.rows.items()}
        for table in Base.metadata.sorted_tables:
            for row in self.rows.get(table.name, []):
                for fk in table.foreign_keys:
                    ids = ids_by_table.get(fk.column.table.name, set())
                    require(row[fk.parent.name] is None or row[fk.parent.name] in ids, "SOURCE_FOREIGN_KEY_FAILURE")
        identities = {
            "users": [("email",)], "contacts": [("external_source", "external_id")],
            "deals": [("external_source", "external_id")], "posts": [("external_source", "external_id")],
            "orders": [("source", "external_id")], "emails": [("account", "gm_msgid"), ("account", "uidvalidity", "uid")],
            "conversations": [("source", "integration_id", "external_id")],
            "messages": [("conversation_id", "external_id")],
            "media_files": [("token",), ("stored_name",)],
            "channel_metrics": [("channel_id", "key")], "metric_snapshots": [("channel_id", "key", "day")],
            "stat_snapshots": [("metric", "day")],
        }
        for name, groups in identities.items():
            for group in groups:
                seen = set()
                for row in self.rows.get(name, []):
                    key = tuple(row[k] for k in group)
                    if name == "users":
                        key = (key[0].strip().casefold(),)
                    if not all(v is not None and v != "" and v != 0 for v in key):
                        continue
                    require(key not in seen, "DUPLICATE_PROVIDER_IDENTITY")
                    seen.add(key)
        for row in self.rows.get("media_files", []):
            for field in ("stored_name", "jpeg_name"):
                name = row[field]
                if not name and field == "jpeg_name":
                    continue
                path = media_path(self.media_dir, name)
                size = path.stat().st_size
                require(field != "stored_name" or size == row["size"], "MEDIA_SIZE_MISMATCH")
                self.files[name] = {"size": size, "sha256": digest_file(path)}
        media_ids = {r["id"] for r in self.rows.get("media_files", [])}
        integration_ids = {r["id"] for r in self.rows.get("integrations", [])}
        for name in ("publish_jobs", "composer_drafts"):
            for row in self.rows.get(name, []):
                ids = json_value(row["media_ids"], list)
                require(all(type(i) is int for i in ids), "INVALID_MEDIA_REFERENCE")
                require(row.get("media_deleted") or set(ids) <= media_ids, "MISSING_MEDIA_REFERENCE")
                if name == "composer_drafts":
                    targets = json_value(row["target_ids"], list)
                    require(all(type(i) is int for i in targets) and set(targets) <= integration_ids,
                            "MISSING_DRAFT_TARGET")
        for name in ("integrations", "notify_settings"):
            for row in self.rows.get(name, []):
                json_value(row["config"], dict)
        emails = [r["email"].strip().casefold() for r in self.rows.get("contacts", []) if r["email"].strip()]
        self.duplicate_emails = sum(count > 1 for count in Counter(emails).values())

    def report(self):
        return {"version": VERSION, "mode": "read-only", "source_sha256": self.fingerprint,
                "table_counts": {k: len(v) for k, v in self.rows.items()},
                "absent_optional_tables": self.missing_tables, "media_files": len(self.files),
                "media_bytes": sum(f["size"] for f in self.files.values()),
                "duplicate_contact_email_groups": self.duplicate_emails,
                "credentials_exported": False, "provider_calls": 0}

    def transformed(self, source_key=None, target_key=None):
        require(bool(source_key) == bool(target_key), "BOTH_KEYS_REQUIRED")
        result = {k: [dict(row) for row in v] for k, v in self.rows.items()}
        for name, rows in result.items():
            for row in rows:
                if name in ("integrations", "notify_settings"):
                    if row["secrets"] and source_key:
                        try:
                            data = json_value(cipher(source_key).decrypt(row["secrets"].encode()), dict)
                            data.pop("oauth_state", None)
                            row["secrets"] = cipher(target_key).encrypt(json.dumps(data).encode()).decode()
                        except Exception:
                            raise ImportRefused("CREDENTIAL_DECRYPTION_FAILED") from None
                    else:
                        row["secrets"] = ""
                    if name == "integrations":
                        row["enabled"] = False
                        if row["last_status"] == "running":
                            row["last_status"] = "error"
                            row["last_error"] = "Migration hold: review interrupted sync before enabling."
                    else:
                        cfg = json_value(row["config"], dict)
                        cfg.update(enabled=False, push_enabled=False, twilio_enabled=False, email_enabled=False)
                        row["config"] = json.dumps(cfg)
                if name == "publish_jobs" and row["status"] in ("scheduled", "posting"):
                    row["status"] = "canceled"
                if name == "publish_targets" and row["status"] in ("pending", "posting", "processing"):
                    row["status"] = "canceled"
                    row["error"] = "Migration hold: check remote publication status before creating another job."
                if name == "posts" and row["status"] == "scheduled":
                    row["status"] = "draft"
                if name == "media_files":
                    row["token"] = secrets.token_urlsafe(32)
        result["crm_projections"] = [dict(
            contact_id=row["id"], source_key=str(uuid.uuid5(NAMESPACE, f'{self.fingerprint}:{row["id"]}')),
            crm_id="", payload=json.dumps({"FirstName": row["first_name"],
                "LastName": row["last_name"] or row["first_name"] or "Contact", "Email__c": row["email"],
                "Phone__c": row["phone"], "company": row["company"]}),
            pending=False, deleted=False, error="Migration review required before CRM projection.")
            for row in result.get("contacts", [])]
        return result


def safe_schema(schema):
    require(re.fullmatch(SCHEMA_PATTERN, schema) is not None, "REHEARSAL_SCHEMA_REQUIRED")
    return schema


@contextmanager
def transaction(engine, schema):
    safe_schema(schema)
    require(engine.dialect.name == "postgresql", "POSTGRESQL_TARGET_REQUIRED")
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        lock = int.from_bytes(hashlib.sha256(schema.encode()).digest()[:8], "big", signed=True)
        require(conn.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": lock}), "IMPORT_BUSY")
        yield conn.execution_options(schema_translate_map={None: schema})


def row_digest(conn, table):
    h = hashlib.sha256()
    count = 0
    for row in conn.execute(select(table).order_by(*table.primary_key.columns)).mappings():
        h.update(json.dumps(dict(row), sort_keys=True, default=str, ensure_ascii=True).encode() + b"\n")
        count += 1
    return {"count": count, "sha256": h.hexdigest()}


def apply(snapshot, engine, schema, target_media, *, source_key=None, target_key=None):
    """Create-only: replay refuses the existing target. Reconcile it instead."""
    safe_schema(schema)
    target_media = Path(target_media).absolute()
    require(not target_media.exists() and not target_media.is_symlink(), "TARGET_MEDIA_MUST_NOT_EXIST")
    require(target_media.parent.resolve() == target_media.parent, "TARGET_MEDIA_PARENT_MUST_BE_CANONICAL")
    rows = snapshot.transformed(source_key, target_key)
    run_id = str(uuid.uuid4())
    # If a process or connection dies during COMMIT, leave the private directory
    # for reconciliation. Never guess that an uncertain commit rolled back.
    with transaction(engine, schema) as conn:
        require(not inspect(conn).has_schema(schema), "TARGET_SCHEMA_ALREADY_EXISTS")
        conn.execute(CreateSchema(schema))
        Base.metadata.create_all(conn)
        target_media.mkdir(mode=0o700)
        journal = dict(snapshot.report(), mode="rehearsal", schema=schema, run_id=run_id,
                       credential_policy="reencrypt" if source_key else "reconnect",
                       media_directory=str(target_media), files=snapshot.files)
        marker = target_media / MARKER
        with open(marker, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as f:
            json.dump(journal, f)
            f.flush(); os.fsync(f.fileno())
        for name, expected in snapshot.files.items():
            source = media_path(snapshot.media_dir, name)
            with source.open("rb") as src, open(target_media / name, "xb", opener=lambda p, flags: os.open(p, flags, 0o600)) as dest:
                h = hashlib.sha256()
                size = 0
                while chunk := src.read(1024 * 1024):
                    h.update(chunk); size += len(chunk); dest.write(chunk)
                dest.flush(); os.fsync(dest.fileno())
            require({"size": size, "sha256": h.hexdigest()} == expected, "SOURCE_MEDIA_CHANGED")
        for table in Base.metadata.sorted_tables:
            values = rows.get(table.name, [])
            for offset in range(0, len(values), 500):
                conn.execute(table.insert(), values[offset:offset + 500])
            if "id" in table.c:
                seq = conn.scalar(text("SELECT pg_get_serial_sequence(:table, 'id')"), {"table": f'{schema}.{table.name}'})
                if seq:
                    maximum = max((r["id"] for r in values), default=0)
                    conn.execute(text("SELECT setval(CAST(:seq AS regclass), :value, :called)"),
                                 {"seq": seq, "value": max(1, maximum), "called": bool(maximum)})
        require(digest_file(snapshot.path) == snapshot.fingerprint, "SOURCE_CHANGED_DURING_IMPORT")
        journal["target_tables"] = {t.name: row_digest(conn, t) for t in Base.metadata.sorted_tables}
        require(all(journal["target_tables"][k]["count"] == len(v) for k, v in rows.items()), "RECONCILIATION_FAILED")
        journal["held_rows"] = {name: [{"id": r["id"], "status": r["status"]} for r in snapshot.rows.get(name, [])
                                     if r["status"] in ("scheduled", "posting", "pending", "processing")]
                                for name in ("posts", "publish_jobs", "publish_targets")}
        conn.execute(text(f'CREATE TABLE "{schema}"._fh_import (run_id text PRIMARY KEY, journal jsonb NOT NULL)'))
        conn.execute(text(f'INSERT INTO "{schema}"._fh_import VALUES (:id, CAST(:journal AS jsonb))'),
                     {"id": run_id, "journal": json.dumps(journal)})
    return {**snapshot.report(), "mode": "imported-held", "schema": schema, "run_id": run_id,
            "credential_policy": journal["credential_policy"], "reconciled": True}


def _verify(conn, schema, run_id, target_media):
    require(inspect(conn).has_schema(schema), "TARGET_SCHEMA_NOT_FOUND")
    require(set(inspect(conn).get_table_names(schema=schema)) == set(Base.metadata.tables) | {"_fh_import"},
            "TARGET_SCHEMA_CHANGED")
    journals = conn.execute(text(f'SELECT journal FROM "{schema}"._fh_import WHERE run_id=:id'), {"id": run_id}).scalars().all()
    require(len(journals) == 1, "RUN_ID_MISMATCH")
    journal = journals[0]
    require(journal["version"] == VERSION and journal["schema"] == schema, "IMPORT_VERSION_MISMATCH")
    require(str(target_media) == journal["media_directory"] and not target_media.is_symlink(), "TARGET_MEDIA_MISMATCH")
    require(json_value(private_value(target_media / MARKER), dict)["run_id"] == run_id, "MEDIA_MARKER_MISMATCH")
    require({p.name for p in target_media.iterdir()} == set(journal["files"]) | {MARKER}, "TARGET_MEDIA_CHANGED")
    for name, expected in journal["files"].items():
        path = media_path(target_media, name)
        require(path.stat().st_size == expected["size"] and digest_file(path) == expected["sha256"], "TARGET_MEDIA_CHANGED")
    for table in Base.metadata.sorted_tables:
        # Keep concurrent app writes out until reconciliation/rollback finishes.
        conn.execute(text(f'LOCK TABLE "{schema}"."{table.name}" IN SHARE MODE'))
        require({c["name"] for c in inspect(conn).get_columns(table.name, schema=schema)} == set(table.c.keys()),
                "TARGET_SCHEMA_CHANGED")
        require(row_digest(conn, table) == journal["target_tables"][table.name], "TARGET_DATA_CHANGED")
    return journal


def verify(engine, schema, run_id, target_media, *, rollback=False):
    target_media = Path(target_media).absolute()
    with transaction(engine, schema) as conn:
        journal = _verify(conn, schema, run_id, target_media)
        if rollback:
            # RESTRICT throughout: never cascade into another schema if someone
            # has attached a new FK/view to this rehearsal since the import.
            Base.metadata.drop_all(conn)
            conn.execute(text(f'DROP TABLE "{schema}"._fh_import'))
            conn.execute(DropSchema(schema))
    if rollback:
        # Only remove the files recorded in this run after confirmed DB commit.
        for name in journal["files"]:
            (target_media / name).unlink()
        (target_media / MARKER).unlink()
        target_media.rmdir()
    return {"mode": "rolled-back" if rollback else "verified", "run_id": run_id,
            "schema": schema, "reconciled": True, "provider_calls": 0}
