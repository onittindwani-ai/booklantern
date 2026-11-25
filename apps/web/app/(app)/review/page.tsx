"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { Badge, Button, Card, ConfirmDialog, EmptyState, Field, notify } from "@sendora/ui-kit";
import { DocViewer, type Box } from "@/components/DocViewer";
import { ListSkeleton, LoadError, PageHead } from "@/components/Parts";
import { get, post, api } from "@/lib/api";
import { useRole } from "@/lib/hooks";
import { BILL_STATE, FIELD_LABEL, confTone, confWord, finding, sevTone } from "@/lib/labels";
import { money, moneyIn } from "@/lib/money";
import type { BillDetail, BillRow, FieldValue } from "@/lib/types";

const MONEY = new Set(["subtotal_minor", "tax_minor", "total_minor"]);
const ORDER = ["vendor", "number", "issue_date", "due_date", "po", "bill_to", "currency", "subtotal_minor", "tax_minor", "total_minor", "bank_account"];
const PATCH: Record<string, string> = { vendor: "vendor", number: "number", issue_date: "issue_date", due_date: "due_date", po: "po_number", bill_to: "bill_to", currency: "currency", bank_account: "bank_account", subtotal_minor: "subtotal_minor", tax_minor: "tax_minor", total_minor: "total_minor" };

function toMinor(text: string): number | null { const t = text.replace(/[^0-9.\-]/g, ""); if (!/^-?\d+(\.\d{1,2})?$/.test(t)) return null; const [w, f = ""] = t.split("."); return Number(w) * 100 + Math.sign(Number(w) || 1) * Number((f + "00").slice(0, 2)); }
/** A plain sentence when a typed value cannot be saved, or null when it is fine. Checked before anything is sent. */
function fieldProblem(k: string, v: string): string | null {
  const t = v.trim();
  if (MONEY.has(k)) return toMinor(t) === null || t.startsWith("-") ? "Type an amount like 1250.00, with no more than 2 decimals." : null;
  if (k === "issue_date" || k === "due_date") {
    if (t === "") return k === "due_date" ? null : "Type the date like 2026-12-15.";
    const d = new Date(`${t}T00:00:00Z`);
    return /^\d{4}-\d{2}-\d{2}$/.test(t) && !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === t ? null : "Type the date like 2026-12-15.";
  }
  if (k === "currency") return /^[A-Za-z]{3}$/.test(t) ? null : "Type a 3 letter currency code like USD.";
  return null;
}
const current = (b: BillDetail, k: string): string => {
  switch (k) { case "vendor": return b.vendor; case "number": return b.number; case "issue_date": return b.issue_date ?? ""; case "due_date": return b.due_date ?? ""; case "po": return b.po_number; case "bill_to": return b.bill_to; case "currency": return b.currency;
    case "subtotal_minor": return (b.subtotal_minor / 100).toFixed(2); case "tax_minor": return (b.tax_minor / 100).toFixed(2); case "total_minor": return (b.total_minor / 100).toFixed(2); default: return b.bank_account; }
};

