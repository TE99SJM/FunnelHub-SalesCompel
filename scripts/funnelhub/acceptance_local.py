#!/usr/bin/env python3
"""Reproducible disposable PostgreSQL + Go + Python smoke/restart acceptance.

Requires PostgreSQL 17 binaries, a built SalesCompel executable, this module's
Python requirements, and a built frontend. Never connects to mserver or providers.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("--postgres-bin", type=Path, required=True)
parser.add_argument("--salescompel-bin", type=Path, required=True)
parser.add_argument("--go-bin", type=Path)
parser.add_argument("--browser-script", type=Path)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
checks = []
processes = []


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]


def passed(name):
    checks.append({"check": name, "status": "passed"}); print("PASS", name, flush=True)


def wait_http(url):
    for _ in range(100):
        try:
            if httpx.get(url, trust_env=False, timeout=1).status_code == 200: return
        except httpx.HTTPError: pass
        time.sleep(.1)
    raise AssertionError("Service did not become healthy")


with tempfile.TemporaryDirectory(prefix="funnelhub-acceptance-") as tmp:
    temp = Path(tmp)
    logfile = (temp / "runtime.log").open("w")
    env = dict(os.environ)
    pgport, crmport, appport = port(), port(), port()
    pgdata = temp / "postgres"
    try:
        subprocess.run([str(args.postgres_bin / "initdb"), "-D", str(pgdata), "-A", "trust", "--locale=en_US.UTF-8", "--encoding=UTF8"], check=True, stdout=logfile, stderr=logfile)
        pg = subprocess.Popen([str(args.postgres_bin / "postgres"), "-D", str(pgdata), "-h", "127.0.0.1", "-p", str(pgport), "-c", "unix_socket_directories="], stdout=logfile, stderr=logfile)
        processes.append(pg)
        admin = f"postgresql://{os.getenv('USER', 'agent')}@127.0.0.1:{pgport}/postgres?sslmode=disable"
        for _ in range(100):
            try:
                with psycopg.connect(admin, autocommit=True) as c:
                    c.execute("CREATE DATABASE fh_integration")
                break
            except psycopg.OperationalError: time.sleep(.1)
        else: raise AssertionError("PostgreSQL did not start")
        env.update({k: secrets.token_hex(32) for k in ["RECORDS_PASSWORD", "IDENTITY_PASSWORD", "MARKETING_PASSWORD", "SALESCOMPEL_TOKEN", "SECRET_KEY"]})
        env.update(MIGRATION_DATABASE_URL=admin.replace("/postgres?", "/fh_integration?"),
                   SALESCOMPEL_TENANT="funnelhub", SALESCOMPEL_USER="funnelhub-owner", SALESCOMPEL_ROLE="admin",
                   SALESCOMPEL_BINARY=str(args.salescompel_bin))
        subprocess.run([sys.executable, str(ROOT / "deploy/bootstrap.py")], env=env, check=True, stdout=logfile, stderr=logfile)
        subprocess.run([sys.executable, str(ROOT / "deploy/bootstrap.py")], env=env, check=True, stdout=logfile, stderr=logfile)
        passed("PostgreSQL initialization and repeat initialization")
        if args.go_bin:
            with psycopg.connect(admin, autocommit=True) as c:
                c.execute("CREATE DATABASE sc_baseline")
                c.execute("CREATE ROLE sc_records_login LOGIN IN ROLE salescompel_records")
                c.execute("CREATE ROLE sc_identity_login LOGIN IN ROLE salescompel_identity")
            test_env = dict(env, TEST_DATABASE_URL=admin.replace("/postgres?", "/sc_baseline?"),
                            TEST_RECORDS_URL=f"postgresql://sc_records_login@127.0.0.1:{pgport}/sc_baseline?sslmode=disable",
                            TEST_IDENTITY_URL=f"postgresql://sc_identity_login@127.0.0.1:{pgport}/sc_baseline?sslmode=disable")
            result = subprocess.run([str(args.go_bin), "test", "-p", "1", "-json", "./..."], env=test_env, cwd=ROOT, capture_output=True, text=True)
            events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
            summary = {key: sum(e.get("Action") == key and "Test" in e for e in events) for key in ("pass", "fail", "skip")}
            checks.append({"check": "upstream Go tests", "status": "passed" if result.returncode == 0 else "failed", **summary})
            if result.returncode:
                # Only test output with synthetic data, no deployment secrets.
                (args.out.parent / "go-test-failures.txt").write_text("".join(e.get("Output", "") for e in events if e.get("Action") == "output"))
                raise AssertionError("Upstream Go tests failed; see go-test-failures.txt")
            print("PASS upstream Go tests", summary, flush=True)
        crm_env = dict(env, DATABASE_URL=f"postgresql://fh_records:{env['RECORDS_PASSWORD']}@127.0.0.1:{pgport}/fh_integration?sslmode=disable",
                       AUTH_DATABASE_URL=f"postgresql://fh_identity:{env['IDENTITY_PASSWORD']}@127.0.0.1:{pgport}/fh_integration?sslmode=disable")
        app_env = dict(env, DATABASE_URL=f"postgresql+psycopg://fh_marketing:{env['MARKETING_PASSWORD']}@127.0.0.1:{pgport}/fh_integration",
                       SALESCOMPEL_URL=f"http://127.0.0.1:{crmport}", DATA_DIR=str(temp / "media"),
                       FRONTEND_DIST=str(ROOT / "modules/funnelhub/frontend/dist"), SYNC_SCHEDULER="false",
                       EXTERNAL_PUBLISH_ENABLED="false", PUBLIC_MEDIA_ENABLED="false", ALLOW_DEMO_SEED="false")

        def start_apps():
            crm = subprocess.Popen([str(args.salescompel_bin), "serve", "--addr", f"127.0.0.1:{crmport}", "--assets", ""], env=crm_env, stdout=logfile, stderr=logfile)
            processes.append(crm)
            wait_http(f"http://127.0.0.1:{crmport}/healthz")
            app = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(appport), "--no-access-log"], cwd=ROOT / "modules/funnelhub/backend", env=app_env, stdout=logfile, stderr=logfile)
            processes.append(app)
            wait_http(f"http://127.0.0.1:{appport}/api/health")
            return crm, app

        crm, app = start_apps()
        passed("App and original SalesCompel engine start with restricted database roles")
        with httpx.Client(base_url=f"http://127.0.0.1:{appport}", trust_env=False, timeout=30) as client:
            assert client.get("/api/crm/accounts").status_code == 401
            owner = {"email": "test-owner@example.invalid", "name": "Test Owner", "password": secrets.token_urlsafe(24)}
            r = client.post("/api/auth/setup", json=owner); assert r.status_code == 201, r.text
            client.headers["Authorization"] = "Bearer " + r.json()["access_token"]
            assert client.post("/api/auth/login", json={"email":owner["email"], "password":owner["password"]}).status_code == 200
            assert client.post("/api/auth/setup", json=owner).status_code == 409
            passed("Owner setup/login, authentication and setup lockout")
            account = client.post("/api/crm/accounts", json={"Name":"Acceptance account"}); assert account.status_code == 201, account.text
            aid = account.json()["id"]
            assert client.patch(f"/api/crm/accounts/{aid}", json={"Name":"Account edited"}).status_code == 204
            r = client.post("/api/contacts", json={"first_name":"Acceptance", "last_name":"Contact", "company":"Test company", "email":"synthetic@example.invalid"}); assert r.status_code == 201, r.text
            cid = r.json()["id"]
            assert client.patch(f"/api/contacts/{cid}", json={"last_name":"Edited"}).status_code == 200
            for _ in range(3):
                client.post("/api/crm/sync")
                status = client.get("/api/crm/status").json()
                if status["pending"] == 0: break
                time.sleep(.2)
            assert status["pending"] == 0, status
            rows = client.get("/api/crm/contacts").json()["records"]
            assert len(rows) == 1 and rows[0]["LastName"] == "Edited" and rows[0]["AccountId"]
            client.post("/api/crm/sync")
            assert len(client.get("/api/crm/contacts").json()["records"]) == 1
            passed("Account CRUD and contact projection with company link and no duplicate retry")
            # Valid synthetic PNG, independent of any user media.
            import io
            from PIL import Image
            image = io.BytesIO(); Image.new("RGB",(30,30),"green").save(image,"PNG")
            r = client.post("/api/publish/media", files={"files":("acceptance.png",image.getvalue(),"image/png")}); assert r.status_code == 201, r.text
            media = r.json()[0]
            draft = client.post("/api/drafts", json={"text":"Persistent acceptance draft", "media_ids":[media["id"]]}).json()
            assert client.get(media["url"]).status_code == 404
            assert client.post("/api/publish", json={"text":"Must not post", "targets":[{"integration_id":1}]}).status_code == 403
            passed("Native multipart media, private delivery and publication gate")
            assert client.get("/api/channels").status_code == 200
            assert client.get("/api/dashboard/site-visitors").json() == []
            passed("Empty social/analytics states use real database, no fabricated metrics")
            if args.browser_script:
                browser_env = dict(env, FH_TEST_URL=f"http://127.0.0.1:{appport}", FH_TEST_EMAIL=owner["email"], FH_TEST_PASSWORD=owner["password"], FH_BROWSER_OUT=str(args.out.parent))
                subprocess.run(["node", str(args.browser_script.resolve())], env=browser_env, check=True)
                passed("Desktop/mobile browser acceptance")
            for p in (app, crm): p.terminate(); p.wait(timeout=15)
            crm, app = start_apps()
            assert client.get("/api/auth/me").status_code == 200
            assert any(r["Id"] == aid and r["Name"] == "Account edited" for r in client.get("/api/crm/accounts").json()["records"])
            assert client.get("/api/contacts").json()["items"][0]["id"] == cid
            assert any(d["id"] == draft["id"] for d in client.get("/api/drafts").json())
            assert client.get(f"/api/publish/media/{media['id']}/file").content == image.getvalue()
            passed("Both processes restart; CRM contacts/accounts, login, drafts and media persist")
    except Exception as exc:
        checks.append({"check":"acceptance", "status":"failed", "error":str(exc)})
        # Redact generated secrets before retaining diagnostic logs.
        logfile.flush()
        log = (temp / "runtime.log").read_text()
        for k,v in env.items():
            if ("PASSWORD" in k or "TOKEN" in k or "SECRET" in k) and v: log = log.replace(v,"[REDACTED]")
        args.out.with_suffix(".log").write_text(log)
        raise
    finally:
        for p in reversed(processes):
            if p.poll() is None:
                p.terminate()
                try: p.wait(timeout=15)
                except subprocess.TimeoutExpired: p.kill(); p.wait()
        args.out.write_text(json.dumps({"checks":checks, "production_accessed":False, "live_providers_tested":False},indent=2))
        logfile.close()
