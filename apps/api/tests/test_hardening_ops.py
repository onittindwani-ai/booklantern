"""Alembic and the worker read the same settings as the API, the backup script is safe, and the docs and .env.example list every setting."""

import re
import stat
import subprocess
from pathlib import Path

import pytest

from booklantern import worker
from booklantern.config import Settings
from booklantern.dburl import resolve_url
from sendora_core.settings import BaseAppSettings, ConfigError

ROOT = Path(__file__).resolve().parents[3]


def test_alembic_reads_the_same_settings_as_the_app(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ENV_FILE", raising=False)
    assert resolve_url("sqlite:///x.db") == "sqlite:///x.db"  # -x url=... wins
    f = tmp_path / "prod.env"
    f.write_text("DATABASE_URL=postgresql+psycopg://u:p@db:5432/booklantern\n")
    assert resolve_url(None, str(f)) == "postgresql+psycopg://u:p@db:5432/booklantern"
    monkeypatch.setenv("ENV_FILE", str(f))
    assert resolve_url() == "postgresql+psycopg://u:p@db:5432/booklantern"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///from-env.db")
    assert resolve_url() == "sqlite:///from-env.db"
    monkeypatch.delenv("DATABASE_URL")
    empty = tmp_path / "empty.env"
    empty.write_text("APP_NAME=x\n")
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        resolve_url(None, str(empty))


def test_alembic_env_uses_the_shared_resolver():
    text = (ROOT / "apps" / "api" / "alembic" / "env.py").read_text()
    assert "resolve_url" in text and "sqlite:///" not in text  # no built in fallback database


def test_the_worker_reads_env_file_like_the_api(tmp_path, monkeypatch):
    f = tmp_path / "w.env"
    f.write_text("APP_NAME=from-the-worker-file\nLOG_LEVEL=WARNING\n")
    monkeypatch.setenv("ENV_FILE", str(f))
    monkeypatch.delenv("APP_NAME", raising=False)
    s = worker.load_settings()
    assert s.app_name == "from-the-worker-file" and s.log_level == "WARNING"


def test_the_worker_refuses_the_same_unsafe_settings_as_the_api(tmp_path, monkeypatch):
    f = tmp_path / "w.env"
    f.write_text("DEMO_MODE=false\nSESSION_SECRET=change-me-to-a-long-random-string\n")
    monkeypatch.setenv("ENV_FILE", str(f))
    monkeypatch.setattr(worker, "make_engine", lambda *_: pytest.fail("started the database before checking the settings"))
    with pytest.raises(ConfigError):
        worker.main()


def test_the_log_level_setting_is_checked():
    with pytest.raises(Exception):
        Settings(_env_file=None, log_level="LOUD")


# ---- the docs and .env.example list every setting ----

def example_names() -> set[str]:
    return {m.group(1) for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=", (ROOT / ".env.example").read_text(), re.M)}


def test_env_example_lists_every_setting():
    names = {n.upper() for n in Settings.model_fields} | {n.upper() for n in BaseAppSettings.model_fields}
    missing = sorted(names - example_names())
    assert not missing, f"add these to .env.example: {missing}"


def test_the_environment_variables_doc_lists_every_setting():
    doc = (ROOT / "docs" / "04-ENVIRONMENT-VARIABLES.md").read_text()
    listed = set(re.findall(r"`([A-Z][A-Z0-9_]+)`", doc))
    names = {n.upper() for n in Settings.model_fields} | {n.upper() for n in BaseAppSettings.model_fields}
    missing = sorted(names - listed)
    assert not missing, f"add these to docs/04-ENVIRONMENT-VARIABLES.md: {missing}"


def test_env_example_loads_as_it_is():
    s = Settings(_env_file=str(ROOT / ".env.example"))
    assert s.demo_mode is False and s.llm_call_budget is None and s.company_name == "Birchfield Supply Co"  # the placeholder is kept on purpose so problems() asks for a real one
    assert any("COMPANY_NAME" in p for p in s.problems())


def test_every_block_of_env_example_has_a_comment():
    blocks = (ROOT / ".env.example").read_text().split("\n\n")
    for block in blocks:
        lines = [x for x in block.splitlines() if x.strip()]
        if any(re.match(r"^[A-Z][A-Z0-9_]*=", x) for x in lines):
            assert any(x.startswith("#") for x in lines), f"a block of settings with no comment: {lines[0]}"


# ---- the backup script ----

def fake_docker(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    d = bin_dir / "docker"
    d.write_text("#!/bin/sh\ncase \"$*\" in\n  *pg_dump*) printf '%s' \"$FAKE_DUMP\" ;;\n  *tar*) [ -n \"${FAKE_TAR_FAIL:-}\" ] && exit 1; printf 'tarbytes' ;;\nesac\n")
    d.chmod(d.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def run_backup(tmp_path, dump, **extra):
    out = tmp_path / "out"
    env = {"PATH": f"{fake_docker(tmp_path)}:/usr/bin:/bin", "BACKUP_DIR": str(out), "FAKE_DUMP": dump, "HOME": str(tmp_path), **extra}
    r = subprocess.run(["sh", str(ROOT / "deploy" / "hetzner" / "backup.sh")], cwd="/", env=env, capture_output=True, text=True)  # cwd is not the repo, as under cron
    return r, out


def test_backup_works_from_any_folder_and_keeps_the_dump(tmp_path):
    r, out = run_backup(tmp_path, "PGDMPdata")
    assert r.returncode == 0, r.stderr
    assert [p.read_text() for p in out.glob("booklantern-*.dump")] == ["PGDMPdata"] and list(out.glob("uploads-*.tar"))
    assert not list(out.glob("*.partial"))
    assert (out.stat().st_mode & 0o077) == 0  # umask 077 applies to the folder as well as to the files written
    assert all((p.stat().st_mode & 0o077) == 0 for p in out.glob("booklantern-*.dump"))


def test_backup_fails_loudly_when_the_uploads_cannot_be_archived(tmp_path):
    r, out = run_backup(tmp_path, "PGDMPdata", FAKE_TAR_FAIL="1")
    assert r.returncode == 1 and "uploaded bills" in r.stderr  # it used to say nothing and exit 0, so a backup without the bills looked complete
    assert [p.read_text() for p in out.glob("booklantern-*.dump")] == ["PGDMPdata"]  # the database dump that did succeed is kept
    assert not list(out.glob("uploads-*")) and not list(out.glob("*.partial"))


def test_backup_never_keeps_an_empty_dump(tmp_path):
    r, out = run_backup(tmp_path, "")
    assert r.returncode == 1 and "empty" in r.stderr
    assert not list(out.glob("*.dump")) and not list(out.glob("*.partial"))


# ---- the data folder comes from SEED_DIR first ----

def test_no_module_reaches_for_the_data_folder_by_its_own_path():
    src = ROOT / "apps" / "api" / "src" / "booklantern"
    hits = [str(p.relative_to(src)) for p in src.rglob("*.py") if "parents[" in p.read_text() and p.name != "seeding.py"]
    assert hits == [], f"find the data folder through settings.seed_dir (seeding.data_dir): {hits}"


def test_seed_dir_is_used_before_the_fallback(tmp_path, monkeypatch):
    from booklantern import seeding

    data = tmp_path / "mine"
    data.mkdir()
    (data / "seed.json").write_text("{}")
    monkeypatch.setattr(seeding, "REPO_DATA", tmp_path / "nowhere")
    assert seeding.data_dir(str(data)) == data
    with pytest.raises(FileNotFoundError):
        seeding.data_dir("")
