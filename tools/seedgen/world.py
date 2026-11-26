"""The sample world: vendors, customers, invoices, payments, bank lines. Deterministic. Everything is sample data."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from booklantern.money import line_total, mul_bp

FX_EUR_USD_BP = 10800  # a sample fixed rate: 1 EUR = 1.0800 USD, used by the seed and by the matcher setting

AS_OF = date(2026, 12, 1)
BANK_START = date(2025, 12, 1)
COMPANY = "Birchfield Supply Co"


@dataclass
class VendorDef:
    key: str
    name: str
    addr: str
    currency: str
    tax_bp: int
    requires_po: bool
    account: str
    terms_days: int
    items: list[tuple[str, int, int]]  # description, unit price minor, quantity milli (usual)


VENDORS = [
    VendorDef("V01", "Alderbank Packaging Ltd", "14 Mill Lane, Sampleford", "USD", 800, False, "SMPL-0101-2201", 30, [("Carton 12x12", 240, 400000), ("Pallet wrap roll", 1895, 6000), ("Bubble sleeve", 65, 900000)]),
    VendorDef("V02", "Brightwater Freight Services", "2 Dock Road, Sampleport", "USD", 0, False, "SMPL-0102-2202", 14, [("Pallet delivery", 18500, 4000), ("Fuel surcharge", 2400, 4000), ("Storage per pallet week", 850, 12000)]),
    VendorDef("V03", "Cobalt Office Supply", "77 Park Row, Sampleford", "USD", 700, True, "SMPL-0103-2203", 30, [("Copy paper case", 3850, 6000), ("Toner cartridge", 11900, 2000), ("Desk organiser", 1450, 5000)]),
    VendorDef("V04", "Dunmore Industrial Parts", "9 Forge Street, Sampleham", "USD", 800, True, "SMPL-0104-2204", 45, [("Hex bolt box of 100", 1250, 20000), ("Bearing 6204", 940, 30000), ("Hydraulic hose 2m", 3600, 8000)]),
    VendorDef("V05", "Eastgate Cleaning Co", "31 East Gate, Sampleford", "USD", 0, False, "SMPL-0105-2205", 15, [("Weekly office clean", 28000, 4000), ("Window clean", 9500, 1000)]),
    VendorDef("V06", "Fernhill IT Support", "5 Fern Hill, Sampleham", "USD", 1000, False, "SMPL-0106-2206", 30, [("Support hours", 9500, 9000), ("Remote monitoring licence", 4900, 5000)]),
    VendorDef("V07", "Gablemere Print Studio", "Gablemere Weg 3, Samplestadt", "EUR", 1900, False, "SMPL-0107-2207", 30, [("Flyer print run of 500", 7200, 4000), ("Roll up banner", 14500, 2000)]),
    VendorDef("V08", "Hollin Insurance Brokers", "100 Cover Street, Sampleford", "USD", 0, False, "SMPL-0108-2208", 30, [("Premium instalment", 42000, 1000), ("Admin fee", 1500, 1000)]),
]


@dataclass
class CustomerDef:
    key: str
    name: str
    email: str
    tz: str
    terms_days: int
    habit_days: int  # how many days after the due date this customer usually pays (negative means early)
    flag: str = ""  # bankruptcy, opt_out, dispute


CUSTOMERS = [
    CustomerDef("C01", "Marlowe Bakery", "ap@marlowe-bakery.example.test", "America/New_York", 30, 2),
    CustomerDef("C02", "Northgate Dental Group", "billing@northgate-dental.example.test", "America/Chicago", 30, 9),
    CustomerDef("C03", "Oakridge Builders", "accounts@oakridge-builders.example.test", "America/Denver", 30, 38, "bankruptcy"),
    CustomerDef("C04", "Pinewood Veterinary", "office@pinewood-vet.example.test", "America/Los_Angeles", 15, -1),
    CustomerDef("C05", "Quayside Cafe", "hello@quayside-cafe.example.test", "America/New_York", 15, 14, "opt_out"),
    CustomerDef("C06", "Ravenscroft Legal", "finance@ravenscroft-legal.example.test", "America/New_York", 45, 6),
    CustomerDef("C07", "Stonebridge Gym", "admin@stonebridge-gym.example.test", "America/Chicago", 30, 21),
    CustomerDef("C08", "Tallow and Wick Candles", "pay@tallow-wick.example.test", "America/Los_Angeles", 30, 4),
    CustomerDef("C09", "Underhill Garage", "office@underhill-garage.example.test", "America/Denver", 30, 17, "dispute"),
    CustomerDef("C10", "Vesper Florists", "books@vesper-florists.example.test", "America/New_York", 30, 11),
]


def workday(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


@dataclass
class World:
    rng: random.Random
    invoices: list[dict] = field(default_factory=list)  # AR
    payments: list[dict] = field(default_factory=list)  # receipts: invoice numbers, amounts, date
    bills_hist: list[dict] = field(default_factory=list)
    bank: list[dict] = field(default_factory=list)
    recurring: list[dict] = field(default_factory=list)
    promises: list[dict] = field(default_factory=list)
    reminders: list[dict] = field(default_factory=list)
    key: dict = field(default_factory=dict)  # reconciliation answer key


def _vendor_bill_lines(v: VendorDef, rng: random.Random, target_minor: int | None = None):
    for _ in range(200):
        picks = rng.sample(v.items, k=min(len(v.items), rng.choice([1, 2, 2, 3])))
        lines = []
        for desc, unit, q in picks:
            q_use = max(1000, int(q * rng.choice([0.5, 0.75, 1.0, 1.0, 1.25, 1.5])) // 1000 * 1000) if q >= 4000 else q
            lines.append((desc, q_use, unit, line_total(q_use, unit)))
        sub = sum(x[3] for x in lines)
        if target_minor is None or 0.6 * target_minor <= sub <= 1.6 * target_minor:
            return lines
    return lines


def build_world(seed: int = 20261201) -> World:
    rng = random.Random(seed)
    w = World(rng)
    # vendor history: 6 paid bills each, monthly, oldest first
    n = 5000
    for v in VENDORS:
        base = None
        for i in range(6):
            issue = date(2026, 5, 10) + timedelta(days=30 * i + rng.randint(-2, 2))
            lines = _vendor_bill_lines(v, rng, base)
            sub = sum(x[3] for x in lines)
            base = base or sub
            tax = mul_bp(sub, v.tax_bp)
            n += 1
            due = issue + timedelta(days=v.terms_days)
            w.bills_hist.append({"vendor": v.key, "number": f"{v.key[1:]}-{n}", "issue": issue.isoformat(), "due": due.isoformat(), "currency": v.currency,
                                 "subtotal_minor": sub, "tax_minor": tax, "total_minor": sub + tax, "paid_on": workday(due).isoformat()})
    _customers_and_bank(w)
    return w


def _customers_and_bank(w: World) -> None:
    rng = w.rng
    num = 2000
    cust = {c.key: c for c in CUSTOMERS}
    for c in CUSTOMERS:
        for m in range(12):
            if rng.random() > 0.72 and not (m >= 10):
                continue
            issue = date(2025, 12, 1) + timedelta(days=30 * m + rng.randint(0, 20))
            if issue > AS_OF - timedelta(days=3):
                continue
            total = rng.choice([126000, 180500, 354000, 468000, 675000, 960000, 1358000]) + rng.randint(0, 99) * 100
            num += 1
            due = issue + timedelta(days=c.terms_days)
            pay = workday(due + timedelta(days=c.habit_days + rng.randint(-2, 3)))
            paid = pay < AS_OF and not (issue > AS_OF - timedelta(days=110) and rng.random() < 0.55)
            w.invoices.append({"customer": c.key, "number": f"INV-{num}", "issue": issue.isoformat(), "due": due.isoformat(), "currency": "USD", "total_minor": total,
                               "tax_minor": mul_bp(total, 0), "paid_minor": total if paid else 0, "paid_on": pay.isoformat() if paid else None, "status": "paid" if paid else "open", "flag": ""})
    open_inv = [i for i in w.invoices if i["status"] == "open"]
    # bankruptcy customer: nothing of theirs is paid after a point, mark every open one
    # promises: two kept in the future, one broken
    overdue = sorted([i for i in open_inv if i["due"] < AS_OF.isoformat() and cust[i["customer"]].flag == ""], key=lambda i: i["due"])
    for k, (inv, days, state) in enumerate(zip(overdue[:3], (5, 12, -6), ("open", "open", "broken"))):
        w.promises.append({"invoice": inv["number"], "promised_on": (AS_OF + timedelta(days=days)).isoformat(), "amount_minor": inv["total_minor"], "status": state})
    # disputes: one for the dispute customer, one more
    disp = [i for i in open_inv if cust[i["customer"]].flag == "dispute"][:1] + [i for i in open_inv if i["customer"] == "C06"][:1]
    for i in disp:
        i["flag"] = "dispute"
    # partial payments on two open invoices
    for inv in [i for i in open_inv if i["flag"] == "" and cust[i["customer"]].flag == "" and i["number"] not in {p["invoice"] for p in w.promises}][:2]:
        inv["paid_minor"] = inv["total_minor"] // 2
        inv["partial_on"] = (AS_OF - timedelta(days=9)).isoformat()
    _bank(w, cust)


def _desc_receipt(c: CustomerDef, inv_numbers: list[str], rng: random.Random, i: int) -> str:
    name = c.name.upper()
    style = i % 5
    if style == 0:
        return f"ACH CREDIT {name} {inv_numbers[0]}"
    if style == 1:
        return f"WIRE IN {name.replace(' BAKERY', ' BKRY').replace(' GROUP', ' GRP')}"
    if style == 2:
        return f"ACH CREDIT {name.split()[0]} PAYMENT REF {inv_numbers[0].replace('INV-', '')}"
    if style == 3:
        return f"DEPOSIT {name[:-1]} INV {inv_numbers[0]}"
    return f"ACH CREDIT {name}"


def _bank(w: World, cust: dict) -> None:
    rng = w.rng
    seq = 0
    cm = {c.key: c for c in CUSTOMERS}
    vm = {v.key: v for v in VENDORS}

    def add(d: str, desc: str, amount: int, kind: str, targets: list[dict]) -> str:
        nonlocal seq
        seq += 1
        ref = f"T{seq:04d}"
        w.bank.append({"ref": ref, "date": d, "description": desc, "amount_minor": amount, "currency": "USD"})
        w.key[ref] = {"kind": kind, "targets": targets}
        return ref

    # receipts for paid invoices, merging two splits
    paid = sorted([i for i in w.invoices if i["paid_on"] and not i.get("partial_on")], key=lambda i: i["paid_on"])
    used: set[str] = set()
    splits = 0
    for idx, inv in enumerate(paid):
        if inv["number"] in used:
            continue
        c = cm[inv["customer"]]
        group = [inv]
        if splits < 2 and idx % 11 == 3:
            mate = next((j for j in paid[idx + 1:] if j["customer"] == inv["customer"] and j["number"] not in used and abs((date.fromisoformat(j["paid_on"]) - date.fromisoformat(inv["paid_on"])).days) <= 40), None)
            if mate:
                group.append(mate); splits += 1
        for g in group:
            used.add(g["number"])
        d = max(g["paid_on"] for g in group)
        amount = sum(g["total_minor"] for g in group)
        for g in group:
            g["paid_on"] = d
        add(d, _desc_receipt(c, [g["number"] for g in group], rng, idx), amount, "split" if len(group) > 1 else "invoice", [{"type": "invoice", "number": g["number"], "amount_minor": g["total_minor"]} for g in group])
    for inv in [i for i in w.invoices if i.get("partial_on")]:
        add(inv["partial_on"], f"ACH CREDIT {cm[inv['customer']].name.upper()} PART PAYMENT", inv["paid_minor"], "invoice", [{"type": "invoice", "number": inv["number"], "amount_minor": inv["paid_minor"]}])
    # vendor payments
    for k, b in enumerate(w.bills_hist):
        v = vm[b["vendor"]]
        if b["paid_on"] >= AS_OF.isoformat():
            continue
        amt = b["total_minor"] if v.currency == "USD" else mul_bp(b["total_minor"], FX_EUR_USD_BP)  # EUR bills are paid in dollars at a fixed sample rate
        tail = f" {b['number']}" if k % 3 else ""
        add(b["paid_on"], f"ACH DEBIT {v.name.upper()}{tail}", -amt, "bill", [{"type": "bill", "number": b["number"], "amount_minor": amt}])
    # recurring
    rec = [("Rent", "RENT MILLSIDE PROPERTIES", -320000, 1), ("Payroll", "PAYROLL BATCH", -650000, 15), ("Payroll", "PAYROLL BATCH", -650000, 28), ("Software subscription", "SOFTLAB SUBSCRIPTION", -28900, 5), ("Bank fee", "MONTHLY ACCOUNT FEE", -2500, 27)]
    for name, desc, amt, day in rec:
        for m in range(12):
            yy, mm = (2025 + (11 + m) // 12, (11 + m) % 12 + 1)
            d = workday(date(yy, mm, day))
            if d < AS_OF:
                add(d.isoformat(), desc, amt, "recurring", [{"type": "recurring", "name": name}])
    w.recurring = [{"name": n, "direction": "out", "amount_minor": -a, "cadence": "monthly", "day": d, "match": desc} for n, desc, a, d in {r[0]: r for r in rec}.values() if n != "Payroll"] + \
                  [{"name": "Payroll", "direction": "out", "amount_minor": 650000, "cadence": "twice_monthly", "day": 15, "match": "PAYROLL BATCH"}]
    # planted problems: duplicate lines, unmatched lines
    base = [b for b in w.bank]
    for src in (base[10], base[60], base[140]):
        ref = add(src["date"], src["description"], src["amount_minor"], "duplicate", [])
        w.key[ref]["duplicate_of"] = src["ref"]
    add("2026-03-18", "ACH CREDIT UNKNOWN REMITTER 8841", 41000, "none", [])
    add("2026-07-09", "CASH DEPOSIT BRANCH 02", 126500, "none", [])
    add("2026-09-21", "POS PURCHASE HARDWARE WORLD 0442", -8735, "none", [])
    w.bank.sort(key=lambda t: (t["date"], t["ref"]))
