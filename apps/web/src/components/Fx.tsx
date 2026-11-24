"use client";
import Link from "next/link";
import { Badge } from "@sendora/ui-kit";
import { moneyIn } from "@/lib/money";
import type { FxInfo, RowFx } from "@/lib/types";

/** A line under a page title when any number on the page was converted into the company currency, or left out for want of a rate. */
export function FxBanner({ fx }: { fx: FxInfo | undefined }) {
  if (!fx || (fx.converted_count === 0 && fx.missing_count === 0)) return null;
  const rates = fx.rates_used.map((r) => `${r.currency} at ${r.rate}${r.rate_date ? ` (rate of ${r.rate_date}${r.stale ? ", old" : ""})` : ""}`).join(", ");
  return (
    <div className="ll-fxnote" role="status" data-testid="fx-banner">
      {fx.converted_count > 0 ? <p><strong>Converted into {fx.base}.</strong> {fx.converted_count} amount{fx.converted_count === 1 ? "" : "s"} in another currency {fx.converted_count === 1 ? "was" : "were"} converted at a manual rate: {rates}. The original amounts are kept and shown on each row.</p> : null}
      {fx.missing_count > 0 ? <p className="ll-neg"><strong>{fx.missing_count} amount{fx.missing_count === 1 ? " is" : "s are"} left out.</strong> No exchange rate has been entered for {fx.missing_count === 1 ? "its" : "their"} currency. <Link href="/reports#rates">Add a rate</Link>.</p> : null}
    </div>
  );
}

/** An amount in its own currency, with the converted amount, the rate and its date next to it when the currency is not the company's. */
export function FxAmount({ minor, currency, fx }: { minor: number; currency: string; fx: RowFx | null | undefined }) {
  if (!fx) return <span className="ll-num">{moneyIn(minor, currency)}</span>;
  if (fx.missing) return <span className="ll-fxamt"><span className="ll-num">{moneyIn(minor, currency)}</span><Badge tone="warning">no rate</Badge></span>;
  return (
    <span className="ll-fxamt" title={`Converted at ${fx.rate}, the manual rate of ${fx.rate_date}${fx.stale ? " (old)" : ""}`}>
      <span className="ll-num">{moneyIn(minor, currency)}</span>
      <span className="ll-fxamt__to">{moneyIn(fx.base_minor ?? 0, fx.base_currency)} at {fx.rate}</span>
    </span>
  );
}