function Review({ id, queue }: { id: number; queue: BillRow[] }) {
  const qc = useQueryClient();
  const router = useRouter();
  const { canWrite } = useRole();
  const q = useQuery({ queryKey: ["bill", id], queryFn: () => get<BillDetail>(`/bills/${id}`) });
  const [active, setActive] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [confirmReject, setConfirmReject] = useState(false);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["bill", id] }); qc.invalidateQueries({ queryKey: ["bills"] }); qc.invalidateQueries({ queryKey: ["overview"] }); qc.invalidateQueries({ queryKey: ["exceptions"] }); };
  const save = useMutation({
    mutationFn: async () => { const body: Record<string, unknown> = {}; for (const [k, v] of Object.entries(edits)) { body[PATCH[k] ?? k] = MONEY.has(k) ? toMinor(v) : (k === "due_date" && v.trim() === "") ? null : v.trim(); } return api<{ findings: string[] }>(`/bills/${id}`, { method: "PATCH", json: body }); },
    onSuccess: (r) => { setEdits({}); notify.success(r.findings.length ? `Saved. ${r.findings.length} finding${r.findings.length > 1 ? "s" : ""} after the checks.` : "Saved. The checks found nothing."); refresh(); },
    onError: (e: Error) => notify.error("Could not save", e.message),
  });
  const approve = useMutation({ mutationFn: () => post(`/bills/${id}/approve`, { note }), onSuccess: () => { notify.success("Approved."); refresh(); }, onError: (e: Error) => notify.error("Could not approve", e.message) });
  const reject = useMutation({ mutationFn: () => post(`/bills/${id}/reject`, { reason: note || "Rejected by a person" }), onSuccess: () => { notify.info("Rejected."); refresh(); }, onError: (e: Error) => notify.error("Could not reject", e.message) });
  const postDraft = useMutation({
    mutationFn: () => post<{ posted: boolean; reason?: string }>(`/bills/${id}/post`),
    onSuccess: (r) => { r.posted ? notify.success("Posted to the accounting system as a draft.") : notify.info(`Nothing was posted. ${r.reason}`); refresh(); },
    onError: (e: Error) => notify.error("Could not post", e.message),
  });
  const boxes: Box[] = useMemo(() => {
    const f = q.data?.document?.extraction.fields ?? {};
    return Object.entries(f).filter(([, v]) => v.box).map(([k, v]) => ({ id: k, box: v.box as number[], label: FIELD_LABEL[k] ?? k }));
  }, [q.data]);
  if (q.isError) return <LoadError error={q.error} onRetry={() => q.refetch()} what="this bill" />;
  if (!q.data) return <ListSkeleton rows={6} />;
  const b = q.data;
  const fields: Record<string, FieldValue> = b.document?.extraction.fields ?? {};
  const open = b.exceptions.filter((e) => e.status === "open");
  const block = open.filter((e) => e.severity === "block");
  const editable = b.status === "needs_review" || b.status === "inbox";
  const idx = queue.findIndex((x) => x.id === id);
  const dirty = Object.keys(edits).length > 0;
  const ownWork = b.self_review === "owner";
  const needNote = block.length > 0 || ownWork;
  const problems = Object.fromEntries(Object.entries(edits).map(([k, v]) => [k, fieldProblem(k, v)] as const).filter(([, m]) => m));
  const firstProblem = Object.values(problems)[0] ?? null;
  const missing = [!b.vendor.trim() && "vendor", !b.issue_date && "bill date", b.total_minor <= 0 && "total"].filter(Boolean) as string[];
  const approveBlocked = dirty ? "Save your changes first" : missing.length ? `Fill in the ${missing.join(", ")} and save first` : b.self_review === "blocked" ? "You changed this bill or closed a finding on it. Someone else has to approve it" : needNote && !note.trim() ? "Write the reason first" : null;
  return (
    <div className="ll-stack">
      <div className="sx-row" style={{ flexWrap: "wrap" }}>
        <Badge tone={BILL_STATE[b.status]?.tone ?? "accent"}>{BILL_STATE[b.status]?.label ?? b.status.replace(/_/g, " ")}</Badge>
        <strong>{b.vendor || "Unknown vendor"}</strong><span className="ll-num">{b.number}</span><span className="ll-num">{moneyIn(b.total_minor, b.currency)}</span>
        <span className="ll-grow" />
        <Button size="sm" feedback={false} disabled={idx <= 0} disabledReason="This is the first bill in the queue" onClick={() => router.push(`/review?bill=${queue[idx - 1]!.id}`)}>Previous</Button>
        <Button size="sm" feedback={false} disabled={idx < 0 || idx >= queue.length - 1} disabledReason="This is the last bill in the queue" onClick={() => router.push(`/review?bill=${queue[idx + 1]!.id}`)}>Next</Button>
      </div>
      <div className="ll-review">
        <div>
          {b.document ? <DocViewer docId={b.document.id} boxes={b.document.readable ? boxes : []} active={active} onActive={setActive} alt={`Page 1 of ${b.document.ref}${b.vendor ? `, the bill from ${b.vendor}` : ""}`} />
            : <Card><EmptyState title="No document" body="No document is attached to this bill." /></Card>}
          {b.document && !b.document.readable ? <p className="ll-mini" style={{ color: "var(--sx-ink-2)", fontSize: "var(--sx-text-caption)", margin: "8px 0 0" }}>This page is a picture and the offline reader cannot read pictures. Read it here and key the fields by hand on the right, or connect a live reader.</p> : null}
        </div>
        <div className="ll-fields">
          {open.map((e) => (
            <div key={e.id} className={`ll-find ${e.severity === "block" ? "ll-find--block" : e.severity === "info" ? "ll-find--info" : ""}`} role="note">
              <span className="sx-row"><Badge tone={sevTone(e.severity)}>{e.severity === "block" ? "Blocks approval" : e.severity === "warning" ? "Check" : "Note"}</Badge><strong>{finding(e.kind).label}</strong></span>
              <span style={{ fontSize: "var(--sx-text-caption)" }}>{e.detail}</span>
            </div>
          ))}
          {ORDER.filter((k) => k in fields || edits[k] !== undefined || (!b.document?.readable && k !== "currency")).map((k) => {
            const fv = fields[k];
            const val = edits[k] ?? current(b, k);
            return (
              <div key={k} className="ll-field" data-on={active === k} onMouseEnter={() => setActive(k)} onMouseLeave={() => setActive(null)}>
                <label className="ll-field__label" htmlFor={`f-${k}`}>{FIELD_LABEL[k]}</label>
                <input id={`f-${k}`} className="ll-field__input" value={val} disabled={!editable} inputMode={MONEY.has(k) ? "decimal" : undefined} onFocus={() => setActive(k)} onBlur={() => setActive(null)}
                  onChange={(e) => setEdits((x) => ({ ...x, [k]: e.target.value }))} aria-describedby={`why-${k}`} aria-invalid={problems[k] ? true : undefined} />
                {fv ? <Badge tone={confTone(fv.confidence)}>{fv.confidence} {confWord(fv.confidence)}</Badge> : <Badge>typed by hand</Badge>}
                <span id={`why-${k}`} className="ll-field__why" role={problems[k] ? "alert" : undefined}>{problems[k] ?? (fv ? `${fv.reasons.join(", ")}.${fv.box ? "" : " No position on the page."}` : "No value was read from the page.")}</span>
              </div>
            );
          })}
          {b.lines.length ? (
            <Card title="Lines" headingLevel={3}>
              <table className="ll-lines"><thead><tr><th>Item</th><th>Qty</th><th>Price</th><th>Amount</th></tr></thead><tbody>
                {b.lines.map((l) => <tr key={l.id}><td>{l.description}</td><td>{l.quantity_milli / 1000}</td><td>{money(l.unit_minor)}</td><td>{money(l.total_minor)}</td></tr>)}
              </tbody></table>
            </Card>
          ) : null}
          {b.vendor_record ? <p className="ll-mini" style={{ color: "var(--sx-ink-3)", fontSize: 12, margin: 0 }}>On file for this vendor: account {b.vendor_record.bank_account}, usual currency {b.vendor_record.currency}, tax {b.vendor_record.tax_rate_bp / 100} percent{b.vendor_record.requires_po ? ", purchase order required" : ""}.</p> : null}
          {editable ? (
            <Card title="Decide" headingLevel={3}>
              <div className="ll-stack">
                <Field label={block.length > 0 ? "Why approve despite the blocking finding (required)" : ownWork ? "Why approve a bill you changed yourself (required)" : "Note (optional)"} value={note} onChange={setNote} />
                <div className="sx-row" style={{ flexWrap: "wrap" }}>
                  <Button disabled={!canWrite || !dirty || !!firstProblem} disabledReason={!canWrite ? "Your sign in can read but not change" : firstProblem ?? "Change a field first"} onClick={async () => { await save.mutateAsync(); }}>Save changes</Button>
                  <Button variant="primary" disabled={!canWrite || !!approveBlocked} disabledReason={!canWrite ? "Your sign in can read but not change" : approveBlocked ?? undefined} onClick={async () => { await approve.mutateAsync(); }}>Approve</Button>
                  <Button variant="danger" feedback={false} disabled={!canWrite} disabledReason="Your sign in can read but not change" onClick={() => setConfirmReject(true)}>Reject</Button>
                </div>
              </div>
            </Card>
          ) : b.status !== "approved" ? (
            <Card title="Closed" headingLevel={3}><p style={{ margin: 0, maxWidth: "65ch" }}>This bill is {BILL_STATE[b.status]?.label.toLowerCase() ?? b.status}. Nothing more can be done to it here.</p></Card>
          ) : b.status === "approved" ? (
            <Card title="Post to accounting" headingLevel={3}>
              <p style={{ margin: "0 0 13px", maxWidth: "65ch" }}>Posting makes a draft bill in your accounting system. It needs live mode and the accounting write switch. In draft mode nothing is posted and you are told so.</p>
              <Button variant="primary" disabled={!canWrite} disabledReason="Your sign in can read but not change" onClick={async () => { await postDraft.mutateAsync(); }}>Post as a draft</Button>
            </Card>
          ) : null}
        </div>
      </div>
      <ConfirmDialog open={confirmReject} onOpenChange={setConfirmReject} title="Reject this bill?" description="It leaves the queue and is not paid. The reason in the note box is saved to the audit log." confirmLabel="Reject" destructive onConfirm={() => reject.mutate()} />
    </div>
  );
}

