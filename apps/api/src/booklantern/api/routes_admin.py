from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from booklantern import collections, fx as FX, fxservice
from booklantern.api.deps import db, get_ctx, owner, writer
from booklantern.api.serializers import iso
from booklantern.context import Ctx, set_state
from booklantern.models import Reminder
from booklantern.registry import CATEGORIES, ENV_VARS
from sendora_core.approvals import ApprovalError, decide
from sendora_core.audit import record_audit, verify_audit_chain
from sendora_core.models import Approval, AuditEntry

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/approvals", summary="Pending and recent approvals")
def approvals(s: Session = Depends(db, scope="function")):
    rows = list(s.scalars(select(Approval).order_by(Approval.id.desc()).limit(100)))
    return [{"id": a.id, "action": a.action, "summary": a.summary, "risk": a.risk, "status": a.status, "requested_by": a.requested_by, "decided_by": a.decided_by, "note": a.decision_note, "created_at": iso(a.created_at), "payload": a.payload} for a in rows]


class DecideIn(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=500)


@router.post("/approvals/{approval_id}/decide", summary="Approve or reject")
def decide_approval(approval_id: int, body: DecideIn, s: Session = Depends(db, scope="function"), u: dict = Depends(writer)):
    existing = s.get(Approval, approval_id)
    if existing is not None and existing.requested_by == u["user"]:
        raise HTTPException(409, "The person who asked for this cannot decide it. Ask someone else.")
    try:
        a = decide(s, approval_id, body.approve, u["user"], u["role"], body.note or None)
    except ApprovalError as exc:
        raise HTTPException(409, str(exc)) from exc
    if a.action == "reminder.send" and a.payload.get("reminder_id"):
        r = s.get(Reminder, int(a.payload["reminder_id"]))
        if r and body.approve and r.status == "drafted":
            collections.approve_reminder(s, r.id, u["user"])
        elif r and not body.approve and r.status == "drafted":
            r.status, r.cancel_reason = "cancelled", "rejected by a person"
    return {"status": a.status}


@router.get("/audit", summary="Audit log, newest first")
def audit(limit: int = Query(100, ge=1, le=1000), s: Session = Depends(db, scope="function")):
    return [{"id": e.id, "actor": e.actor, "action": e.action, "target": e.target, "detail": e.detail, "at": e.created_at} for e in s.scalars(select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit))]


@router.get("/audit/verify", summary="Check the audit chain has not been edited")
def audit_verify(s: Session = Depends(db, scope="function")):
    ok, bad = verify_audit_chain(s)
    return {"ok": ok, "first_bad_id": bad}


@router.get("/integrations", summary="Every adapter, which one is selected, and what it needs")
def integrations(ctx: Ctx = Depends(get_ctx)):
    st = ctx.settings
    chosen = {c: getattr(st, f"{c}_adapter") for c in CATEGORIES}
    out = []
    for row in ctx.registry.describe():
        env = ENV_VARS.get((row["category"], row["name"]), [])
        out.append({**row, "selected": chosen.get(row["category"]) == row["name"], "env_vars": env, "configured": all(bool(getattr(st, v.lower(), "")) for v in env) if env else True})
    return {"categories": list(CATEGORIES), "adapters": out, "demo_mode": st.demo_shortcuts}


@router.post("/integrations/{category}/test", summary="Test the selected adapter in a category")
def test_integration(category: str, ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    if category not in CATEGORIES:
        raise HTTPException(404, "Unknown category.")
    ok, detail = getattr(ctx.adapters, category).healthcheck()
    return {"category": category, "ok": ok, "detail": detail}


@router.get("/settings", summary="Mode, kill switch and config problems")
def get_settings(s: Session = Depends(db, scope="function"), ctx: Ctx = Depends(get_ctx)):
    eff = ctx.effective(s)
    st = ctx.settings
    return {"mode": st.mode.value, "effective_mode": eff.mode.value, "kill_switch": eff.kill_switch, "demo_mode": st.demo_shortcuts, "problems": st.problems(), "accounting_write": st.accounting_write,
            "company": st.company_name, "currency": st.base_currency, "window": f"{st.reminder_window_start:02d}:00 to {st.reminder_window_end:02d}:00 customer local time, weekdays",
            "llm": "live (UNVERIFIED)" if st.effective_llm_backend.value == "anthropic" else "offline stand in", "extractor": "offline rules (not a language model)" if st.extractor == "offline" else "live model (UNVERIFIED)",
            "collection_prob_bp": st.probs()}


class SettingsIn(BaseModel):
    kill_switch: bool | None = None
    force_draft: bool | None = None


@router.post("/settings", summary="Turn the kill switch or draft mode on or off (owner only). The app can never switch live mode on.")
def post_settings(body: SettingsIn, s: Session = Depends(db, scope="function"), ctx: Ctx = Depends(get_ctx), u: dict = Depends(owner)):
    if body.kill_switch is not None:
        set_state(s, "kill_switch", "1" if body.kill_switch else "0")
        record_audit(s, u["user"], "settings.kill_switch", None, {"on": body.kill_switch})
    if body.force_draft is not None:
        set_state(s, "force_draft", "1" if body.force_draft else "0")
        record_audit(s, u["user"], "settings.force_draft", None, {"on": body.force_draft})
    s.flush()
    return get_settings(s, ctx)


class FxRateIn(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    rate_date: date
    rate: str = Field(min_length=1, max_length=20)
    note: str = Field(default="", max_length=160)


@router.get("/fx-rates", summary="Manual exchange rates, newest first for each currency")
def fx_rates(s: Session = Depends(db, scope="function"), ctx: Ctx = Depends(get_ctx)):
    return {"base": ctx.settings.base_currency, "rates": fxservice.list_rates(s), "today": ctx.today(s).isoformat()}


@router.post("/fx-rates", summary="Add a manual exchange rate (company currency for one unit of the other currency), or correct the one for the same day")
def set_fx_rate(body: FxRateIn, s: Session = Depends(db, scope="function"), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    try:
        return fxservice.set_rate(s, ctx, body.currency, body.rate_date, body.rate, body.note, u["user"])
    except FX.FxError as exc:
        raise HTTPException(422, str(exc)) from exc
