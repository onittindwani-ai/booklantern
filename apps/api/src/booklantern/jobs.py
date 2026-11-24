"""The background jobs and the little scheduler that keeps them running."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from booklantern import bankservice, collections, forecastservice, fxservice, intake
from booklantern.context import Ctx, set_state
from sendora_core.events import record_event
from sendora_core.jobs import Handler, enqueue

INTERVALS = {"intake": 120, "reminders": 300, "reconcile": 600, "forecast": 3600}


def job_intake(session: Session, ctx: Ctx) -> dict:
    return intake.run_intake(session, ctx)


def job_reminders(session: Session, ctx: Ctx) -> dict:
    collections.update_promises(session, ctx.today(session))
    out = collections.plan_reminders(session, ctx)
    out.update(collections.send_approved(session, ctx))
    return out


def job_reconcile(session: Session, ctx: Ctx) -> dict:
    out = bankservice.run_matching(session, ctx)
    bankservice.record_payments(session)
    return out


def job_forecast(session: Session, ctx: Ctx) -> dict:
    fxservice.flag_missing(session, ctx)
    res = forecastservice.compute(session, ctx)
    forecastservice.save(session, ctx, res)
    set_state(session, "last_forecast_low", str(res["low_point_minor"]))
    return {"low_point_minor": res["low_point_minor"], "closing_minor": res["closing_minor"]}


JOBS = {"intake": job_intake, "reminders": job_reminders, "reconcile": job_reconcile, "forecast": job_forecast}


def make_handlers(ctx: Ctx) -> dict[str, Handler]:
    return {kind: (lambda session, payload, fn=fn: fn(session, ctx)) for kind, fn in JOBS.items()}


def schedule_due(session: Session, ctx: Ctx) -> int:
    from sendora_core.db import utcnow
    from sendora_core.models import Job

    n, now = 0, utcnow()
    for kind, secs in INTERVALS.items():
        last = session.scalars(select(Job).where(Job.kind == kind).order_by(Job.id.desc())).first()
        if last is None:
            enqueue(session, kind); n += 1
        elif last.status in {"done", "failed"} and last.finished_at is not None and (now - last.finished_at.replace(tzinfo=now.tzinfo)).total_seconds() >= secs:
            enqueue(session, kind); n += 1
    return n


def run_cycle(session: Session, ctx: Ctx) -> dict:
    """Everything once, in order. The demo's Run button and the tests use this."""
    out = {"intake": job_intake(session, ctx), "reconcile": job_reconcile(session, ctx), "reminders": job_reminders(session, ctx), "forecast": job_forecast(session, ctx)}
    record_event(session, "cycle.ran", None, None, {"processed": out["intake"]["processed"]})
    return out
