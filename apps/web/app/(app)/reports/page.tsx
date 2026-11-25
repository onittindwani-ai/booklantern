"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Card, DataTable, EmptyState, Field, notify, type Column } from "@sendora/ui-kit";
import { FxBanner } from "@/components/Fx";
import { ListSkeleton, LoadError, PageHead } from "@/components/Parts";
import { get, post } from "@/lib/api";
import { money } from "@/lib/money";
import type { FxInfo, FxRateRow } from "@/lib/types";

type Sum = { as_of: string; currency: string; cash_minor: number; receivable_minor: number; bills_to_review: number; open_invoices: number; unmatched_lines: number; open_exceptions: number; fx: FxInfo };
type Rates = { base: string; today: string; rates: FxRateRow[] };

function RatesCard({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["fx-rates"], queryFn: () => get<Rates>("/fx-rates") });
  const [cur, setCur] = useState("EUR");
  const [rate, setRate] = useState("");
  const [day, setDay] = useState("");
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () => post<{ warning: string }>("/fx-rates", { currency: cur, rate_date: day || q.data?.today, rate, note }),
    onSuccess: (r) => {
      if (r.warning) notify.info(`Rate saved. Check it: ${r.warning}`); else notify.success("Rate saved. Totals use it from its date on.");
      setRate(""); setNote(""); qc.invalidateQueries();
    },
    onError: (e: Error) => notify.error("Could not save the rate", e.message),
  });
  const base = q.data?.base ?? "USD";
  const columns: Column<FxRateRow>[] = [
    { key: "c", header: "Currency", width: "100px", render: (r) => r.currency, sortValue: (r) => r.currency },
    { key: "r", header: `${base} for 1`, width: "130px", align: "right", render: (r) => r.rate, sortValue: (r) => Number(r.rate) },
    { key: "d", header: "From", width: "120px", render: (r) => r.rate_date, sortValue: (r) => r.rate_date },
    { key: "n", header: "Note", width: "1.4fr", render: (r) => r.note || "", sortValue: (r) => r.note },
    { key: "b", header: "Entered by", width: "1fr", render: (r) => r.entered_by, sortValue: (r) => r.entered_by },
  ];
  return (
    <Card title="Exchange rates (typed by a person)">
      <div className="ll-stack" id="rates">
        <p className="ll-mini" style={{ margin: 0, color: "var(--sx-ink-2)", fontSize: "var(--sx-text-caption)", maxWidth: "65ch" }}>
          Amounts in another currency are converted into {base} with the latest rate dated on or before the day looked at. With no rate, the amount is left out and flagged, never guessed. Nothing here is fetched from a market feed: look the rate up (your bank or accountant) and type it. The rate is {base} for one unit of the other currency.
        </p>
        {!q.data ? <ListSkeleton rows={2} /> : q.data.rates.length === 0 ? <EmptyState title="No rates yet" body="Add one when a bill or invoice comes in another currency." /> : <div className="ll-noopen"><DataTable label="Exchange rates" rows={q.data.rates} rowKey={(r) => String(r.id)} columns={columns} height={Math.min(60 + q.data.rates.length * 44, 280)} /></div>}
        {canEdit ? (
          <div className="ll-ratesform" role="group" aria-label="Add an exchange rate">
            <Field label="Currency code" value={cur} onChange={(v) => setCur(v.toUpperCase().slice(0, 3))} hint="For example EUR" />
            <Field label={`${base} for one unit`} value={rate} onChange={setRate} hint="For example 1.0800" inputMode="decimal" />
            <Field label="Valid from" type="date" value={day || q.data?.today || ""} onChange={setDay} />
            <Field label="Note (optional)" value={note} onChange={setNote} hint="Where you looked it up" />
            <Button variant="primary" loading={save.isPending} disabled={cur.length !== 3 || rate.trim() === ""} disabledReason="Type a 3 letter currency and a rate first" onClick={() => save.mutate()}>Save rate</Button>
          </div>
        ) : <p className="ll-mini" style={{ margin: 0 }}>Only the owner can change the rates. Your sign in can read them.</p>}
      </div>
    </Card>
  );
}

export default function ReportsPage() {
  const q = useQuery({ queryKey: ["report-summary"], queryFn: () => get<Sum>("/reports/summary") });
  const me = useQuery({ queryKey: ["me"], queryFn: () => get<{ role: string }>("/auth/me") });
  if (q.isError) return <div className="ll-page"><PageHead title="Reports" /><LoadError error={q.error} onRetry={() => q.refetch()} what="the report" /></div>;
  if (!q.data) return <div className="ll-page"><PageHead title="Reports" /><ListSkeleton /></div>;
  const s = q.data;
  return (
    <div className="ll-page">
      <PageHead title="Reports" sub={`Month end pack as of ${s.as_of}. Built by code from the data here. It is a working pack, not accounting or tax advice.`} actions={<a className="sx-btn sx-btn--primary" href="/api/reports/month-end.pdf" download>Download the PDF</a>} />
      <FxBanner fx={s.fx} />
      <div className="ll-statgrid">
        <div className="ll-stat"><span className="ll-stat__l">Cash on the statements</span><span className="ll-stat__v">{money(s.cash_minor)}</span></div>
        <div className="ll-stat"><span className="ll-stat__l">Owed to you</span><span className="ll-stat__v">{money(s.receivable_minor)}</span></div>
        <div className="ll-stat"><span className="ll-stat__l">Open invoices</span><span className="ll-stat__v">{String(s.open_invoices)}</span></div>
        <div className="ll-stat"><span className="ll-stat__l">Bills to review</span><span className="ll-stat__v">{String(s.bills_to_review)}</span></div>
        <div className="ll-stat"><span className="ll-stat__l">Bank lines not matched</span><span className="ll-stat__v">{String(s.unmatched_lines)}</span></div>
        <div className="ll-stat"><span className="ll-stat__l">Open exceptions</span><span className="ll-stat__v">{String(s.open_exceptions)}</span></div>
      </div>
      <Card title="What is in the pack"><p style={{ margin: 0 }}>Totals, receivables aging by customer, bills waiting, unmatched bank lines, open exceptions, the 13 week forecast, and the exchange rates used with every converted item. Every number comes from code. Check it before you share it.</p></Card>
      <RatesCard canEdit={me.data?.role === "owner"} />
    </div>
  );
}
