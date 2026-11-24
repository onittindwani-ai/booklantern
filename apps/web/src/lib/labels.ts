import type { BadgeTone } from "@sendora/ui-kit";

export const FINDING: Record<string, { label: string; help: string }> = {
  wrong_total: { label: "Total does not add up", help: "Subtotal plus tax is not the total printed on the bill." },
  wrong_tax: { label: "Tax differs from the rate", help: "The tax on the bill is not the printed (or usual) rate times the subtotal. A comparison only, not tax advice." },
  due_date_assumed: { label: "Due date assumed", help: "The bill shows no due date, so the bill date plus the vendor terms (net 30 by default) was used." },
  missing_fx_rate: { label: "No exchange rate", help: "This amount is in another currency and no rate has been entered, so it is left out of totals, aging and the forecast." },
  line_sum_mismatch: { label: "Lines do not add up", help: "The line amounts do not sum to the subtotal." },
  duplicate_exact: { label: "Exact duplicate", help: "Same vendor, number, date and amount as another bill." },
  duplicate_near: { label: "Possible duplicate", help: "Same vendor and amount as another bill, with a very similar number and date." },
  amount_far_above_history: { label: "Far above usual", help: "Much larger than this vendor's usual bill." },
  bank_detail_changed: { label: "Bank details changed", help: "The bank account is not the one on file. Phone the vendor before paying." },
  missing_po: { label: "No purchase order", help: "This vendor's bills need a PO number." },
  currency_mismatch: { label: "Unexpected currency", help: "Not the currency this vendor is usually paid in." },
  future_date: { label: "Date in the future", help: "The bill is dated after today." },
  wrong_company: { label: "Addressed to someone else", help: "The bill is not addressed to your company." },
  unknown_vendor: { label: "Unknown vendor", help: "No vendor on the list matches." },
  unreadable_document: { label: "Could not read it", help: "The page is a picture. Key the fields by hand." },
  low_confidence: { label: "Low confidence", help: "At least one field is unsure." },
  possible_duplicate_line: { label: "Duplicate bank line", help: "An identical line comes earlier in the file." },
  unmatched_line: { label: "Bank line not matched", help: "Nothing fits this line." },
};
export const finding = (k: string) => FINDING[k] ?? { label: k.replace(/_/g, " "), help: "" };
export const sevTone = (s: string): BadgeTone => (s === "block" ? "danger" : s === "warning" ? "warning" : "neutral");

export const BILL_STATE: Record<string, { label: string; tone: BadgeTone }> = {
  inbox: { label: "New", tone: "neutral" }, needs_review: { label: "Needs review", tone: "warning" }, approved: { label: "Approved", tone: "accent" },
  posted_draft: { label: "Posted as draft", tone: "success" }, paid: { label: "Paid", tone: "success" }, rejected: { label: "Rejected", tone: "neutral" },
};
export const FIELD_LABEL: Record<string, string> = {
  vendor: "Vendor", number: "Bill number", issue_date: "Bill date", due_date: "Due date", po: "PO number", bill_to: "Addressed to", currency: "Currency", subtotal_minor: "Subtotal", tax_minor: "Tax", tax_rate_bp: "Tax rate", total_minor: "Total", bank_account: "Bank account",
};
export const confWord = (c: number) => (c >= 80 ? "sure" : c >= 50 ? "check" : "unsure");
export const confTone = (c: number): BadgeTone => (c >= 80 ? "success" : c >= 50 ? "warning" : "danger");
export const REASON: Record<string, string> = { block: "Blocking", warning: "Warning", info: "Info" };
export const STOP: Record<string, string> = {
  paid: "Paid", opt_out: "Asked for no reminders", bankruptcy: "Bankruptcy flag", dispute: "In dispute", promise_pending: "Promise to pay pending", max_count: "All reminders sent", kill_switch: "Kill switch is on",
  not_due_yet: "Next step not due yet", min_gap: "Waiting between reminders", quiet_hours: "Waiting for send hours", due: "Reminder is due",
};
export const stop = (r: string) => STOP[r] ?? r.replace(/_/g, " ");

export const AUDIT_ACTION: Record<string, string> = {
  "bank.imported": "Bank statement imported", "bill.approved": "Bill approved", "bill.created": "Bill read and added", "bill.edited": "Bill corrected", "bill.post_skipped": "Posting to accounting skipped",
  "bill.posted_draft": "Bill posted as a draft", "bill.rejected": "Bill rejected", "customer.opt_out": "Reminder opt out changed", "document.uploaded": "Document uploaded", "exception.resolved": "Finding closed",
  "fx_rate.set": "Exchange rate saved", "invoice.dispute": "Dispute changed", "match.confirmed": "Match confirmed", "match.manual": "Bank line linked by a person", "match.removed": "Match removed",
  "payment_link.created": "Payment link made", "promise.recorded": "Promise to pay recorded", "reminder.approved": "Reminder approved", "reminder.cancelled": "Reminder cancelled", "reminder.sent": "Reminder sent",
  "settings.force_draft": "Draft mode changed", "settings.kill_switch": "Kill switch changed", "approval.requested": "Approval asked for", "approval.approved": "Approval granted", "approval.rejected": "Approval refused",
};
/** "bill.post_skipped" becomes "Posting to accounting skipped"; anything not in the list is still made readable. */
export const auditAction = (a: string): string => AUDIT_ACTION[a] ?? (a.replace(/[._]/g, " ").replace(/^./, (c) => c.toUpperCase()));
/** "bill:73" becomes "Bill 73". */
export const auditTarget = (t: string | null): string => (t ? t.replace(/[_]/g, " ").replace(":", " ").replace(/^./, (c) => c.toUpperCase()) : "");
