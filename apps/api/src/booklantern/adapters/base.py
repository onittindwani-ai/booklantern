"""Adapter interfaces and shared helpers. Every category has an offline `seed` adapter."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlparse

from sendora_core.adapters import AdapterError


class OutcomeUnknown(AdapterError):
    """A call that may or may not have taken effect: the request (or the mail's text) had left when the answer was lost, or the server failed after it started. Whoever called must not
    simply try again unless the other side can recognise a repeat."""


class PermanentFailure(AdapterError):
    """The other side said no and will say no again (a mail server refusing the address, for example). Trying again changes nothing."""


@dataclass
class InboundDocument:
    external_id: str
    file_name: str
    data: bytes
    from_addr: str = ""
    subject: str = ""
    ref: str = ""  # a fixed reference, set only by the offline demo mailbox: a reference is never taken from text a sender wrote
    ack: str = ""  # which mailbox message this came from: it is marked read only after the document is safely stored (see InboxAdapter.acknowledge)


@dataclass
class InboundNote:
    """A message that came to the intake mailbox with no bill in it (a customer's answer to a reminder, for example). It is left unread in the mailbox and shown to a person."""
    uid: str
    from_addr: str
    subject: str
    snippet: str


@dataclass
class RemoteInvoice:
    number: str
    customer: str
    total_minor: int
    balance_minor: int
    due: str
    currency: str = "USD"


@dataclass
class DraftBill:
    vendor_name: str
    number: str
    issue_date: str
    due_date: str
    currency: str
    lines: list[dict] = field(default_factory=list)  # description, quantity, unit_minor, total_minor
    subtotal_minor: int = 0
    tax_minor: int = 0
    total_minor: int = 0
    memo: str = ""
    idempotency_key: str = ""  # the same key on a repeated call makes the accounting system return the first bill instead of creating a second one


class PostedDraft(str):
    """The id of the draft an accounting system made (it IS that id, as a string, so everything that used the plain id keeps working) plus what the system says about it.
    `total_minor` is the total the vendor's own answer reports (None when the adapter cannot read one back): posting compares it with the approved total and refuses to
    record success when they differ."""

    total_minor: int | None
    currency: str

    def __new__(cls, external_id: str, total_minor: int | None = None, currency: str = "") -> "PostedDraft":
        obj = super().__new__(cls, external_id)
        obj.total_minor, obj.currency = total_minor, currency
        return obj

    @property
    def external_id(self) -> str:
        return str(self)


def split_tax(lines: list[dict], tax_minor: int) -> list[int]:
    """The tax shared over the lines in proportion to their totals, the parts adding up to the tax exactly (the last line takes the remainder)."""
    if not lines or tax_minor <= 0:
        return [0] * len(lines)
    weights = [max(int(ln["total_minor"]), 0) for ln in lines]
    whole = sum(weights)
    if whole <= 0:
        return [tax_minor] + [0] * (len(lines) - 1)
    parts = [tax_minor * w // whole for w in weights]
    parts[-1] += tax_minor - sum(parts)
    return parts


class AccountingAdapter(Protocol):
    def list_open_invoices(self) -> list[RemoteInvoice]: ...
    def create_draft_bill(self, bill: DraftBill) -> str | PostedDraft: ...
    def healthcheck(self) -> tuple[bool, str]: ...


class PaymentsAdapter(Protocol):
    def create_payment_link(self, *, invoice_number: str, amount_minor: int, currency: str, description: str) -> str: ...
    def healthcheck(self) -> tuple[bool, str]: ...


class InboxAdapter(Protocol):
    def fetch_documents(self) -> list[InboundDocument]: ...
    def acknowledge(self, acks: list[str]) -> None: ...
    def take_notes(self) -> list[InboundNote]: ...
    def healthcheck(self) -> tuple[bool, str]: ...


class EmailSender(Protocol):
    def send(self, *, from_addr: str, to: str, subject: str, body: str) -> str: ...
    def healthcheck(self) -> tuple[bool, str]: ...


def is_loopback(host: str) -> bool:
    """True for this same computer (localhost, 127.x, ::1). Plain text mail connections are allowed only to such a host."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def safe_base_url(url: str, *, allow_http_local: bool = False) -> str:
    """Refuse base URLs that point at the local network or non web schemes (SSRF guard for URLs a user can set).

    Only https is accepted. Hosts that resolve to private, loopback, link local or reserved addresses are refused,
    unless `allow_http_local` is set (tests and a self hosted accounting tool on the same machine, a deliberate choice).
    """
    u = urlparse(url)
    if u.scheme not in {"https", "http"} or not u.hostname:
        raise AdapterError("The URL must start with https:// and include a host name.")
    if u.username or u.password:
        raise AdapterError("Put credentials in the key fields, not in the URL.")
    if u.scheme == "http" and not allow_http_local:
        raise AdapterError("Use an https:// URL.")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise AdapterError(f"The host {u.hostname} could not be found.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified) and not allow_http_local:
            raise AdapterError("That URL points at a private or local address, which is refused.")
    return url.rstrip("/")
