#!/usr/bin/env python3
"""Read an operator-supplied SQLite snapshot; report counts only, never secrets.

No import/write mode exists. Run against a consistent exported snapshot, not the
live production volume. Preserve its .secret_key separately in private storage.
"""
import argparse
import json
import sqlite3
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("snapshot", type=Path)
parser.add_argument("--media-dir", type=Path)
args = parser.parse_args()
path = args.snapshot.resolve(strict=True)
db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
db.execute("PRAGMA query_only=ON")
tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
counts = {}
for table in sorted(tables):
    safe = table.replace('"','""')
    counts[table] = db.execute(f'SELECT count(*) FROM "{safe}"').fetchone()[0]
report = {"mode":"read-only assessment", "table_counts":counts,
          "foreign_key_violations":len(db.execute("PRAGMA foreign_key_check").fetchall()),
          "apply_supported":False, "credentials_exported":False}
if "contacts" in tables:
    report["duplicate_nonempty_contact_email_groups"] = db.execute("SELECT count(*) FROM (SELECT lower(trim(email)) FROM contacts WHERE trim(email) != '' GROUP BY lower(trim(email)) HAVING count(*) > 1)").fetchone()[0]
if "integrations" in tables:
    report["encrypted_connections"] = db.execute("SELECT count(*) FROM integrations WHERE secrets != ''").fetchone()[0]
if "media_files" in tables and args.media_dir:
    root=args.media_dir.resolve(strict=True)
    missing=unsafe=0
    for stored,jpeg in db.execute("SELECT stored_name,jpeg_name FROM media_files"):
        for name in [stored,jpeg]:
            if not name: continue
            p=(root/name).resolve()
            if p.parent != root: unsafe+=1
            elif not p.is_file(): missing+=1
    report.update(missing_media_files=missing,unsafe_media_paths=unsafe)
db.close()
print(json.dumps(report,indent=2))
