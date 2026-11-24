"""Offline adapters for the demo and the tests. Nothing leaves this machine."""

from __future__ import annotations

import json
from pathlib import Path

from booklantern.adapters.base import DraftBill, InboundDocument, RemoteInvoice
from sendora_core.safety import write_action

DATA = Path(__file__).resolve().parents[5] / "data"


class SeedAccounting:
    def __init__(self, settings):
        self.settings = settings
        self.posted: list[DraftBill] = []

    def list_open_invoices(self) -> list[RemoteInvoice]:
        seed = json.loads((Path(self.settings.seed_dir or DATA) / "seed.json").read_text())
        names = {c["key"]: c["name"] for c in seed["customers"]}
        return [RemoteInvoice(i["number"], names[i["customer"]], i["total_minor"], i["total_minor"] - i["paid_minor"], i["due"]) for i in seed["invoices"] if i["status"] == "open"]

    @write_action("accounting.create_draft_bill")
    def create_draft_bill(self, bill: DraftBill) -> str:
        self.posted.append(bill)
        return f"seed-bill-{len(self.posted)}"

    def healthcheck(self) -> tuple[bool, str]:
        return True, "Offline demo accounting data."


class SeedPayments:
    def __init__(self, settings=None):
        self.settings = settings

    def create_payment_link(self, *, invoice_number: str, amount_minor: int, currency: str, description: str) -> str:
        return f"https://pay.example.test/demo/{invoice_number}"  # a placeholder, not a real page

    def healthcheck(self) -> tuple[bool, str]:
        return True, "Offline demo payment links (placeholders)."


class SeedInbox:
    def __init__(self, settings):
        self.settings = settings
        self.delivered: set[str] = set()

    def fetch_documents(self) -> list[InboundDocument]:
        root = Path(self.settings.seed_dir or DATA)
        seed = json.loads((root / "seed.json").read_text())
        out = []
        for d in seed["documents"]:
            if d["source"] == "inbox" and d["id"] not in self.delivered:
                self.delivered.add(d["id"])
                out.append(InboundDocument(d["id"], Path(d["file"]).name, (root / d["file"]).read_bytes(), d["from"], d["subject"]))
        return out

    def healthcheck(self) -> tuple[bool, str]:
        return True, "Offline demo mailbox."


class SeedEmail:
    def __init__(self, settings):
        self.settings = settings
        self.outbox: list[dict] = []

    @write_action("email.send")
    def send(self, *, from_addr: str, to: str, subject: str, body: str) -> str:
        self.outbox.append({"from": from_addr, "to": to, "subject": subject, "body": body})
        return f"seed-mail-{len(self.outbox)}"

    def healthcheck(self) -> tuple[bool, str]:
        return True, "Offline demo email. Nothing leaves this machine."
