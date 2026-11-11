"""Bounded CRM routes, protected by the same login as marketing workflows."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import crm_bridge as bridge
from ..database import get_db
from ..deps import current_user

router = APIRouter(prefix="/api/crm", tags=["CRM"], dependencies=[Depends(current_user)])


class AccountIn(BaseModel):
    Name: str = Field(min_length=1, max_length=255)
    Compat_Text__c: str | None = Field(default=None, max_length=80)


def record_id(value):
    if len(value) != 18 or not value.isascii() or not value.isalnum():
        raise HTTPException(422, "Invalid CRM record ID")
    return value


@router.get("/status")
def status(db: Session = Depends(get_db)):
    rows = db.scalars(select(bridge.CRMProjection).where(bridge.CRMProjection.pending.is_(True))
                      .order_by(bridge.CRMProjection.contact_id).limit(50)).all()
    total = db.scalar(select(func.count()).select_from(bridge.CRMProjection)
                      .where(bridge.CRMProjection.pending.is_(True))) or 0
    return {"configured": bridge.configured(), "pending": total,
            "errors": [{"contact_id": r.contact_id, "error": r.error} for r in rows if r.error],
            "mode": "Single-owner workspace; FunnelHub owns projected contact edits"}


@router.post("/sync")
def sync():
    if not bridge.configured():
        raise HTTPException(503, "CRM engine is not configured")
    return bridge.sync_pending()


@router.get("/accounts")
def accounts():
    return bridge.request("GET", "query", params={"q": "SELECT Id,Name,Compat_Text__c FROM Account ORDER BY Name LIMIT 2000"})


@router.post("/accounts", status_code=201)
def create_account(data: AccountIn):
    return bridge.request("POST", "sobjects/Account", data=data.model_dump())


@router.patch("/accounts/{account_id}", status_code=204)
def update_account(account_id: str, data: AccountIn):
    bridge.request("PATCH", f"sobjects/Account/{record_id(account_id)}", data=data.model_dump())


@router.get("/contacts")
def contacts():
    return bridge.request("GET", "query", params={"q": "SELECT Id,FirstName,LastName,AccountId,Email__c,Phone__c FROM Contact ORDER BY LastName LIMIT 2000"})
