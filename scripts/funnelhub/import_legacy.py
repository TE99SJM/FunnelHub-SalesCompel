#!/usr/bin/env python3
"""Offline rehearsal CLI. No production target, cutover, or automatic activation."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["assess", "apply", "verify", "rollback"])
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--source-media", type=Path)
    parser.add_argument("--schema")
    parser.add_argument("--target-media", type=Path)
    parser.add_argument("--dsn-file", type=Path, help="Private 0600 file containing the PostgreSQL SQLAlchemy URL")
    parser.add_argument("--source-key-file", type=Path)
    parser.add_argument("--target-key-file", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--disposable-target", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="fh-offline-import-") as tmp:
        # ORM imports may initialize Settings; isolate it from both installations.
        os.environ.update(DATA_DIR=tmp, DATABASE_URL="sqlite://", SECRET_KEY="offline-model-import-unused")
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "modules/funnelhub/backend"))
        from app.legacy_import import Snapshot, apply, verify, private_value, require, ImportRefused
        from sqlalchemy import create_engine
        engine = None
        try:
            if args.action in ("assess", "apply"):
                require(args.snapshot is not None and args.source_media is not None, "SOURCE_ARGUMENTS_REQUIRED")
                snapshot = Snapshot(args.snapshot, args.source_media)
            if args.action == "assess":
                result = snapshot.report()
            else:
                require(args.schema and args.target_media and args.dsn_file, "TARGET_ARGUMENTS_REQUIRED")
                require(args.action == "verify" or args.disposable_target, "DISPOSABLE_TARGET_ACK_REQUIRED")
                engine = create_engine(private_value(args.dsn_file), hide_parameters=True, echo=False)
                if args.action == "apply":
                    require(bool(args.source_key_file) == bool(args.target_key_file), "BOTH_KEYS_REQUIRED")
                    result = apply(snapshot, engine, args.schema, args.target_media,
                                   source_key=private_value(args.source_key_file) if args.source_key_file else None,
                                   target_key=private_value(args.target_key_file) if args.target_key_file else None)
                else:
                    require(bool(args.run_id), "RUN_ID_REQUIRED")
                    result = verify(engine, args.schema, args.run_id, args.target_media, rollback=args.action == "rollback")
            print(json.dumps(result, indent=2))
            return 0
        except ImportRefused as exc:
            print(json.dumps({"status": "refused", "code": str(exc)}))
            return 2
        except Exception:
            # DB/driver exceptions often embed statement parameters or private rows.
            print(json.dumps({"status": "failed", "code": "OFFLINE_IMPORT_FAILED",
                              "action": "Keep any private staging files; inspect target state before retry."}))
            return 1
        finally:
            if engine is not None:
                engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
