"""Adapter interfaces and shared helpers. Every category has an offline `seed` adapter."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlparse

from sendora_core.adapters import AdapterError


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


class AccountingAdapter(Protocol):
    def list_open_invoices(self) -> list[RemoteInvoice]: ...
    def create_draft_bill(self, bill: DraftBill) -> str: ...
    def healthcheck(self) -> tuple[bool, str]: ...


class PaymentsAdapter(Protocol):
    def create_payment_link(self, *, invoice_number: str, amount_minor: int, currency: str, description: str) -> str: ...
    def healthcheck(self) -> tuple[bool, str]: ...


class InboxAdapter(Protocol):
    def fetch_documents(self) -> list[InboundDocument]: ...
    def acknowledge(self, acks: list[str]) -> None: ...
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
