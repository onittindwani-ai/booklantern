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

from booklantern.adapters.base import InboundDocument, InboundNote, OutcomeUnknown, PermanentFailure, is_loopback
from booklantern.util import clean_header
from sendora_core.adapters import AdapterError
from sendora_core.safety import write_action

ALLOWED = {"application/pdf", "image/png", "image/jpeg"}
MAX_BYTES = 15 * 1024 * 1024  # one attachment
MAX_MESSAGE_BYTES = 25 * 1024 * 1024  # one whole message: a larger one is never loaded into memory
MAX_MESSAGES_PER_POLL = 25  # the rest wait for the next poll
MAX_ATTACHMENTS_PER_MESSAGE = 10
SIZE_RE = re.compile(rb"RFC822\.SIZE\s+(\d+)")
MAX_SKIPPED_MEMORY = 5000  # how many message numbers without a bill the poller remembers, so a mailbox full of other mail never crowds out a bill
NOTE_CHARS = 400


def _watch(c):
    """Make the connection remember that the text of a message was handed to the server (`data_started`). From that moment a lost connection cannot say whether the mail was accepted."""
    c.data_started = False
    real = getattr(c, "data", None)
    if real is not None:
        def data(msg, _real=real):
            c.data_started = True
            return _real(msg)
        c.data = data
    return c


def _goodbye(c) -> None:
    """Say goodbye and close, and ignore every failure: the server has already answered about the message, so trouble while leaving changes nothing about it."""
    for name in ("quit", "close"):
        fn = getattr(c, name, None)
        if fn is not None:
            try:
                fn()
            except Exception:
                pass


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


def _snippet(msg) -> str:
    """The first words of a message's plain text, for a person to see. Any failure gives an empty text: a strange message must never stop the poll."""
    try:
        body = msg.get_body(preferencelist=("plain",))
        return " ".join(((body.get_content() if body is not None else "") or "").split())[:NOTE_CHARS]
    except Exception:
        return ""


class ImapInbox(_Base):
    def __init__(self, settings):
        super().__init__(settings)
        self._skipped: dict[str, None] = {}  # messages looked at that hold no bill. They stay UNREAD in the mailbox (a person reads them); this only stops the poller from fetching them every time
        self._notes: list[InboundNote] = []

    def _skip(self, uid: str) -> None:
        self._skipped[uid] = None
        while len(self._skipped) > MAX_SKIPPED_MEMORY:
            self._skipped.pop(next(iter(self._skipped)))

    def take_notes(self) -> list[InboundNote]:
        """The messages without a bill that were seen since the last call, once each. The mailbox still holds them as unread."""
        out, self._notes = self._notes, []
        return out

    def fetch_documents(self) -> list[InboundDocument]:
        """Attachments of unread messages (at most MAX_MESSAGES_PER_POLL messages). The messages stay unread until `acknowledge` is called with the `ack` of each document.
        A message with no bill in it (too large, no PDF or image attachment) is NOT marked read: it may be a customer's answer to a reminder, which a person must see. It is
        remembered here so it is not fetched again and again, and its sender and first words are handed over by `take_notes`."""
        self._need("imap_host", "smtp_user")
        out: list[InboundDocument] = []
        try:
            c = self._imap()
            try:
                c.select("INBOX")
                _, data = c.uid("SEARCH", None, "UNSEEN")
                fresh = [u.decode() for u in (data[0] or b"").split() if u.decode() not in self._skipped]
                for uid in fresh[:MAX_MESSAGES_PER_POLL]:
                    _, size_parts = c.uid("FETCH", uid, "(RFC822.SIZE)")
                    size = _size_of(size_parts)
                    if size is not None and size > MAX_MESSAGE_BYTES:
                        self._skip(uid)  # too large to load: left unread, nothing is read from it
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
                        self._skip(uid)  # left unread on purpose
                        self._notes.append(InboundNote(uid, parseaddr(str(msg["From"] or ""))[1], clean_header(str(msg["Subject"] or ""))[:200], _snippet(msg)))
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
            c = _watch(self._smtp())
        except smtplib.SMTPAuthenticationError as exc:
            raise AdapterError("The mail server rejected the user name or password. For Gmail use an app password.") from exc
        except ssl.SSLCertVerificationError as exc:
            raise AdapterError(f"The certificate of {self.settings.smtp_host} could not be verified, so nothing was sent. Check SMTP_HOST and the port.") from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise AdapterError(f"Could not send through {self.settings.smtp_host}: {type(exc).__name__}.") from exc
        try:
            c.send_message(m)
        except smtplib.SMTPRecipientsRefused as exc:
            codes = [int(v[0]) for v in exc.recipients.values()]
            raise (PermanentFailure if codes and all(x >= 500 for x in codes) else AdapterError)(f"The mail server refused the address: {', '.join(str(x) for x in codes)}.") from exc
        except (smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as exc:
            raise (PermanentFailure if exc.smtp_code >= 500 else AdapterError)(f"The mail server answered {exc.smtp_code} and did not accept the message.") from exc
        except ssl.SSLCertVerificationError as exc:
            raise AdapterError(f"The certificate of {self.settings.smtp_host} could not be verified, so nothing was sent. Check SMTP_HOST and the port.") from exc
        except (smtplib.SMTPException, OSError) as exc:
            if c.data_started:  # the text of the mail had gone: the server may have accepted it before the line dropped
                raise OutcomeUnknown(f"The connection to {self.settings.smtp_host} failed after the message was handed over ({type(exc).__name__}), so it is not known whether it was sent.") from exc
            raise AdapterError(f"Could not send through {self.settings.smtp_host}: {type(exc).__name__}.") from exc
        finally:
            _goodbye(c)
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
