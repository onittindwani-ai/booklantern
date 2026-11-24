"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Card, DataTable, EmptyState, TableSkeleton, type Column } from "@sendora/ui-kit";
import { FxAmount, FxBanner } from "@/components/Fx";
import { ListSkeleton, LoadError, PageHead } from "@/components/Parts";
import { get } from "@/lib/api";
import { money } from "@/lib/money";
import type { Aging, InvoiceRow } from "@/lib/types";

const BUCKETS = ["current", "1-30", "31-60", "61-90", "90+"];
const LABEL: Record<string, string> = { current: "Not due yet", "1-30": "1 to 30 days late", "31-60": "31 to 60 days", "61-90": "61 to 90 days", "90+": "Over 90 days" };

export default function AgingPage() {
  const q = useQuery({ queryKey: ["aging"], queryFn: () => get<Aging>("/aging") });
  const [sel, setSel] = useState<{ customer?: number; bucket?: string } | null>(null);
  const drill = useQuery({ queryKey: ["aging-drill", sel], enabled: sel !== null, queryFn: () => get<InvoiceRow[]>(`/invoices?status=open${sel?.customer ? `&customer_id=${sel.customer}` : ""}${sel?.bucket ? `&bucket=${encodeURIComponent(sel.bucket)}` : ""}`) });
  if (q.isError) return <div className="ll-page"><PageHead title="Aging" /><LoadError error={q.error} onRetry={() => q.refetch()} what="aging" /></div>;
  if (!q.data) return <div className="ll-page"><PageHead title="Aging" /><ListSkeleton /></div>;
  const a = q.data;
  const max = Math.max(...a.customers.map((c) => c.total_minor), 1);
  const columns: Column<InvoiceRow>[] = [
    { key: "n", header: "Invoice", width: "110px", render: (r) => r.number, sortValue: (r) => r.number },
    { key: "c", header: "Customer", width: "1.3fr", render: (r) => r.customer, sortValue: (r) => r.customer },
    { key: "d", header: "Due", width: "110px", render: (r) => r.due_date, sortValue: (r) => r.due_date },
    { key: "l", header: "Days late", width: "90px", align: "right", render: (r) => (r.days_late > 0 ? r.days_late : "not due"), sortValue: (r) => r.days_late },
    { key: "o", header: "Owed", width: "170px", align: "right", render: (r) => <FxAmount minor={r.outstanding_minor} currency={r.currency} fx={r.fx} />, sortValue: (r) => r.fx?.base_minor ?? r.outstanding_minor },
    { key: "s", header: "Status", width: "150px", render: (r) => (r.disputed ? <Badge tone="warning">In dispute</Badge> : <Badge>{LABEL[r.bucket] ?? r.bucket}</Badge>) },
  ];
  return (
    <div className="ll-page">
      <PageHead title="Aging" sub={`${money(a.total_minor)} is owed to you. The colour shows how late. Click a bar or one of its colours to see the invoices behind it.`} />
      <FxBanner fx={a.fx} />
      <Card title="By customer">
        <div className="ll-legend" style={{ marginBottom: 13 }}>{BUCKETS.map((b, i) => <span key={b}><i className={`ll-b${i}`} />{LABEL[b]} <strong className="ll-num">{money(a.buckets_minor[b] ?? 0)}</strong></span>)}</div>
        <div className="ll-agebars">
          {a.customers.length === 0 ? <EmptyState title="Nobody owes you anything" body="Every invoice is paid." /> : a.customers.map((c) => (
            <div key={c.customer_id} className="ll-agerow">
              <button className="ll-link" type="button" style={{ all: "unset", cursor: "pointer", textDecoration: "underline", textDecorationColor: "var(--sx-line-strong)" }} onClick={() => setSel({ customer: c.customer_id })}>{c.name}</button>
              <div className="ll-agebar" style={{ width: `${Math.max((c.total_minor / max) * 100, 4)}%` }} role="group" aria-label={`${c.name}, ${money(c.total_minor)} owed`}>
                {BUCKETS.map((b, i) => (c.buckets_minor[b] ?? 0) > 0 ? <button key={b} type="button" className={`ll-b${i}`} style={{ flex: `${c.buckets_minor[b] ?? 0} 1 0` }} aria-pressed={sel?.customer === c.customer_id && sel?.bucket === b} aria-label={`${c.name}, ${LABEL[b]}, ${money(c.buckets_minor[b] ?? 0)}`} title={`${LABEL[b]}: ${money(c.buckets_minor[b] ?? 0)}`} onClick={() => setSel({ customer: c.customer_id, bucket: b })} /> : null)}
              </div>
              <span className="ll-amt ll-num">{money(c.total_minor)}</span>
            </div>
          ))}
        </div>
      </Card>
      {sel ? (
        <Card title={`Invoices${sel.bucket ? `, ${(LABEL[sel.bucket] ?? "").toLowerCase()}` : ""}${sel.customer ? `, ${a.customers.find((c) => c.customer_id === sel.customer)?.name}` : ""}`}>
          {!drill.data ? <TableSkeleton rows={3} columns={6} /> : drill.data.length === 0 ? <EmptyState title="Nothing here" body="No open invoices match." /> : <div className="ll-noopen"><DataTable label="Invoices behind the bar" rows={drill.data} rowKey={(r) => String(r.id)} columns={columns} height={Math.min(60 + drill.data.length * 44, 360)} /></div>}
        </Card>
      ) : null}
    </div>
  );
}
