"""Load the data a real install starts with, from the command line. It uses the same functions as the API (`booklantern/setup_data.py`) and reads the same settings file.

    python tools/load_data.py bank-account "Main account" --currency USD --opening 1250000 --opening-date 2026-01-01   (opening balance in minor units, so cents)
    python tools/load_data.py vendors vendors.csv       columns: name, currency, tax_rate, requires_po, bank_account, terms_days, address
    python tools/load_data.py customers customers.csv   columns: name, email, timezone, terms_days
    python tools/load_data.py invoices invoices.csv     columns: number, customer, issue_date, due_date, total, currency, paid
    python tools/load_data.py account 6200 "Software" expense      one line of the chart of accounts
    python tools/load_data.py recurring "Rent" out 450000 monthly --day 1 --match "LANDLORD"

Add --env-file other.env to read another settings file (default .env, or ENV_FILE). A CSV file is all or nothing: one bad line (named by its number) stops the whole file.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

import _common  # noqa: F401
from booklantern import setup_data
from booklantern.config import Settings
from sendora_core import models as _core  # noqa: F401
from sendora_core.db import Base, make_engine, make_session_factory, session_scope
import booklantern.models  # noqa: F401


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", default=os.environ.get("ENV_FILE", ".env"))
    sub = ap.add_subparsers(dest="what", required=True)
    for name in ("vendors", "customers", "invoices"):
        sub.add_parser(name).add_argument("file", type=Path)
    b = sub.add_parser("bank-account")
    b.add_argument("name")
    b.add_argument("--currency", default="")
    b.add_argument("--opening", type=int, default=0, help="opening balance in minor units (cents)")
    b.add_argument("--opening-date", type=date.fromisoformat, default=None)
    a = sub.add_parser("account")
    a.add_argument("code")
    a.add_argument("name")
    a.add_argument("kind", choices=setup_data.ACCOUNT_KINDS)
    r = sub.add_parser("recurring")
    r.add_argument("name")
    r.add_argument("direction", choices=("in", "out"))
    r.add_argument("amount_minor", type=int)
    r.add_argument("cadence", choices=setup_data.CADENCES)
    r.add_argument("--day", type=int, default=1)
    r.add_argument("--match", default="")
    args = ap.parse_args(argv)

    settings = Settings(_env_file=args.env_file)
    engine = make_engine(settings.database_url)
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    who = "command line"
    try:
        with session_scope(factory) as s:
            if args.what in ("vendors", "customers", "invoices"):
                fn = {"vendors": setup_data.import_vendors, "customers": setup_data.import_customers, "invoices": setup_data.import_invoices}[args.what]
                rep = fn(s, settings, who, args.file.read_text(encoding="utf-8"))
                print(f"OK added {rep.added}, left as they were {len(rep.skipped)}")
            elif args.what == "bank-account":
                x = setup_data.create_bank_account(s, settings, who, name=args.name, currency=args.currency, opening_minor=args.opening, opening_date=args.opening_date)
                print(f"OK bank account {x.id} ({x.currency})")
            elif args.what == "account":
                x = setup_data.create_account(s, who, code=args.code, name=args.name, kind=args.kind)
                print(f"OK account {x.code}")
            else:
                x = setup_data.create_recurring(s, who, name=args.name, direction=args.direction, amount_minor=args.amount_minor, cadence=args.cadence, day=args.day, match_text=args.match)
                print(f"OK repeating item {x.id}")
    except (setup_data.SetupError, OSError) as exc:
        print("PROBLEM", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
