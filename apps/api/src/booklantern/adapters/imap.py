"""A mailbox over IMAP (read unseen mail and take PDF or image attachments) and a sender over SMTP. Works with Gmail (app password), Outlook and most hosts.

Every connection checks the server certificate and host name. A plain text connection (SMTP_USE_TLS=false, IMAP_USE_SSL=false) is allowed only to this same computer.
A message is marked read only after its documents are stored (`acknowledge`), so one bad attachment or a crash never loses a bill.
"""

from __future__ import annotations

import email
import imaplib
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.policy import default as default_policy
from email.utils import make_msgid, parseaddr

from booklantern.adapters.base import InboundDocument, is_loopback
from booklantern.util import clean_header
from sendora_core.adapters import AdapterError
from sendora_core.safety import write_action

ALLOWED = {"application/pdf", "image/png", "image/jpeg"}
MAX_BYTES = 15 * 1024 * 1024  # one attachment
MAX_MESSAGE_BYTES = 25 * 1024 * 1024  # one whole message: a larger one is never loaded into memory
MAX_MESSAGES_PER_POLL = 25  # the rest wait for the next poll
MAX_ATTACHMENTS_PER_MESSAGE = 10
SIZE_RE = re.compile(rb"RFC822\.SIZE\s+(\d+)")


class _Base:
    def __init__(self, settings):
        self.settings = settings

    def _need(self, *names: str) -> None:
        missing = [n.upper() for n in names if not getattr(self.settings, n)]
        if missing:
            raise AdapterError(f"Set {', '.join(missing)} in your environment first (see docs/04-ENVIRONMENT-VARIABLES.md).")

    def _smtp(self) -> smtplib.SMTP:
        """Always a verified connection: the certificate and the host name are checked. Plain text is allowed only to this same computer."""
        s = self.settings
        ctx = ssl.create_default_context()
        if s.smtp_port == 465:
            c = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=20, context=ctx)
        else:
            if not s.smtp_use_tls and not is_loopback(s.smtp_host):
                raise AdapterError("SMTP_USE_TLS=false is only allowed for a mail server on this same computer (127.0.0.1). Turn it back on.")
            c = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20)
            if s.smtp_use_tls:
                try:
                    c.starttls(context=ctx)
                except Exception:
                    c.close()
                    raise
        if s.smtp_user:
            c.login(s.smtp_user, s.smtp_password)
        return c

    def _imap(self) -> imaplib.IMAP4:
        s = self.settings
        if s.imap_use_ssl:
            c = imaplib.IMAP4_SSL(s.imap_host, s.imap_port, ssl_context=ssl.create_default_context(), timeout=20)
        elif is_loopback(s.imap_host):
            c = imaplib.IMAP4(s.imap_host, s.imap_port, timeout=20)
        else:
            raise AdapterError("IMAP_USE_SSL=false is only allowed for a mail server on this same computer (127.0.0.1). Turn it back on.")
        c.login(s.smtp_user, s.smtp_password)
        return c


def _size_of(parts) -> int | None:
    for p in parts or []:
        raw = p if isinstance(p, bytes) else (p[0] if isinstance(p, tuple) else b"")
        m = SIZE_RE.search(raw)
        if m:
            return int(m.group(1))
    return None


