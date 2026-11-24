"use client";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { moneyShort } from "@/lib/money";
import type { Week } from "@/lib/types";

interface Props { weeks: Week[]; base?: number[] | null; height?: number }
const W = 760, PAD = { l: 58, r: 16, t: 14, b: 30 };

function tween(from: number[], to: number[], ms: number, onFrame: (v: number[]) => void, reduced: boolean): () => void {
  if (reduced || from.length !== to.length) { onFrame(to); return () => {}; }
  let raf = 0; const t0 = performance.now();
  const step = (t: number) => {
    const k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3);
    onFrame(to.map((v, i) => (from[i] ?? 0) + (v - (from[i] ?? 0)) * e));
    if (k < 1) raf = requestAnimationFrame(step);
  };
  raf = requestAnimationFrame(step);
  return () => cancelAnimationFrame(raf);
}

/** The forecast line. It redraws smoothly: values move from the old answer to the new one over 420 ms, and a newer answer cancels the move. */
export function ForecastChart({ weeks, base, height = 300 }: Props) {
  const target = useMemo(() => weeks.map((w) => w.closing_minor), [weeks]);
  const [shown, setShown] = useState<number[]>(target);
  const prev = useRef<number[]>(target);
  const [hover, setHover] = useState<number | null>(null);
  const uid = useId().replace(/:/g, "");
  useEffect(() => {
    const reduced = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const cancel = tween(prev.current, target, 420, (v) => { prev.current = v; setShown(v); }, reduced);
    return cancel;
  }, [target]);
  const all = [...shown, ...(base ?? []), 0];
  const lo = Math.min(...all), hi = Math.max(...all), span = Math.max(hi - lo, 1);
  const H = height, iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;
  const x = (i: number) => PAD.l + (iw * i) / Math.max(shown.length - 1, 1);
  const y = (v: number) => PAD.t + ih * (1 - (v - lo) / span);
  const path = (vals: number[]) => vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  const zero = y(0);
  const ticks = [lo, lo + span / 2, hi].map((v) => Math.round(v / 100) * 100);
  const low = shown.indexOf(Math.min(...shown));
  const neg = lo < 0;
  return (
    <figure className="ll-chart" aria-label="13 week cash forecast">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Cash by week, lowest ${moneyShort(Math.min(...target))} in week ${target.indexOf(Math.min(...target)) + 1}`} onPointerLeave={() => setHover(null)}
        onPointerMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); const px = ((e.clientX - r.left) / r.width) * W; setHover(Math.max(0, Math.min(shown.length - 1, Math.round(((px - PAD.l) / iw) * (shown.length - 1))))); }}>
        <defs>
          <linearGradient id={`g${uid}`} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="var(--sx-accent)" stopOpacity="0.32" /><stop offset="1" stopColor="var(--sx-accent)" stopOpacity="0.02" /></linearGradient>
          <clipPath id={`neg${uid}`}><rect x={PAD.l} y={Math.min(zero, H - PAD.b)} width={iw} height={Math.max(H - PAD.b - zero, 0)} /></clipPath>
        </defs>
        {ticks.map((t, i) => (<g key={i}><line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} className="ll-chart__grid" /><text x={PAD.l - 8} y={y(t) + 4} textAnchor="end" className="ll-chart__tick">{moneyShort(t)}</text></g>))}
        {neg ? <line x1={PAD.l} x2={W - PAD.r} y1={zero} y2={zero} className="ll-chart__zero" /> : null}
        <path d={`${path(shown)} L${x(shown.length - 1)} ${y(lo)} L${x(0)} ${y(lo)} Z`} fill={`url(#g${uid})`} />
        {neg ? <path d={`${path(shown)} L${x(shown.length - 1)} ${y(lo)} L${x(0)} ${y(lo)} Z`} className="ll-chart__neg" clipPath={`url(#neg${uid})`} /> : null}
        {base ? <path d={path(base)} className="ll-chart__base" /> : null}
        <path d={path(shown)} className="ll-chart__line" />
        {shown.map((v, i) => <circle key={i} cx={x(i)} cy={y(v)} r={hover === i ? 5 : i === low ? 4 : 2.5} className={v < 0 ? "ll-chart__dot ll-chart__dot--bad" : "ll-chart__dot"} />)}
        {weeks.map((w, i) => (i % 2 === 0 ? <text key={w.index} x={x(i)} y={H - 8} textAnchor="middle" className="ll-chart__tick">W{w.index}</text> : null))}
        {hover !== null ? <g><line x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={H - PAD.b} className="ll-chart__cross" /></g> : null}
      </svg>
      <figcaption className="ll-chart__cap" aria-live="polite">
        {hover !== null ? <span>Week {weeks[hover]!.index}, from {weeks[hover]!.start}: cash {moneyShort((shown[hover] ?? 0))}. In {moneyShort(weeks[hover]!.receipts_minor + weeks[hover]!.new_sales_minor)}, out {moneyShort(weeks[hover]!.bills_minor + weeks[hover]!.recurring_out_minor + weeks[hover]!.other_minor)}.</span>
          : <span>Move over the chart for a week. {base ? "The dashed line is the forecast without the changes." : ""}</span>}
      </figcaption>
    </figure>
  );
}
