"""The words a bill uses for its fields, in the languages a small business meets most (English, German, French, Spanish, Italian, Dutch, Portuguese, Polish, Japanese).

General vocabulary only. It is matched on text folded to lower case without accents. Nothing here comes from any test set; the old self written held out set
is spent (see docs/EXTRACTION-EVAL.md). A word that is wrong here shows up as a field the reader does not find, and then as a low confidence note for a person.
"""

from __future__ import annotations

import re

from booklantern.extraction.dates import fold

_VAL = r"(?=\s*$|\s+\d|\s+[^\W\d]{3,9}\.?\s+\d)"  # the label may be followed by its date with no colon

NUMBER = [r"^(?:tax\s+)?invoice\s*(?:no\b|number\b|nr\b|num\b|#)", r"^inv\.?\s*(?:no\b|#|number)", r"^number$", r"^(?:credit\s+(?:note|memo)|document|receipt|bill|statement)\s*(?:no\b|number\b|nr\b|#)",
          r"^rechnungs?\s*(?:nr|nummer|-nr)", r"^rechnung\s*nr", r"^(?:facture|fattura|factura|factuur|faktura|fatura)\s*(?:no|n°|nº|n\.|nr|num|numero|numer|numéro|número)",
          r"^(?:numero|numéro|número|numer|nummer)\s*(?:de |di |da )?(?:facture|fattura|factura|factuur|faktura|fatura|rechnung)", r"^(?:facture|fattura|factura|factuur|faktura|fatura)\s*:?$",
          r"^gutschrift\s*(?:nr|nummer)", r"^请求书番号|^請求書番号|^請求書no", r"^no\.?\s*(?:de )?(?:facture|factura)"]
ISSUE = [r"^(?:invoice|bill|document)\s*date", r"^date\s*of\s*(?:invoice|issue)", r"^issue\s*date", r"^issued(?:\s*on)?$", r"^date" + _VAL, r"^dated" + _VAL, r"^rechnungsdatum", r"^ausstellungsdatum", r"^datum" + _VAL, r"^belegdatum",
         r"^date\s*(?:de\s*)?(?:la\s*)?(?:facture|emission|d'emission)", r"^fecha(?:\s*(?:de\s*)?(?:factura|emision|expedicion))?$", r"^data(?:\s*(?:della\s*)?(?:fattura|emissione|documento))?$", r"^factuurdatum",
         r"^datum\s*factuur", r"^data\s*wystawienia", r"^data\s*(?:de\s*)?(?:emissao|fatura)", r"^請求日", r"^発行日", r"^invoice\s*dated"]
DUE = [r"^due(?:\s*date|\s*on)?" + _VAL, r"^payment\s*due", r"^pay(?:able)?\s*by", r"^settle\s*by", r"^to\s*be\s*paid\s*by", r"^due\s*by", r"^falligkeit\w*", r"^zahlbar\s*bis", r"^zahlungsziel", r"^zahlbar\s*(?:bis|am)",
       r"^echeance", r"^date\s*d'?echeance", r"^vencimiento", r"^fecha\s*de\s*vencimiento", r"^scadenza", r"^data\s*(?:di\s*)?scadenza", r"^vervaldatum", r"^te\s*betalen\s*voor", r"^termin\s*platnosci",
       r"^vencimento", r"^data\s*de\s*vencimento", r"^支払期限", r"^支払期日", r"^お支払期限", r"^payment\s*date\s*due", r"^pay\s*before"]
PO = [r"^po\s*(?:number|no\b|#|ref)", r"^p\.?o\.?\s*(?:number|no\b|#)?$", r"^purchase\s*order", r"^customer\s*po", r"^your\s*(?:order|po|ref)", r"^order\s*(?:no|number|ref|#)", r"^bestell(?:nummer|nr|ung)",
      r"^commande", r"^n°\s*commande", r"^orden\s*de\s*compra", r"^ordine", r"^bestelnummer", r"^numer\s*zamowienia", r"^nota\s*de\s*encomenda"]
BILL_TO = [r"^bill(?:ed)?\s*to", r"^invoice\s*to", r"^sold\s*to", r"^customer$", r"^client$", r"^buyer", r"^rechnung\s*an", r"^rechnungsempfanger", r"^kunde$", r"^facture\s*a", r"^facturado\s*a", r"^cliente$",
           r"^fatturato\s*a", r"^factuuradres", r"^klant$", r"^nabywca", r"^faturado\s*a", r"^請求先", r"^to:?$", r"^attention", r"^customer\s*name", r"^bill\s*recipient", r"^account\s*name"]
SELLER = [r"^seller", r"^from:?$", r"^supplier", r"^vendor", r"^issued\s*by", r"^verkaufer", r"^lieferant", r"^fournisseur", r"^proveedor", r"^fornitore", r"^leverancier", r"^sprzedawca", r"^fornecedor"]
FIELD_LABELS = {"number": NUMBER, "issue_date": ISSUE, "due_date": DUE, "po": PO, "bill_to": BILL_TO, "seller": SELLER}

