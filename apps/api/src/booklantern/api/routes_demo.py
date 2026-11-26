"""Demo mode only. These routes return 404 when DEMO_MODE is off."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from booklantern import clock, demo
from booklantern.api.deps import db, demo_only, get_ctx, owner, writer
from booklantern.context import Ctx
from booklantern.jobs import run_cycle

router = APIRouter(prefix="/api/demo", tags=["demo"], dependencies=[Depends(demo_only)])


@router.get("/state", summary="The demo clock")
def state(s: Session = Depends(db, scope="function"), ctx: Ctx = Depends(get_ctx)):
    return {"now": ctx.now(s).isoformat()}


@router.post("/reset", summary="Reset to the seed data and a fresh clock")
def reset(s: Session = Depends(db, scope="function"), ctx: Ctx = Depends(get_ctx), u: dict = Depends(owner)):
    try:
        return demo.reset(s, ctx)
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/tick", summary="Run every job once, now")
def tick(s: Session = Depends(db, scope="function"), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    return run_cycle(s, ctx)


class AdvanceIn(BaseModel):
    hours: float = Field(ge=0, le=24 * 30)


@router.post("/advance", summary="Move the demo clock forward")
def advance(b: AdvanceIn, s: Session = Depends(db, scope="function"), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    return {"now": clock.advance(s, b.hours).isoformat()}


class StressIn(BaseModel):
    n: int = Field(ge=1, le=20000)


@router.post("/stress-bank", summary="Add many sample bank lines, to check that long tables stay fast")
def stress(b: StressIn, s: Session = Depends(db, scope="function"), ctx: Ctx = Depends(get_ctx), u: dict = Depends(owner)):
    from booklantern.models import BankAccount, BankTransaction

    acct = s.query(BankAccount).first()
    start = ctx.today(s) - timedelta(days=400)
    s.bulk_insert_mappings(BankTransaction, [{"bank_account_id": acct.id, "ref": f"S{i:05d}", "posted_on": start + timedelta(days=i % 400), "description": f"STRESS ROW {i}", "amount_minor": ((i * 7919) % 90000) - 45000,
                                              "currency": "USD", "status": "ignored", "row_hash": f"stress{i}", "batch": "stress"} for i in range(b.n)])
    return {"added": b.n}
