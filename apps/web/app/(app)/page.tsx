"use client";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Badge, Button, Card, CountUp, EmptyState } from "@sendora/ui-kit";
import { ForecastChart } from "@/components/ForecastChart";
import { FxBanner } from "@/components/Fx";
import { ListSkeleton, LoadError, PageHead } from "@/components/Parts";
import { get } from "@/lib/api";
import { money, moneyShort } from "@/lib/money";
import type { Forecast, Overview } from "@/lib/types";

function useDebounced<T>(v: T, ms: number): T {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

function Slider({ id, label, value, min, max, step, onChange, text }: { id: string; label: string; value: number; min: number; max: number; step: number; onChange: (n: number) => void; text: string }) {
  return (
    <div className="ll-slider">
      <div className="ll-slider__row"><label htmlFor={id}>{label}</label><strong className="ll-num">{text}</strong></div>
      <input id={id} type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} aria-valuetext={text} />
    </div>
  );
}

export default function CockpitPage() {
  const [collect, setCollect] = useState(0);
  const [pay, setPay] = useState(0);
  const [hire, setHire] = useState(0);
  const [hireWeek, setHireWeek] = useState(4);
  const q = useDebounced({ collect, pay, hire, hireWeek }, 60);
  const ov = useQuery({ queryKey: ["overview"], queryFn: () => get<Overview>("/overview") });
  const fc = useQuery({
    queryKey: ["forecast", q],
    queryFn: () => get<Forecast>(`/forecast?collect_delay_days=${q.collect}&pay_delay_days=${q.pay}&hire_monthly_minor=${q.hire * 100}&hire_week=${q.hireWeek}`),
    placeholderData: keepPreviousData,
  });
  const why = useQuery({ queryKey: ["forecast-explain"], queryFn: () => get<{ text: string; writer: string }>("/forecast/explain") });
  if (ov.isError) return <div className="ll-page"><PageHead title="Cash cockpit" /><LoadError error={ov.error} onRetry={() => ov.refetch()} what="the cockpit" /></div>;
  if (!ov.data || !fc.data) return <div className="ll-page"><PageHead title="Cash cockpit" /><ListSkeleton rows={6} /></div>;
  const o = ov.data, f = fc.data;
  const changed = collect > 0 || pay > 0 || hire > 0;
  const bad = f.low_point_minor < 0;
  return (
    <div className="ll-page">
      <PageHead title="Cash cockpit" sub={`As of ${o.as_of}. The next 13 weeks of cash, worked out by code from what customers owe, what bills are due and what repeats every month.`}
        actions={changed ? <Button size="sm" feedback={false} onClick={() => { setCollect(0); setPay(0); setHire(0); }}>Reset the sliders</Button> : null} />
      <FxBanner fx={o.fx} />
      <div className="ll-statgrid">
        <div className="ll-stat"><span className="ll-stat__l">Cash in the bank</span><span className="ll-stat__v"><CountUp value={o.cash_minor} format={(n) => money(n)} /></span></div>
        <div className="ll-stat"><span className="ll-stat__l">Customers owe you</span><span className="ll-stat__v"><CountUp value={o.receivable_minor} format={(n) => money(n)} /></span><span className="ll-stat__l">{money(o.overdue_minor)} is late</span></div>
        <div className="ll-stat"><span className="ll-stat__l">Bills to pay</span><span className="ll-stat__v"><CountUp value={o.payable_minor} format={(n) => money(n)} /></span><span className="ll-stat__l">{o.bills_to_review} still need review</span></div>
        <div className="ll-stat"><span className="ll-stat__l">Lowest point{changed ? " with your changes" : ""}</span><span className={`ll-stat__v ${bad ? "ll-neg" : ""}`}><CountUp value={f.low_point_minor} format={(n) => money(n)} /></span><span className="ll-stat__l">in week {f.low_point_week}{bad ? ", below zero" : ""}</span></div>
      </div>
      <div className="ll-two ll-two--rev">
        <Card title="Cash week by week">
          <ForecastChart weeks={f.weeks} base={changed ? f.base_closing : null} />
          {f.runs_out_in_week ? <p role="alert" className="ll-neg" style={{ margin: "8px 0 0" }}><strong>Cash runs out in week {f.runs_out_in_week}.</strong> Look at what you can collect sooner or pay later.</p> : <p className="ll-mini" style={{ margin: "8px 0 0", color: "var(--sx-ink-2)" }}>Cash stays above zero for all 13 weeks{changed ? " with these changes" : ""}.</p>}
        </Card>
        <Card title="What if">
          <div className="ll-sliders">
            <Slider id="s-collect" label="Customers pay later by" value={collect} min={0} max={30} step={1} onChange={setCollect} text={`${collect} days`} />
            <Slider id="s-pay" label="You pay vendors later by" value={pay} min={0} max={30} step={1} onChange={setPay} text={`${pay} days`} />
            <Slider id="s-hire" label="Add a hire costing" value={hire} min={0} max={8000} step={250} onChange={setHire} text={hire ? `${money(hire * 100)} a month` : "no hire"} />
            {hire > 0 ? <Slider id="s-week" label="Starting in week" value={hireWeek} min={1} max={13} step={1} onChange={setHireWeek} text={`week ${hireWeek}`} /> : null}
          </div>
          <p className="ll-mini" style={{ color: "var(--sx-ink-2)", fontSize: "var(--sx-text-caption)", margin: "13px 0 0" }}>Closing cash in week 13: <strong className={`ll-num ${f.closing_minor < 0 ? "ll-neg" : ""}`}>{money(f.closing_minor)}</strong>{changed ? <> instead of <span className="ll-num">{money(f.base_closing[12] ?? 0)}</span></> : null}. {f.beyond_horizon_minor ? `${moneyShort(f.beyond_horizon_minor)} more is expected after week 13.` : ""}</p>
        </Card>
      </div>
      <Card title="In plain words">
        {why.data ? <><p style={{ margin: 0, maxWidth: "65ch" }}>{why.data.text}</p><p className="ll-mini" style={{ color: "var(--sx-ink-3)", fontSize: 12, margin: "8px 0 0" }}>Written by: {why.data.writer}. Every number above comes from the forecast code, not from the writer.</p></> : <ListSkeleton rows={1} />}
        {f.excluded_receivables.length ? <p style={{ margin: "13px 0 0" }}><Badge tone="warning">{f.excluded_receivables.length} invoices left out</Badge> <span className="ll-mini" style={{ color: "var(--sx-ink-2)" }}>They are in dispute or belong to a customer with a bankruptcy flag, so they count for nothing until that changes.</span></p> : null}
        <details style={{ marginTop: 13 }}><summary>How the forecast works</summary><p style={{ maxWidth: "65ch" }}>Each unpaid invoice gets a date (the promised date, or the due date plus how late that customer usually pays) and a chance of being paid based on how late it already is. The chances are defaults the owner sets: 95, 90, 75, 50 and 20 percent from current to over 90 days late. Bills are paid on their due date. Repeating items like rent and payroll are expanded by date. Nothing here predicts new sales beyond the average of the last 13 weeks, collected about six weeks after invoicing.</p></details>
      </Card>
      {o.bills_to_review === 0 && o.open_exceptions === 0 ? <Card><EmptyState title="Nothing needs you" body="No bills are waiting and no exceptions are open." /></Card> : null}
    </div>
  );
}
