"""Initialize only this isolated test database. Runtime never receives admin DSN."""
import json
import os
import subprocess

import psycopg
from psycopg import sql


def run(*args):
    result = subprocess.run([os.getenv("SALESCOMPEL_BINARY", "/usr/local/bin/salescompel"), *args],
                            check=True, text=True, capture_output=True)
    return result.stdout


def main():
    dsn = os.environ["MIGRATION_DATABASE_URL"]
    with psycopg.connect(dsn, autocommit=True) as db:
        for role in ("salescompel_owner", "salescompel_records", "salescompel_identity"):
            if not db.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                db.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        for role, password, group in (
            ("fh_records", os.environ["RECORDS_PASSWORD"], "salescompel_records"),
            ("fh_identity", os.environ["IDENTITY_PASSWORD"], "salescompel_identity"),
            ("fh_marketing", os.environ["MARKETING_PASSWORD"], None),
        ):
            if not db.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                db.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(role), sql.Literal(password)))
            if group:
                db.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(role)))
        db.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        db.execute("CREATE SCHEMA IF NOT EXISTS funnelhub AUTHORIZATION fh_marketing")
        db.execute("ALTER ROLE fh_marketing SET search_path TO funnelhub")
    run("migrate", "up")
    run("provision")
    # Add only missing fields, preserving the upstream checksummed migrations.
    catalog = json.loads(run("schema", "inspect", "--tenant", os.environ["SALESCOMPEL_TENANT"]))
    # Schema inspection serializes Go catalog structs; use exact source key names.
    objects = catalog.get("Objects", catalog.get("objects", {}))
    if isinstance(objects, dict):
        contact = objects.get("Contact", {})
    else:
        contact = next((o for o in objects if o.get("Name", o.get("name")) == "Contact"), {})
    fields = contact.get("Fields", contact.get("fields", {}))
    names = set(fields) if isinstance(fields, dict) else {f.get("Name", f.get("name")) for f in fields}
    for name, label, length in (("FunnelHub_Key__c", "FunnelHub source key", 80),
                                 ("Email__c", "Email", 255), ("Phone__c", "Phone", 80)):
        if name not in names:
            run("schema", "field", "create", "--tenant", os.environ["SALESCOMPEL_TENANT"],
                "--object", "Contact", "--name", name, "--label", label, "--type", "Text", "--length", str(length))
    print("Test database initialized; runtime roles and CRM fields ready.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        # Commands contain no credentials, and never print the environment/DSN.
        raise SystemExit("SalesCompel initialization failed: " + exc.stderr.strip())
