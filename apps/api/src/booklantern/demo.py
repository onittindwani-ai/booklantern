"""Demo mode: reset to the seed data, move the clock. Fictional people and the offline stand ins only. Nothing real is touched."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from booklantern import bankservice, clock, collections, forecastservice, intake
from booklantern.models import State
from booklantern.seeding import data_dir as seed_data_dir, load_seed, read_seed
from sendora_core.db import Base


def data_dir(ctx) -> Path:
    return seed_data_dir(ctx.settings.seed_dir)


def reset(session: Session, ctx) -> dict:
    """Erase every table and load the seed data. It exists only for a demo with no owner password: with a real owner it refuses, whatever route called it."""
    if not ctx.settings.demo_shortcuts:
        raise PermissionError("The demo reset is only available in demo mode with no owner password set.")
    root = data_dir(ctx)
    seed = read_seed(root)  # read the data BEFORE anything is erased: a missing folder must not leave an empty database
    session.rollback()
    session.close()
    # Empty every table and load the seed in ONE transaction. Dropping and recreating the tables left a moment with no tables,
    # and any page that refreshed during it (the live stream does this on every event) got a 500 "no such table".
    with ctx.factory() as s:
        for table in reversed(Base.metadata.sorted_tables):
            s.execute(table.delete())
        clock.set_offset(s, 0.0)
        s.flush()
        now = clock.now(s, True)
        info = load_seed(s, seed, now)
        imp = bankservice.import_csv(s, (root / seed["bank_csv"]).read_text(), "seed-statement")
        match = bankservice.run_matching(s, ctx)
        # The two part payments on the demo statement are only suggestions (a part payment always is). The demo opens with them confirmed, as a person would on the first day,
        # so the open balances it shows are the ones the seed describes. Their invoices were loaded with nothing paid (see seeding.load_seed): confirming applies each deposit once.
        from sqlalchemy import select

        from booklantern.models import Match
        for m in list(s.scalars(select(Match).where(Match.status == "suggested", Match.reason.like("%marked as a part payment%")))):
            bankservice.confirm_match(s, m.id, "demo seed")
        bankservice.record_payments(s)
        uploaded = 0
        for d in seed["documents"]:
            if d["source"] == "upload":
                doc = intake.ingest(s, ctx, Path(d["file"]).name, (root / d["file"]).read_bytes(), "upload", "", "", ref=d["id"])
                if doc:
                    intake.process_document(s, ctx, doc)
                    uploaded += 1
        collections.update_promises(s, ctx.today(s))
        forecastservice.save(s, ctx, forecastservice.compute(s, ctx))
        s.commit()
        return {"seed": info, "bank": imp, "matching": match, "uploaded_documents": uploaded, "clock": now.isoformat()}
