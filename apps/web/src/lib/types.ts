export interface FxRateUsed { currency: string; rate: string; rate_date: string | null; stale: boolean }
export interface FxItem { kind: string; id: number; label: string; original_minor: number; original_currency: string; base_minor: number; base_currency: string; rate: string; rate_date: string | null; converted: boolean; stale: boolean }
export interface FxMissing { kind: string; id: number; label: string; original_minor: number; original_currency: string; reason: string; detail: string }
/** What was converted into the company currency to build a number, and what was left out because no rate exists. */
export interface FxInfo { base: string; converted_count: number; missing_count: number; rates_used: FxRateUsed[]; converted?: FxItem[]; missing?: FxMissing[] }
/** Next to one amount in another currency: the converted amount with its rate and date, or a no rate flag. Null for the company currency. */
export interface RowFx { converted: boolean; missing: boolean; original_minor: number; original_currency: string; base_minor?: number; base_currency: string; rate?: string; rate_date?: string | null; stale?: boolean }
export interface FxRateRow { id: number; currency: string; rate_date: string; rate: string; note: string; entered_by: string }
export interface Me { user: string; role: "owner" | "approver" | "viewer"; demo_mode: boolean }
export interface Settings { mode: string; effective_mode: string; kill_switch: boolean; demo_mode: boolean; problems: string[]; accounting_write: boolean; company: string; currency: string; window: string; llm: string; extractor: string; collection_prob_bp: Record<string, number> }
export interface Overview {
  as_of: string; currency: string; cash_minor: number; receivable_minor: number; overdue_minor: number; payable_minor: number; bills_to_review: number; open_invoices: number; unmatched_lines: number; open_exceptions: number;
  low_point_minor: number; low_point_week: number; runs_out_in_week: number | null; pending_approvals: number; demo_mode: boolean; fx: FxInfo;
}
export interface Week { index: number; start: string; receipts_minor: number; new_sales_minor: number; bills_minor: number; recurring_in_minor: number; recurring_out_minor: number; other_minor: number; net_minor: number; opening_minor: number; closing_minor: number }
export interface Forecast { currency: string; fx: FxInfo; as_of: string; opening_minor: number; weeks: Week[]; closing_minor: number; low_point_minor: number; low_point_week: number; total_receipts_minor: number; beyond_horizon_minor: number; runs_out_in_week: number | null; base_closing: number[]; excluded_receivables: { invoice_id: number; reason: string; minor: number }[] }
export interface Flag { kind: string; severity: string }
export interface BillRow { fx: RowFx | null; id: number; vendor: string; vendor_id: number | null; number: string; issue_date: string | null; due_date: string | null; currency: string; po_number: string; bill_to: string; bank_account: string; subtotal_minor: number; tax_minor: number; total_minor: number; paid_minor: number; status: string; document_id: number | null; flags: Flag[] }
export interface FieldValue { value: string | number | null; confidence: number; box: number[] | null; page: number; label: string; reasons: string[] }
export interface LineRow { id: number; description: string; quantity_milli: number; unit_minor: number; total_minor: number }
export interface BillDetail extends BillRow {
  etag: string; // fingerprint of the bill as loaded: sent back with the approval, which is refused when the bill has changed since
  had_block: boolean; // the bill has carried a blocking finding at some point, even if it was edited away
  self_review: "" | "owner" | "blocked"; // the signed in person changed this bill or closed a finding on it: the owner needs a written reason, anyone else cannot approve it
  lines: LineRow[]; exceptions: { id: number; kind: string; severity: string; detail: string; status: string }[];
  vendor_record: { name: string; bank_account: string; currency: string; tax_rate_bp: number; requires_po: boolean } | null;
  document: { id: number; ref: string; pages: number; readable: boolean; extraction: { extractor: string; readable: boolean; notes: string[]; fields: Record<string, FieldValue>; lines: { description: string; total_minor: number; box: number[] | null }[] } } | null;
}
export interface InvoiceRow { fx: RowFx | null; id: number; number: string; customer: string; customer_id: number; issue_date: string; due_date: string; currency: string; total_minor: number; paid_minor: number; outstanding_minor: number; status: string; disputed: boolean; dispute_note: string; payment_link_url: string; days_late: number; bucket: string }
export interface Aging { currency: string; fx: FxInfo; buckets_minor: Record<string, number>; total_minor: number; customers: { customer_id: number; name: string; buckets_minor: Record<string, number>; total_minor: number }[] }
export interface PlanRow extends InvoiceRow { decision: string; reason: string; next_step: number; next_tone: string; sent: { step: number; tone: string; at: string | null }[] }
export interface ReminderRow { id: number; invoice_id: number; invoice: string; customer: string; step: number; tone: string; status: string; scheduled_for: string; sent_at: string | null; subject: string; body: string; cancel_reason: string }
export interface PromiseRow { id: number; invoice: string; invoice_id: number; customer: string; promised_on: string; amount_minor: number; currency: string; status: string; note: string }
export interface Collections { plan: PlanRow[]; reminders: ReminderRow[]; promises: PromiseRow[]; ladder: { step: number; days_after_due: number; tone: string }[] }
export interface MatchRow { id: number; type: string; number: string; allocated_minor: number; score: number; status: string; reason: string }
export interface BankRow { id: number; ref: string; posted_on: string; description: string; amount_minor: number; currency: string; status: string; matches: MatchRow[] }
export interface BankPage { total: number; balance_minor: number; rows: BankRow[] }
export interface Candidate { kind: "invoice" | "bill"; id: number; number: string; party: string; open_minor: number; due_date: string | null }
export interface ExceptionRow { id: number; kind: string; severity: string; ref_type: string; ref_id: number; detail: string; status: string; created_at: string }
export interface ApprovalRow { id: number; action: string; summary: string; risk: string; status: string; requested_by: string; decided_by: string | null; note: string | null; created_at: string; payload: Record<string, unknown> }
export interface AuditRow { id: number; actor: string; action: string; target: string | null; detail: Record<string, unknown>; at: string }
export interface Integrations { categories: string[]; demo_mode: boolean; adapters: { category: string; name: string; tier: string; live_verified: boolean; notes: string; selected: boolean; env_vars: string[]; configured: boolean }[] }
export interface DocRow { id: number; ref: string; file_name: string; source: string; status: string; pages: number; readable: boolean; received_at: string; bill_id: number | null; extractor: string }
