"""Runtime context shared by the API and the worker: settings, database, adapters, model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from booklantern import clock
from booklantern.config import Settings
from booklantern.models import State
from booklantern.offline_llm import OfflineBackend
from booklantern.registry import AdapterSet, build_adapters, build_registry
from sendora_core.costs import CostTracker
from sendora_core.llm import LLM, build_llm
from sendora_core.settings import LLMBackendKind, Mode


@dataclass
class Ctx:
    settings: Settings
    factory: sessionmaker[Session]
    adapters: AdapterSet | Any = None
    registry: Any = None

    def __post_init__(self) -> None:
        self.registry = self.registry or build_registry(self.settings)
        if self.adapters is None:
            self.adapters = build_adapters(self.settings, self.registry)

    def effective(self, session: Session) -> Settings:
        """The kill switch can be turned on in the app, and the mode can be pulled back to draft. Neither can go the other way."""
        kill, force = session.get(State, "kill_switch"), session.get(State, "force_draft")
        upd: dict[str, Any] = {}
        if kill and kill.value == "1":
            upd["kill_switch"] = True
        if force and force.value == "1":
            upd["mode"] = Mode.DRAFT
        return self.settings.model_copy(update=upd) if upd else self.settings

    def now(self, session: Session):
        """The real time, unless demo shortcuts are on (DEMO_MODE and no owner password): only then the made up demo date and its offset count."""
        return clock.now(session, self.settings.demo_shortcuts)

    def today(self, session: Session) -> date:
        return clock.today(session, self.settings.demo_shortcuts)

    def rates(self, session: Session):
        from booklantern import fxservice

        return fxservice.rate_book(session, self)

    def llm(self, session: Session, live: bool = True) -> LLM:
        # LLM_BACKEND=offline (default) | fixture | anthropic. The offline stand in is the zero account default.
        # The anthropic path is UNVERIFIED against the real service. live=False always uses the offline stand in: a read only visitor never causes a paid call.
        eff = self.effective(session)
        if not live and eff.effective_llm_backend is LLMBackendKind.ANTHROPIC:
            eff = eff.model_copy(update={"llm_backend": LLMBackendKind.OFFLINE})
        return build_llm(eff, CostTracker(session), offline=OfflineBackend())


def set_state(session: Session, key: str, value: str) -> None:
    row = session.get(State, key)
    if row is None:
        session.add(State(key=key, value=value))
    else:
        row.value = value


def get_state(session: Session, key: str, default: str = "") -> str:
    row = session.get(State, key)
    return row.value if row else default
