from booklantern import jobs, worker
from booklantern.config import Settings
from sendora_core.jobs import Worker
from sendora_core.settings import Mode


def test_scheduler_queues_each_job_once_and_the_worker_runs_them(seeded):
    w = Worker(seeded.factory, jobs.make_handlers(seeded))
    with seeded.factory() as s:
        assert jobs.schedule_due(s, seeded) == 4
        s.commit()
    assert worker.run_once(seeded, w) >= 4
    with seeded.factory() as s:
        assert jobs.schedule_due(s, seeded) == 0  # just ran, nothing is due yet


def test_the_cycle_reports_each_stage(seeded):
    with seeded.factory() as s:
        out = jobs.run_cycle(s, seeded)
        assert set(out) == {"intake", "reconcile", "reminders", "forecast"} and out["intake"]["processed"] == 0  # the seed cycle already read everything


def test_config_problems_are_plain():
    p = Settings(_env_file=None, demo_mode=False, accounting_adapter="quickbooks", payments_adapter="stripe", inbox_adapter="imap", accounting_write=True, mode=Mode.DRAFT).problems()
    text = " ".join(p)
    assert "OWNER_PASSWORD_HASH" in text and "QBO_CLIENT_ID" in text and "STRIPE_SECRET_KEY" in text and "IMAP_HOST" in text and "ACCOUNTING_WRITE" in text
    s = Settings(_env_file=None, collection_prob_bp="current=9000")
    assert s.probs() == {"current": 9000}


def test_demo_reset_is_repeatable(seeded):
    from booklantern import demo
    with seeded.factory() as s:
        a = demo.reset(s, seeded)
    with seeded.factory() as s:
        b = demo.reset(s, seeded)
    assert a["bank"] == b["bank"] and a["matching"] == b["matching"]