function Inner() {
  const sp = useSearchParams();
  const router = useRouter();
  const list = useQuery({ queryKey: ["bills", "needs_review,inbox,approved"], queryFn: () => get<BillRow[]>("/bills?status=needs_review,inbox,approved") });
  if (list.isError) return <LoadError error={list.error} onRetry={() => list.refetch()} what="the review queue" />;
  if (!list.data) return <ListSkeleton rows={6} />;
  const queue = [...list.data].sort((a, c) => (a.flags.some((f) => f.severity === "block") ? 0 : 1) - (c.flags.some((f) => f.severity === "block") ? 0 : 1) || a.id - c.id);
  const id = Number(sp.get("bill")) || queue[0]?.id;
  const options = [...queue.map((b) => ({ id: b.id, label: `${b.vendor || `Unreadable page (bill ${b.id})`} ${b.number} ${b.flags.some((f) => f.severity === "block") ? "(blocked)" : ""}`.trim() })), ...(id && !queue.some((b) => b.id === id) ? [{ id, label: `Bill ${id} (no longer in the queue)` }] : [])];
  if (!id) return <Card><EmptyState title="The review queue is empty" body="New bills show up here when they arrive by email or when you upload one on the Bills page." /></Card>;
  return (
    <div className="ll-stack">
      <label className="sx-label" style={{ display: "grid", gap: 5, maxWidth: 420 }}>Bill in the queue ({queue.length})
        <select className="ll-select" value={id} onChange={(e) => router.push(`/review?bill=${e.target.value}`)}>
          {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select></label>
      <Review key={id} id={id} queue={queue} />
    </div>
  );
}

export default function ReviewPage() {
  return (
    <div className="ll-page">
      <PageHead title="Invoice review" sub="The page on the left, what was read on the right. Point at a value to see where it came from. Fix anything that is wrong, then approve." />
      <Suspense fallback={<ListSkeleton rows={6} />}><Inner /></Suspense>
    </div>
  );
}
