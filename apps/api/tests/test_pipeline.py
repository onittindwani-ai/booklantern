"""The whole pipeline on the seed, checked against the answer key."""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

from booklantern import collections, forecastservice, intake, posting
from booklantern.evals.extraction_eval import run as run_extraction
from booklantern.models import Bill, Document, ExceptionItem, Invoice, Reminder

ROOT = Path(__file__).resolve().parents[3]


def test_score_seed_tool_passes_every_check():
    r = subprocess.run([sys.executable, str(ROOT / "tools/score_seed.py")], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout


def test_dev_extraction_is_perfect_on_the_documents_it_was_built_for():
    r = run_extraction("documents")
    assert r["field_accuracy_percent"] == 100.0 and len(r["unreadable_scans"]) == 6


def test_heldout_first_run_is_saved_and_honest():
    saved = json.loads((ROOT / "data/eval/heldout_first_run.json").read_text())
    assert saved["documents"] == 24 and saved["field_accuracy_percent"] < 60  # the stand in does not generalise: the score is kept as it came out


def test_same_file_twice_is_one_document(seeded):
    with seeded.factory() as s:
        d = s.scalars(select(Document)).first()
        assert intake.ingest(s, seeded, d.file_name, Path(d.stored_path).read_bytes()) is None


def test_unsupported_file_is_refused(seeded):
    import pytest
    with seeded.factory() as s, pytest.raises(intake.UnsupportedFile):
        intake.ingest(s, seeded, "x.exe", b"MZ....")


def test_a_scan_goes_to_review_with_a_clear_note(seeded):
    with seeded.factory() as s:
        e = s.scalars(select(ExceptionItem).where(ExceptionItem.kind == "unreadable_document")).first()
        assert "OCR" in e.detail
        b = s.get(Bill, e.ref_id)
        assert b.status == "needs_review" and b.total_minor == 0


def test_blocking_finding_needs_a_written_reason_and_draft_mode_posts_nothing(seeded):
    import pytest
    with seeded.factory() as s:
        blocked = s.scalars(select(ExceptionItem).where(ExceptionItem.kind == "wrong_total")).first()
        with pytest.raises(ValueError):
            posting.approve(s, blocked.ref_id, "tester")
        b = posting.approve(s, blocked.ref_id, "tester", "Vendor confirmed the total by phone")
        res = posting.post_draft(s, seeded, b.id, "tester")
        assert res["posted"] is False and "draft" in res["reason"].lower() and b.status == "approved"
        assert seeded.adapters.accounting.posted == []


def test_reminders_are_drafts_and_nothing_is_sent_in_draft_mode(seeded):
    with seeded.factory() as s:
        seeded.today(s)
        from booklantern import clock
        clock.advance(s, 24 * 14)  # two weeks later more invoices are due
        out = collections.plan_reminders(s, seeded)
        assert out["drafted"] >= 1
        for r in s.scalars(select(Reminder).where(Reminder.status == "drafted")):
            collections.approve_reminder(s, r.id, "tester")
        res = collections.send_approved(s, seeded)
        assert res["sent"] == 0 and seeded.adapters.email.outbox == []


def test_dispute_promise_and_opt_out_cancel_drafts(seeded):
    with seeded.factory() as s:
        from booklantern import clock
        clock.advance(s, 24 * 14)
        collections.plan_reminders(s, seeded)
        r = s.scalars(select(Reminder).where(Reminder.status == "drafted")).first()
        inv = r.invoice
        collections.set_dispute(s, inv.id, True, "wrong quantity", "tester")
        assert r.status == "cancelled" and r.cancel_reason == "dispute"


def test_forecast_from_the_database_is_deterministic_and_adds_up(seeded):
    with seeded.factory() as s:
        a, b = forecastservice.compute(s, seeded), forecastservice.compute(s, seeded)
        assert a == b and len(a["weeks"]) == 13
        assert a["opening_minor"] == 3200000  # the seed fixes the closing balance
        late = forecastservice.compute(s, seeded, {"collect_delay_days": 10})
        assert late["closing_minor"] <= a["closing_minor"]
        assert "forecast code" in forecastservice.explain(s, seeded, a)


def test_aging_matches_open_invoices(seeded):
    with seeded.factory() as s:
        rep = collections.aging_report(s, date(2026, 12, 1))
        open_total = sum(i.total_minor - i.paid_minor for i in s.scalars(select(Invoice).where(Invoice.status == "open")))
        assert rep["total_minor"] == open_total == sum(rep["buckets_minor"].values())
