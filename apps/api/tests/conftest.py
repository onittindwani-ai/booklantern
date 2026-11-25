import sys
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