# row labels in the totals area
_EXCLUDE = r"\b(?:tax\s*(?:id|no|number|invoice|point|code|reg)|vat\s*(?:no|number|id|reg|code)|gst\s*(?:no|number|reg)|abn|ust-?id|steuernummer|iva\s*n|nip\b|reg(?:istration)?\s*(?:no|number)|company\s*no|" \
           r"brought\s*forward|carried\s*forward|previous|prior|balance\s*b/?f|balance\s*c/?f|page\s*total|deposit|paid|payment\s*received|amount\s*paid|statement|account\s*summary|open\s*items?|overdue|outstanding|" \
           r"saldo\s*anterior|report|uebertrag|ubertrag|vortrag)\b"
_SUB = r"(?:\bsub\s*-?\s*total|\bnet\s*(?:total|amount|sum|value)\b|\btotal\s*net\b|\btotal\s*(?:excl|ex|before|without|net)\w*|\b(?:excl|ex|before|without)\.?\s*(?:vat|tax|gst|iva|tva)|^net$|\bnet\s*:|" \
       r"zwischensumme|nettobetrag|netto\b|summe\s*netto|gesamt\s*netto|\btotal\s*ht\b|montant\s*ht|\bht\b|sous-?total|base\s*imponible|imponibile|subtotaal|netto\b|wartosc\s*netto|razem\s*netto|valor\s*liquido|total\s*sem\s*iva|sin\s*iva|小計|税抜)"
_TAXWORD = r"\b(?:vat|tax|gst|hst|pst|qst|cgst|sgst|igst|utgst|mwst|mwst\.|ust|umsatzsteuer|steuer|tva|iva|btw|moms|mva|podatek|ptu|消費税)\b|税"
_TAXTOTAL = r"(?:totale?\s*(?:vat|tax|gst|iva|tva|mwst|btw)|(?:vat|tax|gst|iva|tva|mwst|btw)\s*(?:total|amount|gesamt)|summe\s*(?:mwst|ust|steuer)|total\s*taxes?|tax\s*total)"
_TOTAL = r"(?:total\s*(?:due|payable|amount|invoice|to\s*pay|incl\w*|inc\.?|ttc|general|geral|a\s*pagar|fattura|fatura)?|amount\s*(?:due|payable)|balance\s*(?:due|payable)|grand\s*total|invoice\s*total|" \
         r"to\s*pay|gesamtbetrag|gesamtsumme|rechnungsbetrag|endbetrag|zu\s*zahlen|zahlbetrag|bruttobetrag|brutto\b|summe|net\s*a\s*payer|montant\s*ttc|total\s*a\s*pagar|importe\s*total|totale|da\s*pagare|totaal|te\s*betalen|" \
         r"razem|do\s*zaplaty|ogolem|suma\b|valor\s*total|合計|請求金額|ご請求金額|請求額)"


def classify_row(label: str) -> str:
    """'subtotal', 'tax', 'taxtotal', 'total' or '' for the text in front of an amount on a line."""
    t = fold(label).strip(" :.-_")
    if not t or len(t) > 60 or re.search(_EXCLUDE, t):
        return ""
    if re.search(_TAXTOTAL, t):
        return "taxtotal"
    if re.search(_SUB, t):
        return "subtotal"
    if re.fullmatch(r"(?:" + _TOTAL + r")(?:\s*(?:usd|eur|gbp|cad|aud|chf|nok|zar|sgd|inr|pln|jpy|\(.*\)))?\s*(?:incl\w*\.?\s*(?:vat|tax|gst|iva|tva|mwst)?)?", t) or re.match(r"(?:" + _TOTAL + r")\b", t) and not re.search(_TAXWORD, t):
        return "total"
    if re.search(_TAXWORD, t):
        return "tax"
    return ""


def label_field(cell_text: str) -> tuple[str, str] | None:
    """(field, text after the label in the same cell) when a cell starts with a field label. A colon ends the label."""
    raw = cell_text.strip()
    head, sep, tail = raw.partition(":")
    for label, inline in ((head, tail.strip()), (raw, "")) if sep else ((raw, ""),):
        t = fold(label).strip(" .")
        for name, pats in FIELD_LABELS.items():
            for p in pats:
                m = re.search(p, t)
                if m:
                    if inline or sep:
                        return name, inline
                    return name, " ".join(raw.split()[len(label.split()) - len(t[m.end():].split()):]) if t[m.end():].strip() else ""
    return None


CREDIT_RE = re.compile(r"credit\s*(?:note|memo)|gutschrift|\bavoir\b|nota\s*de\s*credito|nota\s*di\s*credito|creditnota|faktura\s*korygujaca|貸方|nota\s*de\s*credito", re.I)
TITLE_RE = re.compile(r"invoice|rechnung|facture|factura|fattura|factuur|faktura|fatura|receipt|credit\s*note|gutschrift|statement|pro\s*forma|bill\b|請求書|tax\s*invoice|page\s*\d|^\W*$", re.I)
