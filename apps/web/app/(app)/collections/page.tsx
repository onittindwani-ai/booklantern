"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, CopyButton, Dialog, EmptyState, Field, TableSkeleton, TabsView, notify } from "@sendora/ui-kit";
import { FxAmount } from "@/components/Fx";
import { ListSkeleton, LoadError, PageHead } from "@/components/Parts";
import { get, post } from "@/lib/api";
import { useRole } from "@/lib/hooks";
import { stop } from "@/lib/labels";
import { money, moneyIn } from "@/lib/money";
import type { Collections, Overview, PlanRow } from "@/lib/types";

const PROMISE_STATE: Record<string, string> = { open: "Waiting", kept: "Kept", broken: "Broken", replaced: "Replaced by a newer promise" };
const DRAFT_STATE: Record<string, string> = { drafted: "Waiting for you", approved: "Approved, goes out on the next run" };
const NO_WRITE = "Your sign in can read but not change";

/** A real calendar day typed as 2026-12-15, or a sentence about what is wrong. */
function dateProblem(v: string, today: string | undefined): string | null {
  const d = new Date(`${v}T00:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(v) || Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== v) return "Type a real date like 2026-12-15.";
  return today && v < today ? `The date is in the past. Pick ${today} or a later day.` : null;
}

function Ladder({ row, ladder }: { row: PlanRow; ladder: Collections["ladder"] }) {
  const sent = new Set(row.sent.map((s) => s.step));
  return <span className="ll-ladder" role="img" aria-label={`${sent.size} of ${ladder.length} reminders sent`}>{ladder.map((l) => <span key={l.step} className="ll-ladder__dot" title={`Step ${l.step}: ${l.tone}, ${l.days_after_due} days after the due date`} data-state={sent.has(l.step) ? "sent" : l.step === row.next_step && row.decision !== "stop" ? "next" : "todo"} />)}</span>;
}

export default function CollectionsPage() {
  const qc = useQueryClient();
  const { canWrite } = useRole();
  const ov = useQuery({ queryKey: ["overview"], queryFn: () => get<Overview>("/overview") });
  const q = useQuery({ queryKey: ["collections"], queryFn: () => get<Collections>("/collections") });
  const [promise, setPromise] = useState<PlanRow | null>(null);
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const done = () => { qc.invalidateQueries(); };
  const approve = useMutation({ mutationFn: (id: number) => post(`/reminders/${id}/approve`), onSuccess: () => { notify.success("Approved. It goes out when the rules allow and the mode is live."); done(); }, onError: (e: Error) => notify.error("Could not approve", e.message) });
  const cancel = useMutation({ mutationFn: (id: number) => post(`/reminders/${id}/cancel`), onSuccess: () => { notify.info("Reminder cancelled."); done(); }, onError: (e: Error) => notify.error("Could not cancel", e.message) });
  const dispute = useMutation({ mutationFn: (v: { id: number; on: boolean }) => post(`/invoices/${v.id}/dispute`, { disputed: v.on, note: v.on ? "Marked in dispute from the Collections page" : "" }), onSuccess: (_r, v) => {
      if (v.on) notify.undo("Marked in dispute. Reminders for it have stopped.", () => { void post(`/invoices/${v.id}/dispute`, { disputed: false, note: "" }).then(() => { notify.info("Dispute cleared."); done(); }); });
      else notify.success("Dispute cleared.");
      done();
    }, onError: (e: Error) => notify.error("Could not change the dispute", e.message) });
  const link = useMutation({ mutationFn: (id: number) => post<{ url: string; real: boolean }>(`/invoices/${id}/payment-link`), onSuccess: (r) => { notify.success(r.real ? "Payment link created." : "Draft mode: a placeholder link was saved, nothing was created at the payment provider."); done(); }, onError: (e: Error) => notify.error("Could not make the payment link", e.message) });
  const savePromise = useMutation({ mutationFn: () => post(`/invoices/${promise!.id}/promise`, { promised_on: date, amount_minor: promise!.outstanding_minor, note }), onSuccess: () => { notify.success("Promise recorded. Reminders pause until that date."); setPromise(null); done(); }, onError: (e: Error) => notify.error("Could not save", e.message) });
  if (q.isError) return <div className="ll-page"><PageHead title="Collections" /><LoadError error={q.error} onRetry={() => q.refetch()} what="collections" /></div>;
  if (!q.data) return <div className="ll-page"><PageHead title="Collections" /><ListSkeleton /></div>;
  const c = q.data;
  const problem = date ? dateProblem(date, ov.data?.as_of) : null;
  const drafts = c.reminders.filter((r) => r.status === "drafted" || r.status === "approved");
  return (
    <div className="ll-page">
      <PageHead title="Collections" sub="Who gets a reminder, in what tone, and why some are held. Stop rules always win: a payment, a dispute, a promise, an opt out or a bankruptcy flag stops the ladder." />
      <TabsView items={[
        { value: "ladder", label: `Ladder (${c.plan.length})`, content: (
          <Card>
            <div className="ll-stack">
              <p className="ll-mini" style={{ margin: 0, color: "var(--sx-ink-2)", fontSize: "var(--sx-text-caption)" }}>Ladder: {c.ladder.map((l) => `step ${l.step} is ${l.tone}, ${l.days_after_due} days after due`).join("; ")}. These days and the wording are decided defaults. Change them for each client in the settings.</p>
              {c.plan.length === 0 ? <EmptyState title="Nothing is owed" body="There are no open invoices." /> : c.plan.map((r) => (
                <div key={r.id} className="ll-plan">
                  <span><strong>{r.number}</strong> {r.customer} <FxAmount minor={r.outstanding_minor} currency={r.currency} fx={r.fx} /> <span className="ll-mini" style={{ color: "var(--sx-ink-3)" }}>{r.days_late > 0 ? `${r.days_late} days late` : "not due yet"}</span></span>
                  <Ladder row={r} ladder={c.ladder} />
                  <span><Badge tone={r.decision === "stop" ? "warning" : r.decision === "wait" ? "neutral" : "accent"}>{r.decision === "stop" ? "Stopped" : r.decision === "wait" ? "Waiting" : "Draft due"}</Badge> <span className="ll-mini" style={{ fontSize: "var(--sx-text-caption)", color: "var(--sx-ink-2)" }}>{stop(r.reason)}</span></span>
                  <span className="sx-row" style={{ flexWrap: "wrap" }}>
                    <Button size="sm" disabled={!canWrite} disabledReason={NO_WRITE} onClick={() => { setPromise(r); setDate(""); setNote(""); }} feedback={false}>Promise to pay</Button>
                    <Button size="sm" disabled={!canWrite} disabledReason={NO_WRITE} onClick={async () => { await dispute.mutateAsync({ id: r.id, on: !r.disputed }); }}>{r.disputed ? "Clear dispute" : "Dispute"}</Button>
                    <Button size="sm" disabled={!canWrite} disabledReason={NO_WRITE} onClick={async () => { await link.mutateAsync(r.id); }}>{r.payment_link_url ? "New payment link" : "Payment link"}</Button>
                    {r.payment_link_url ? <span className="ll-mini ll-linkrow" style={{ color: "var(--sx-ink-2)" }}>Link: <span className="ll-num" style={{ overflowWrap: "anywhere" }}>{r.payment_link_url}</span> <CopyButton value={r.payment_link_url} label="Copy link" /></span> : null}
                  </span>
                </div>
              ))}
            </div>
          </Card>) },
        { value: "drafts", label: `Drafts (${drafts.length})`, content: (
          <Card>{drafts.length === 0 ? <EmptyState title="No drafts waiting" body="Use Run now, then move a day forward, to see reminders drafted as invoices become due." /> : (
            <div className="ll-stack">{drafts.map((r) => (
              <div key={r.id} className="ll-field" style={{ gridTemplateColumns: "1fr auto" }}>
                <span><strong>{r.subject}</strong> <Badge tone={r.status === "approved" ? "accent" : "warning"}>{DRAFT_STATE[r.status] ?? r.status}</Badge><br /><span className="ll-mini" style={{ fontSize: "var(--sx-text-caption)", color: "var(--sx-ink-2)", whiteSpace: "pre-wrap" }}>{r.body.split("\n").slice(2, 4).join(" ")}</span></span>
                <span className="sx-row">{r.status === "drafted" ? <Button size="sm" variant="primary" disabled={!canWrite} disabledReason={NO_WRITE} onClick={async () => { await approve.mutateAsync(r.id); }}>Approve</Button> : null}<Button size="sm" disabled={!canWrite} disabledReason={NO_WRITE} onClick={async () => { await cancel.mutateAsync(r.id); }}>Cancel</Button></span>
              </div>))}</div>)}</Card>) },
        { value: "promises", label: `Promises (${c.promises.length})`, content: (
          <Card>{c.promises.length === 0 ? <EmptyState title="No promises" body="Record one from the ladder." /> : <div className="ll-stack">{c.promises.map((p) => <div key={p.id} className="ll-field" style={{ gridTemplateColumns: "1fr auto" }}><span><strong>{p.invoice}</strong> {p.customer} promised <strong>{p.promised_on}</strong> <span className="ll-num">{moneyIn(p.amount_minor, p.currency)}</span></span><Badge tone={p.status === "kept" ? "success" : p.status === "broken" ? "danger" : p.status === "replaced" ? "neutral" : "accent"}>{PROMISE_STATE[p.status] ?? p.status}</Badge></div>)}</div>}</Card>) },
      ]} />
      <Dialog open={promise !== null} onOpenChange={(o) => !o && setPromise(null)} title="Promise to pay" description={promise ? `${promise.customer} said they will pay ${promise.number} (${moneyIn(promise.outstanding_minor, promise.currency)}).` : undefined}
        actions={<Button variant="primary" disabled={!date || !!problem} disabledReason={problem ?? "Enter the date as 2026-12-15"} onClick={async () => { await savePromise.mutateAsync(); }}>Save the promise</Button>}>
        <div className="ll-stack"><Field label="Promised date (2026-12-15)" value={date} onChange={setDate} validate={(v) => (v ? dateProblem(v, ov.data?.as_of) : null)} hint="Today or a later day" /><Field label="Note" value={note} onChange={setNote} /></div>
      </Dialog>
    </div>
  );
}
