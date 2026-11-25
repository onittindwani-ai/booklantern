"""Booklantern settings. Subclass of the base settings with this system's variables (names only, never values, in docs)."""

from __future__ import annotations

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field

from sendora_core.settings import BaseAppSettings, Mode

DEFAULT_COMPANY_NAME = "Birchfield Supply Co"  # the made up demo company: a real install must name its own
DEFAULT_EMAIL_FROM = "accounts@example.test"
EMAIL_LIKE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Settings(BaseAppSettings):
    app_name: str = "booklantern"
    database_url: str = "sqlite:///./booklantern.sqlite3"

    owner_email: str = "owner@example.test"
    owner_password_hash: str | None = None
    approver_email: str | None = None
    approver_password_hash: str | None = None
    viewer_email: str | None = None  # read only role, for example an accountant: may look at everything, change nothing
    viewer_password_hash: str | None = None
    login_burst: int = Field(default=5, ge=1, le=1000)  # sign in tries in a row before a short wait; the browser tests raise it

    company_name: str = Field(default=DEFAULT_COMPANY_NAME, max_length=120)  # COMPANY_NAME: bills addressed to another name are flagged; it also signs every reminder
    company_address: str = Field(default="", max_length=300)  # COMPANY_ADDRESS: physical postal address, printed in the footer of every reminder email
    reply_to: str = Field(default="", max_length=254)  # REPLY_TO: where customers answer a reminder, also the mailto in the List-Unsubscribe header (empty means EMAIL_FROM)
    base_currency: str = Field(default="USD", min_length=3, max_length=3)  # BASE_CURRENCY
    default_timezone: str = "America/New_York"  # DEFAULT_TIMEZONE: the time zone of a customer imported without one (reminders are sent in the customer's local hours)
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR)$")  # LOG_LEVEL

    accounting_adapter: str = "seed"  # seed, csv, quickbooks, xero, akaunting
    payments_adapter: str = "seed"  # seed or stripe
    inbox_adapter: str = "seed"  # seed or imap
    email_adapter: str = "seed"  # seed or smtp
    extractor: str = "offline"  # offline (rules, not a model) or live (a language model reads, code verifies; UNVERIFIED live, see docs/14)
    reminder_writer: str = "template"  # template (the default wording) or model (the model words each reminder, checked by code; a person still approves each one)
    accounting_write: bool = False  # read only by default, even in live mode

    qbo_client_id: str = ""
    qbo_client_secret: str = ""
    qbo_refresh_token: str = ""
    qbo_realm_id: str = ""
    qbo_environment: str = "sandbox"  # sandbox or production
    qbo_minor_version: str = "75"  # UNVERIFIED: check the current value on Intuit's minor version page
    qbo_api_base: str = ""
    qbo_token_url: str = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

    xero_access_token: str = ""
    xero_tenant_id: str = ""
    xero_base_url: str = "https://api.xero.com"
    akaunting_base_url: str = ""
    akaunting_user: str = ""
    akaunting_password: str = ""
    csv_folder: str = "./csv-in"

    stripe_secret_key: str = ""
    stripe_base_url: str = "https://api.stripe.com"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    imap_host: str = ""
    imap_port: int = 993
    imap_use_ssl: bool = True
    email_from: str = DEFAULT_EMAIL_FROM

    # Decided defaults for the collections ladder and the forecast. The implementer can change each one.
    reminder_window_start: int = Field(default=9, ge=0, le=23)
    reminder_window_end: int = Field(default=17, ge=1, le=24)
    reminder_min_gap_days: int = Field(default=5, ge=0, le=60)
    reminder_max_count: int = Field(default=4, ge=1, le=12)
    collection_prob_bp: str = "current=9500,1-30=9000,31-60=7500,61-90=5000,90+=2000"
    handoff_dir: str = "./handoff"
    seed_dir: str = ""
    upload_dir: str = "./uploads"

    def probs(self) -> dict[str, int]:
        return {k.strip(): int(v) for k, v in (p.split("=") for p in self.collection_prob_bp.split(",") if "=" in p)}

    def identity_problems(self) -> list[str]:
        """What is still a placeholder in the business identity. A reminder goes out under the company's name, address and sender mailbox."""
        out: list[str] = []
        if self.company_name.strip() in {"", DEFAULT_COMPANY_NAME}:
            out.append("COMPANY_NAME is still the made up demo name. Set your client's legal name: bills addressed to any other name are flagged, and reminders are signed with it.")
        if self.email_adapter != "seed" and (self.email_from.strip() in {"", DEFAULT_EMAIL_FROM} or not EMAIL_LIKE.match(self.email_from)):
            out.append("EMAIL_FROM is empty or still the example address. Set the mailbox reminders are sent from.")
        if self.email_adapter != "seed" and len(self.company_address.strip()) < 10:
            out.append("COMPANY_ADDRESS is empty. A reminder email carries the company's physical postal address in its footer.")
        if self.reply_to and not EMAIL_LIKE.match(self.reply_to):
            out.append("REPLY_TO is not an email address.")
        try:
            ZoneInfo(self.default_timezone)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            out.append("DEFAULT_TIMEZONE is not a time zone name (for example America/New_York).")
        return out

    def account_problems(self) -> list[str]:
        """The owner, the approver and the viewer are three different people. Two roles on one email would make one account silently replace the other (the owner's would be lost)."""
        from sendora_core.auth import clean_email

        named = [("OWNER_EMAIL", clean_email(self.owner_email)), ("APPROVER_EMAIL", clean_email(self.approver_email or "")), ("VIEWER_EMAIL", clean_email(self.viewer_email or ""))]
        seen: dict[str, str] = {}
        out: list[str] = []
        for name, email in named:
            if not email:
                continue
            if email in seen:
                out.append(f"{name} is the same address as {seen[email]}. The owner, the approver and the viewer must be three different people, or one account would silently replace the other.")
            else:
                seen[email] = name
        return out

    def runtime_errors(self) -> list[str]:
        out = super().runtime_errors() + self.account_problems()
        if self.mode is Mode.LIVE and not self.demo_mode:
            out += self.identity_problems()
        return list(dict.fromkeys(out))

    def problems(self) -> list[str]:
        out = [p for p in super().problems() if not (self.demo_mode and p.startswith("MODE is live while DEMO_MODE"))]
        if not self.demo_mode and not self.owner_password_hash:
            out.append("OWNER_PASSWORD_HASH is empty. Create one with tools/hash_password.py and set it before you run outside demo mode.")
        if self.demo_mode and self.owner_password_hash:
            out.append("DEMO_MODE is true but an owner password is set. The public demo password is switched off; set DEMO_MODE=false for a real install.")
        if not self.demo_mode:
            out += [p for p in self.identity_problems() if p not in out]
        if self.accounting_write and self.mode is not Mode.LIVE:
            out.append("ACCOUNTING_WRITE is true but MODE is draft, so nothing will be posted. That is safe, set MODE=live only when you mean it.")
        if self.accounting_adapter == "quickbooks" and not (self.qbo_client_id and self.qbo_client_secret and self.qbo_refresh_token and self.qbo_realm_id):
            out.append("ACCOUNTING_ADAPTER is quickbooks but QBO_CLIENT_ID, QBO_CLIENT_SECRET, QBO_REFRESH_TOKEN or QBO_REALM_ID is empty.")
        if self.accounting_adapter == "xero" and not (self.xero_access_token and self.xero_tenant_id):
            out.append("ACCOUNTING_ADAPTER is xero but XERO_ACCESS_TOKEN or XERO_TENANT_ID is empty.")
        if self.accounting_adapter == "akaunting" and not (self.akaunting_base_url and self.akaunting_user):
            out.append("ACCOUNTING_ADAPTER is akaunting but AKAUNTING_BASE_URL or AKAUNTING_USER is empty.")
        if self.payments_adapter == "stripe" and not self.stripe_secret_key:
            out.append("PAYMENTS_ADAPTER is stripe but STRIPE_SECRET_KEY is empty.")
        if self.inbox_adapter == "imap" and not (self.imap_host and self.smtp_user):
            out.append("INBOX_ADAPTER is imap but IMAP_HOST or SMTP_USER is empty.")
        return out
