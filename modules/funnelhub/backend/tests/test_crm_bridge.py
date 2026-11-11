import json

from fastapi import HTTPException
from sqlalchemy import select

from app import crm_bridge as bridge
from app.database import SessionLocal


def test_adapter_requires_login(client):
    assert client.get("/api/crm/accounts").status_code == 401
    assert client.post("/api/crm/sync").status_code == 401


def test_projection_is_durable_and_retries_without_duplicate(auth, monkeypatch):
    monkeypatch.setattr(bridge, "configured", lambda: True)
    remote, creates = {}, []

    def fake(method, path, *, data=None, params=None):
        if path == "query":
            return {"records": [{"Id": v["id"]} for v in remote.values()]}
        if path.startswith("sobjects/Account"):
            return {"id": "001000000000001AAA"}
        if method == "POST":
            creates.append(data.copy())
            remote[data["FunnelHub_Key__c"]] = {"id": "003000000000001AAA", **data}
            # Simulate remote commit + network disconnect before local mapping.
            if len(creates) == 1:
                raise HTTPException(503, "CRM engine is unavailable")
            return {"id": "003000000000001AAA"}
        return None

    monkeypatch.setattr(bridge, "request", fake)
    c = auth.post("/api/contacts", json={"first_name": "Ada", "email": "ada@example.com", "company": "Workshop"}).json()
    assert auth.post("/api/crm/sync").json() == {"synced": 0, "failed": 1}
    assert auth.get("/api/crm/status").json()["pending"] == 1
    assert auth.post("/api/crm/sync").json() == {"synced": 1, "failed": 0}
    assert len(creates) == 1
    with SessionLocal() as db:
        row = db.get(bridge.CRMProjection, c["id"])
        assert row.crm_id == "003000000000001AAA" and not row.pending
    auth.patch(f"/api/contacts/{c['id']}", json={"last_name": "Updated"})
    assert auth.get("/api/crm/status").json()["pending"] == 1
    assert auth.post("/api/crm/sync").json()["synced"] == 1
    assert auth.delete(f"/api/contacts/{c['id']}").status_code == 204
    assert auth.post("/api/crm/sync").json()["synced"] == 1
    with SessionLocal() as db:
        assert db.get(bridge.CRMProjection, c["id"]).deleted


def test_projection_conflict_is_visible(auth, monkeypatch):
    monkeypatch.setattr(bridge, "configured", lambda: True)
    monkeypatch.setattr(bridge, "request", lambda *a, **k: {"records": [{"Id": "a"}, {"Id": "b"}]})
    auth.post("/api/contacts", json={"first_name": "Conflict"})
    assert auth.post("/api/crm/sync").json()["failed"] == 1
    assert "manual reconciliation" in auth.get("/api/crm/status").json()["errors"][0]["error"]


def test_contact_and_projection_rollback_together(auth):
    from app.models import Contact
    with SessionLocal() as db:
        c = Contact(first_name="Uncommitted")
        db.add(c); db.flush()
        cid = c.id
        db.rollback()
    with SessionLocal() as db:
        assert db.get(bridge.CRMProjection, cid) is None


def test_missing_engine_returns_clear_status(auth, monkeypatch):
    monkeypatch.delenv("SALESCOMPEL_URL", raising=False)
    assert auth.get("/api/crm/accounts").status_code == 503
    assert auth.get("/api/crm/status").json()["configured"] is False


def test_account_adapter_is_bounded(auth, monkeypatch):
    calls = []
    monkeypatch.setattr(bridge, "request", lambda method, path, **kwargs: calls.append((method,path,kwargs)) or {"id":"001000000000001AAA"})
    assert auth.post("/api/crm/accounts", json={"Name":"Example"}).status_code == 201
    assert calls[-1][1] == "sobjects/Account"
    assert auth.patch("/api/crm/accounts/not-an-id", json={"Name":"Changed"}).status_code == 422


def test_square_customer_projection_preserves_relationships(auth, monkeypatch):
    from app.models import Contact, Email
    with SessionLocal() as db:
        c = Contact(first_name="Customer", external_source="square", external_id="fixture-customer")
        db.add(c); db.flush()
        e = Email(account="test@example.com", gm_msgid="42", contact_id=c.id)
        db.add(e); db.commit()
        cid = c.id
    with SessionLocal() as db:
        assert db.get(bridge.CRMProjection, cid).pending
        assert db.scalar(select(Email.contact_id)) == cid