class ImapInbox(_Base):
    def fetch_documents(self) -> list[InboundDocument]:
        """Attachments of unread messages (at most MAX_MESSAGES_PER_POLL messages). The messages stay unread until `acknowledge` is called with the `ack` of each document.
        A message that cannot hold a bill (too large, no PDF or image attachment) is marked read here, because there is nothing in it to lose."""
        self._need("imap_host", "smtp_user")
        out: list[InboundDocument] = []
        try:
            c = self._imap()
            try:
                c.select("INBOX")
                _, data = c.uid("SEARCH", None, "UNSEEN")
                for uid_b in (data[0] or b"").split()[:MAX_MESSAGES_PER_POLL]:
                    uid = uid_b.decode()
                    _, size_parts = c.uid("FETCH", uid, "(RFC822.SIZE)")
                    size = _size_of(size_parts)
                    if size is not None and size > MAX_MESSAGE_BYTES:
                        c.uid("STORE", uid, "+FLAGS", "(\\Seen)")  # too large to load, nothing is read from it
                        continue
                    _, parts = c.uid("FETCH", uid, "(BODY.PEEK[])")  # PEEK: reading does not mark it read
                    if not parts or not parts[0] or not isinstance(parts[0], tuple):
                        continue
                    msg = email.message_from_bytes(parts[0][1], policy=default_policy)
                    found = 0
                    for part in msg.iter_attachments():
                        data_b = part.get_payload(decode=True) or b""
                        if part.get_content_type() in ALLOWED and 0 < len(data_b) <= MAX_BYTES and found < MAX_ATTACHMENTS_PER_MESSAGE:
                            found += 1
                            out.append(InboundDocument(f"{msg['Message-ID'] or uid}:{part.get_filename() or 'attachment'}", clean_header(part.get_filename() or "attachment.pdf"), data_b,
                                                       parseaddr(str(msg["From"] or ""))[1], clean_header(str(msg["Subject"] or "")), ack=uid))
                    if not found:
                        c.uid("STORE", uid, "+FLAGS", "(\\Seen)")
            finally:
                try:
                    c.logout()
                except Exception:
                    pass
        except imaplib.IMAP4.error as exc:
            raise AdapterError("The inbox rejected the login or the command. Check the user name and app password.") from exc
        except ssl.SSLCertVerificationError as exc:
            raise AdapterError(f"The certificate of {self.settings.imap_host} could not be verified, so nothing was read. Check IMAP_HOST and the port.") from exc
        except OSError as exc:
            raise AdapterError(f"Could not reach the inbox at {self.settings.imap_host}: {type(exc).__name__}.") from exc
        return out

    def acknowledge(self, acks: list[str]) -> None:
        """Mark messages read once their documents are stored. A failure here only means the message is looked at again next time (the same file is stored once)."""
        if not acks:
            return
        try:
            c = self._imap()
            try:
                c.select("INBOX")
                for uid in acks:
                    c.uid("STORE", uid, "+FLAGS", "(\\Seen)")
            finally:
                try:
                    c.logout()
                except Exception:
                    pass
        except (imaplib.IMAP4.error, OSError, ssl.SSLError):
            return

    def healthcheck(self) -> tuple[bool, str]:
        try:
            self._need("imap_host", "smtp_user")
            self._imap().logout()
            return True, "Connected to the inbox."
        except AdapterError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, f"Could not connect: {type(exc).__name__}. Check host, port and password."


class SmtpSender(_Base):
    @write_action("email.send")
    def send(self, *, from_addr: str, to: str, subject: str, body: str) -> str:
        self._need("smtp_host")
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = clean_header(from_addr), clean_header(to), clean_header(subject)
        m["Message-ID"] = make_msgid(domain=from_addr.rsplit("@", 1)[-1] or "localhost")
        reply_to = clean_header(getattr(self.settings, "reply_to", "") or "")
        if reply_to:
            m["Reply-To"] = reply_to
        # Mail programs show an "unsubscribe" button from this header. The address is a person's mailbox: a reply that says stop is handled by hand (docs/10).
        m["List-Unsubscribe"] = f"<mailto:{reply_to or clean_header(from_addr)}?subject=stop%20reminders>"
        m.set_content(body)
        try:
            with self._smtp() as c:
                c.send_message(m)
        except smtplib.SMTPAuthenticationError as exc:
            raise AdapterError("The mail server rejected the user name or password. For Gmail use an app password.") from exc
        except ssl.SSLCertVerificationError as exc:
            raise AdapterError(f"The certificate of {self.settings.smtp_host} could not be verified, so nothing was sent. Check SMTP_HOST and the port.") from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise AdapterError(f"Could not send through {self.settings.smtp_host}: {type(exc).__name__}.") from exc
        return m["Message-ID"]

    def healthcheck(self) -> tuple[bool, str]:
        try:
            self._need("smtp_host")
            with self._smtp() as c:
                c.noop()
            return True, "Connected to the mail server."
        except AdapterError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, f"Could not connect: {type(exc).__name__}."
