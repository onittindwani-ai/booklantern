import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT)]

from booklantern.config import Settings  # noqa: E402
from booklantern.context import Ctx  # noqa: E402
from sendora_core import models as _core  # noqa: E402,F401
from sendora_core.db import Base, make_engine, make_session_factory  # noqa: E402


def make_ctx(tmp_path, **kw) -> Ctx:
    kw.setdefault("session_secret", "test-secret-test-secret")
    s = Settings(database_url=f"sqlite:///{tmp_path / 't.sqlite3'}", upload_dir=str(tmp_path / "up"), _env_file=None, **kw)
    eng = make_engine(s.database_url)
    Base.metadata.create_all(eng)
    return Ctx(s, make_session_factory(eng))


def freeze_clock(monkeypatch, when: datetime) -> datetime:
    """Make the app's real clock (the one used outside demo mode) read `when`. Tests that depend on business days or quiet hours pin it, so the suite gives the same answer on a
    Monday at noon and on a Sunday at 03:00."""
    when = when if when.tzinfo else when.replace(tzinfo=UTC)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return when if tz is None else when.astimezone(tz)

    monkeypatch.setattr("booklantern.clock.datetime", Frozen)
    return when


@pytest.fixture(autouse=True)
def _clock_from_the_environment(monkeypatch):
    """BOOKLANTERN_TEST_NOW=2026-12-06T08:00:00+00:00 runs the whole suite as if it were that moment (a Sunday, or 03:00 in New York), to prove no test needs a weekday afternoon."""
    raw = os.environ.get("BOOKLANTERN_TEST_NOW")
    if raw:
        freeze_clock(monkeypatch, datetime.fromisoformat(raw))


@pytest.fixture()
def ctx(tmp_path):
    return make_ctx(tmp_path)


@pytest.fixture()
def seeded(tmp_path):
    """A context with the seed loaded and the first demo pipeline done."""
    from booklantern import demo, jobs

    c = make_ctx(tmp_path)
    with c.factory() as s:
        demo.reset(s, c)
    with c.factory() as s:
        jobs.run_cycle(s, c)
        s.commit()
    return c
