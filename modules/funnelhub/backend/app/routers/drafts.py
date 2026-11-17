"""Durable composer drafts. Saving a draft never contacts a publishing service."""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from ..database import Base, get_db
from ..deps import current_user, get_or_404
from ..models import MediaFile


class ComposerDraft(Base):
    __tablename__ = "composer_drafts"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(1000), default="")
    media_ids: Mapped[str] = mapped_column(Text, default="[]")
    target_ids: Mapped[str] = mapped_column(Text, default="[]")


class DraftIn(BaseModel):
    title: str = Field(default="", max_length=200)
    text: str = Field(default="", max_length=63000)
    link: str = Field(default="", max_length=1000)
    media_ids: list[int] = Field(default_factory=list, max_length=35)
    target_ids: list[int] = Field(default_factory=list, max_length=50)


router = APIRouter(prefix="/api/drafts", tags=["drafts"], dependencies=[Depends(current_user)])


def serialize(row, db):
    from .publish import _media_out
    ids = json.loads(row.media_ids)
    media = {m.id: m for m in db.scalars(select(MediaFile).where(MediaFile.id.in_(ids)))}
    return {"id": row.id, "title": row.title, "text": row.text, "link": row.link,
            "media": [_media_out(media[mid]) for mid in ids if mid in media],
            "target_ids": json.loads(row.target_ids)}


@router.get("")
def drafts(db: Session = Depends(get_db)):
    return [serialize(r, db) for r in db.scalars(select(ComposerDraft).order_by(ComposerDraft.id.desc()))]


def save(row, data, db):
    for mid in data.media_ids:
        get_or_404(db, MediaFile, mid)
    row.title, row.text, row.link = data.title, data.text, data.link
    row.media_ids = json.dumps(list(dict.fromkeys(data.media_ids)))
    row.target_ids = json.dumps(list(dict.fromkeys(data.target_ids)))
    db.add(row)
    db.commit()
    return serialize(row, db)


@router.post("", status_code=201)
def create(data: DraftIn, db: Session = Depends(get_db)):
    return save(ComposerDraft(), data, db)


@router.put("/{draft_id}")
def update(draft_id: int, data: DraftIn, db: Session = Depends(get_db)):
    return save(get_or_404(db, ComposerDraft, draft_id), data, db)


@router.delete("/{draft_id}", status_code=204)
def delete(draft_id: int, db: Session = Depends(get_db)):
    db.delete(get_or_404(db, ComposerDraft, draft_id))
    db.commit()
