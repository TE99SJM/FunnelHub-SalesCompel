import io
from datetime import timedelta

from PIL import Image
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import MediaFile, utcnow
from app.publishing import media, runner


def png():
    f = io.BytesIO(); Image.new("RGB", (20,20), "green").save(f, "PNG"); return f.getvalue()


def upload(client):
    r = client.post("/api/publish/media", files={"files": ("photo.png", png(), "image/png")})
    assert r.status_code == 201
    return r.json()[0]


def test_upload_auth_and_empty_rejection(client, auth):
    client.headers.pop("Authorization")
    assert client.post("/api/publish/media", files={"files": ("photo.png",png(),"image/png")}).status_code == 401


def test_atomic_upload_cleanup_and_limits(auth, monkeypatch):
    before = set(media.media_dir().iterdir())
    r = auth.post("/api/publish/media", files=[("files",("good.png",png(),"image/png")),("files",("empty.mov",b"","video/quicktime"))])
    assert r.status_code == 422
    assert set(media.media_dir().iterdir()) == before
    assert auth.get("/api/publish/media").json() == []
    monkeypatch.setattr(settings,"max_upload_bytes",5)
    assert auth.post("/api/publish/media", files={"files":("big.mp4",b"123456","video/mp4")}).status_code == 422
    assert set(media.media_dir().iterdir()) == before


def test_drafts_survive_sessions_protect_media_and_never_publish(auth, monkeypatch):
    monkeypatch.setattr(settings,"external_publish_enabled",False)
    m = upload(auth)
    d = auth.post("/api/drafts",json={"text":"Saved draft", "media_ids":[m["id"]]}).json()
    assert d["media"][0]["id"] == m["id"]
    assert auth.get("/api/drafts").json()[0]["text"] == "Saved draft"
    assert auth.put(f"/api/drafts/{d['id']}",json={"text":"Edited", "media_ids":[m["id"]]}).status_code == 200
    assert auth.delete(f"/api/publish/media/{m['id']}").status_code == 409
    assert auth.get(f"/api/publish/media/{m['id']}/file").content == png()
    monkeypatch.setenv("AUTO_DELETE_MEDIA","true")
    with SessionLocal() as db:
        db.get(MediaFile,m["id"]).created_at = utcnow()-timedelta(days=30);db.commit()
    assert runner.cleanup_media(force=True) == 0
    assert auth.post("/api/publish",json={"text":"Blocked","targets":[{"integration_id":1}]}).status_code == 403
    assert auth.delete(f"/api/drafts/{d['id']}").status_code == 204
    assert auth.delete(f"/api/publish/media/{m['id']}").status_code == 204


def test_media_retained_and_public_route_disabled_by_default(auth, monkeypatch):
    m = upload(auth)
    monkeypatch.setenv("AUTO_DELETE_MEDIA","false")
    monkeypatch.setattr(settings,"public_media_enabled",False)
    assert auth.get(m["url"]).status_code == 404
    assert runner.cleanup_media(force=True) == 0


def test_run_due_cannot_publish_when_disabled(auth, monkeypatch):
    monkeypatch.setattr(settings,"external_publish_enabled",False)
    monkeypatch.setattr(runner,"start",lambda *args: (_ for _ in ()).throw(AssertionError("Published")))
    runner.run_due(); runner.run_job(1)
