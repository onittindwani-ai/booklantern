"""One registry of every adapter, with its tier. Demo mode can only build the offline seed adapters."""

from __future__ import annotations

from dataclasses import dataclass

from booklantern.adapters import seed
from booklantern.adapters.imap import ImapInbox, SmtpSender
from booklantern.adapters.others import AkauntingAccounting, CsvAccounting, StripePayments, XeroAccounting
from booklantern.adapters.quickbooks import QuickBooksAccounting
from sendora_core.adapters import AdapterError, AdapterRegistry, AdapterSpec

CATEGORIES = ("accounting", "payments", "inbox", "email")
ENV_VARS = {
    ("accounting", "quickbooks"): ["QBO_CLIENT_ID", "QBO_CLIENT_SECRET", "QBO_REFRESH_TOKEN", "QBO_REALM_ID", "QBO_ENVIRONMENT", "QBO_MINOR_VERSION"],
    ("accounting", "xero"): ["XERO_ACCESS_TOKEN", "XERO_TENANT_ID"],
    ("accounting", "akaunting"): ["AKAUNTING_BASE_URL", "AKAUNTING_USER", "AKAUNTING_PASSWORD"],
    ("accounting", "csv"): ["CSV_FOLDER"],
    ("payments", "stripe"): ["STRIPE_SECRET_KEY"],
    ("inbox", "imap"): ["IMAP_HOST", "IMAP_PORT", "SMTP_USER", "SMTP_PASSWORD"],
    ("email", "smtp"): ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_FROM"],
}


def build_registry(settings) -> AdapterRegistry:
    reg = AdapterRegistry(settings)
    add = lambda c, n, t, f, notes="": reg.register(AdapterSpec(c, n, t, f, False, notes))  # noqa: E731
    add("accounting", "seed", "A", seed.SeedAccounting, "Offline demo data. Nothing is posted anywhere.")
    add("accounting", "csv", "A", CsvAccounting, "Reads invoices.csv, writes draft-bills.csv. No account needed.")
    add("accounting", "quickbooks", "A", QuickBooksAccounting, "Tested against a mock written from Intuit's public material, not the real service. OAuth endpoints verified, bill and invoice paths unverified.")
    add("accounting", "xero", "B", XeroAccounting, "From memory of public docs, the pages could not be read. Tested against a mock.")
    add("accounting", "akaunting", "B", AkauntingAccounting, "From memory of public docs, the pages could not be read. Tested against a mock.")
    add("payments", "seed", "A", seed.SeedPayments, "Offline placeholders. No real link.")
    add("payments", "stripe", "B", StripePayments, "Payment link create call verified on the API reference page. Tested against a mock.")
    add("inbox", "seed", "A", seed.SeedInbox, "Offline demo mailbox.")
    add("inbox", "imap", "A", ImapInbox, "Tested against a mock IMAP server, not a real mail host.")
    add("email", "seed", "A", seed.SeedEmail, "Offline. Nothing leaves this machine.")
    add("email", "smtp", "A", SmtpSender, "Tested against a mock SMTP server, not a real mail host.")
    return reg


@dataclass
class AdapterSet:
    accounting: object
    payments: object
    inbox: object
    email: object


def build_adapters(settings, registry: AdapterRegistry | None = None) -> AdapterSet:
    reg = registry or build_registry(settings)
    choice = {c: getattr(settings, f"{c}_adapter") for c in CATEGORIES}
    if settings.demo_mode:
        bad = {c: n for c, n in choice.items() if n != "seed"}
        if bad:
            raise AdapterError(f"DEMO_MODE is on, so only offline adapters can be used. Change {', '.join(f'{c.upper()}_ADAPTER' for c in bad)} or turn DEMO_MODE off.")
    return AdapterSet(**{c: reg.get(c, n) for c, n in choice.items()})
