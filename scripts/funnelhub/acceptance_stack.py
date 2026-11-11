#!/usr/bin/env python3
"""Exercise a NEW, empty local test Compose stack; refuse initialized systems."""
import argparse
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import httpx
from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:3051")
parser.add_argument("--disposable-test-stack", action="store_true", required=True)
parser.add_argument("--browser-script", type=Path)
parser.add_argument("--restart", action="store_true")
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
if not args.url.startswith("http://127.0.0.1:"):
    raise SystemExit("Only a disposable loopback test stack is supported")
checks = []
args.out.parent.mkdir(parents=True,exist_ok=True)


def check(name, condition):
    if not condition: raise AssertionError(name)
    checks.append(name); print("PASS",name,flush=True)


with httpx.Client(base_url=args.url,trust_env=False,timeout=30) as c:
    check("empty test stack", c.get("/api/auth/status").json()["needs_setup"])
    owner={"email":"ci-owner@example.invalid","name":"CI Owner","password":secrets.token_urlsafe(24)}
    r=c.post("/api/auth/setup",json=owner); check("owner setup",r.status_code==201)
    c.headers["Authorization"]="Bearer "+r.json()["access_token"]
    caps=c.get("/api/capabilities").json()
    check("external actions disabled",not caps["publishing"] and not caps["public_media"])
    account=c.post("/api/crm/accounts",json={"Name":"CI persistent account"})
    check("SalesCompel account create",account.status_code==201)
    aid=account.json()["id"]
    check("SalesCompel account edit",c.patch(f"/api/crm/accounts/{aid}",json={"Name":"CI edited account"}).status_code==204)
    contact=c.post("/api/contacts",json={"first_name":"CI", "last_name":"Contact","company":"CI company"})
    check("contact create",contact.status_code==201)
    for _ in range(20):
        c.post("/api/crm/sync")
        if c.get("/api/crm/status").json()["pending"]==0: break
        time.sleep(.2)
    contacts=c.get("/api/crm/contacts").json()["records"]
    check("shared CRM contact/account",len(contacts)==1 and bool(contacts[0]["AccountId"]))
    raw=io.BytesIO();Image.new("RGB",(30,30),"green").save(raw,"PNG")
    upload=c.post("/api/publish/media",files={"files":("ci.png",raw.getvalue(),"image/png")})
    check("persistent multipart upload",upload.status_code==201)
    mid=upload.json()[0]["id"]
    draft=c.post("/api/drafts",json={"text":"CI persistent draft","media_ids":[mid]})
    check("draft save",draft.status_code==201)
    did=draft.json()["id"]
    if args.browser_script:
        env=dict(os.environ,FH_TEST_URL=args.url,FH_TEST_EMAIL=owner["email"],FH_TEST_PASSWORD=owner["password"],FH_BROWSER_OUT=str(args.out.parent))
        subprocess.run(["node",str(args.browser_script)],env=env,check=True)
        check("desktop and iPhone WebKit browsers",True)
    if args.restart:
        subprocess.run(["docker","compose","-p","funnelhub-salescompel-test","-f","compose.test.yml","restart","app","db"],check=True)
        for _ in range(100):
            try:
                if c.get("/api/health").status_code==200: break
            except httpx.HTTPError: pass
            time.sleep(.5)
        check("login survives restart",c.get("/api/auth/me").status_code==200)
        check("CRM survives restart",any(a["Id"]==aid and a["Name"]=="CI edited account" for a in c.get("/api/crm/accounts").json()["records"]))
        check("draft survives restart",any(d["id"]==did for d in c.get("/api/drafts").json()))
        check("media survives restart",c.get(f"/api/publish/media/{mid}/file").content==raw.getvalue())
args.out.write_text(json.dumps({"status":"passed","checks":checks,"live_providers_tested":False,"physical_iphone_tested":False},indent=2))
