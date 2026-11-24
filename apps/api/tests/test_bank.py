import pytest

from booklantern import bankcsv, bankservice, reconcile as RC
from booklantern.models import BankAccount, BankTransaction, Bill, Customer, ExceptionItem, Invoice, Match
from datetime import date

CSV = "Date,Description,Amount,Currency,Reference\n2026-03-01,ACH FEE,-25.00,USD,\n2026-03-01,ACH FEE,-25.00,USD,\n2026-03-02,ACH CREDIT PINEWOOD VETERINARY INV-2027,9070.00,USD,\n"


def test_csv_header_and_value_errors():
    with pytest.raises(bankcsv.CsvError):
        bankcsv.parse("Foo,Bar\n1,2\n")
    with pytest.raises(bankcsv.CsvError):
        bankcsv.parse("Date,Description,Amount\n03/01/2026,x,1.00\n")
    with pytest.raises(bankcsv.CsvError):
        bankcsv.parse("Date,Description,Amount\n2026-03-01,x,abc\n")
    assert bankcsv.parse("﻿date,description,amount\n2026-03-01,x,1.00\n")[0].amount_minor == 100  # any column order and case, with a byte order mark


def test_identical_rows_in_one_file_are_kept_and_the_later_one_is_flagged():
    rows = bankcsv.parse(CSV)
    assert len(rows) == 3 and [r.possible_duplicate for r in rows] == [False, True, False]
    assert rows[0].row_hash != rows[1].row_hash


def test_the_same_file_twice_adds_nothing(ctx):
    from booklantern.seeding import load_seed
    with ctx.factory() as s:
        s.add(BankAccount(name="x", currency="USD", opening_minor=0, opening_date=date(2026, 1, 1))); s.flush()
        a = bankservice.import_csv(s, CSV, "b1")
        b = bankservice.import_csv(s, CSV, "b2")
        assert a == {"added": 3, "skipped_already_imported": 0, "possible_duplicates": 1}
        assert b == {"added": 0, "skipped_already_imported": 3, "possible_duplicates": 0}
        assert s.query(BankTransaction).count() == 3
        assert s.query(ExceptionItem).filter_by(kind="possible_duplicate_line").count() == 1
        assert bankservice.balance(s) == -25 * 100 * 2 + 907000


def test_exact_amounts_and_names_match_and_a_split_is_found():
    inv = [RC.Target("invoice", 1, "INV-1", "Marlowe Bakery", 10000, date(2026, 1, 1), date(2026, 1, 31)), RC.Target("invoice", 2, "INV-2", "Marlowe Bakery", 5000, date(2026, 2, 1), date(2026, 2, 28)),
           RC.Target("invoice", 3, "INV-3", "Oakridge Builders", 10000, date(2026, 1, 1), date(2026, 1, 31))]
    t = [RC.Txn(1, date(2026, 2, 5), "ACH CREDIT MARLOWE BKRY INV-1", 10000), RC.Txn(2, date(2026, 3, 1), "WIRE IN MARLOWE BAKERY", 5000), RC.Txn(3, date(2026, 3, 2), "UNKNOWN REMITTER", 777)]
    r = {x.txn_id: x for x in RC.match_all(t, inv, [])}
    assert r[1].outcome == "matched" and r[1].links[0].id == 1
    assert r[2].outcome in ("matched", "suggested") and r[2].links[0].id == 2
    assert r[3].outcome == "unmatched"
    split = RC.match_all([RC.Txn(1, date(2026, 3, 1), "WIRE IN MARLOWE BAKERY", 15000)], inv, [])[0]
    assert split.outcome == "matched" and sorted(l.id for l in split.links) == [1, 2] and sum(l.allocated_minor for l in split.links) == 15000


def test_allocations_never_exceed_the_line_or_the_document_property():
    import random
    rng = random.Random(4)
    for _ in range(300):
        tg = [RC.Target("invoice", i, f"INV-{i}", "Acme Corp", rng.randint(100, 5000), date(2026, 1, 1), date(2026, 2, 1)) for i in range(1, 6)]
        tx = [RC.Txn(i, date(2026, 2, 10 + i), f"ACH CREDIT ACME CORP INV-{rng.randint(1, 5)}", rng.randint(100, 9000)) for i in range(1, 6)]
        out = RC.match_all(tx, tg, [])
        used: dict[int, int] = {}
        for res, t in zip(sorted(out, key=lambda x: x.txn_id), sorted(tx, key=lambda x: x.id)):
            assert sum(l.allocated_minor for l in res.links) <= t.amount_minor
            for l in res.links:
                used[l.id] = used.get(l.id, 0) + l.allocated_minor
        assert all(used[k] <= next(x.open_minor for x in tg if x.id == k) for k in used)


def test_manual_link_is_capped(seeded):
    with seeded.factory() as s:
        t = s.query(BankTransaction).filter_by(status="exception").first()
        inv = s.query(Invoice).filter_by(status="open").first()
        with pytest.raises(ValueError):
            bankservice.link_manually(s, t.id, "invoice", inv.id, abs(t.amount_minor) + 1, "tester")
        m = bankservice.link_manually(s, t.id, "invoice", inv.id, min(abs(t.amount_minor), 1), "tester")
        assert m.status == "confirmed" and t.status == "matched"
        bankservice.unlink(s, m.id, "tester")
        assert t.status == "unmatched"
