"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, DataTable, EmptyState, FilterBar, SegmentedControl, TableSkeleton, notify } from "@sendora/ui-kit";
import { CsvFileInput } from "@/components/CsvFileInput";
import { LoadError, PageHead } from "@/components/Parts";
import { get, post, api } from "@/lib/api";
import { useRole } from "@/lib/hooks";
import { money, moneyIn } from "@/lib/money";
import type { BankPage, BankRow, Candidate } from "@/lib/types";

const FILTERS = [{ value: "unmatched,suggested,exception", label: "Needs attention" }, { value: "matched", label: "Matched" }, { value: "all", label: "All" }, { value: "table", label: "Table of every line" }];
const STATUS_TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = { matched: "success", suggested: "warning", unmatched: "neutral", exception: "danger" };
const STATUS_LABEL: Record<string, string> = { matched: "Matched", suggested: "Suggested", unmatched: "Not matched", exception: "Check this" };

export default function ReconcilePage() {
  const qc = useQueryClient();
  const { canWrite } = useRole();
  const [f, setF] = useState("unmatched,suggested,exception");
  const [sel, setSel] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);
  const [csv, setCsv] = useState("");
  const [fileKey, setFileKey] = useState(0);
  const [acct, setAcct] = useState("");
  const accts = useQuery({ queryKey: ["bank-accounts"], queryFn: () => get<{ id: number; name: string; currency: string }[]>("/bank/accounts") });
  const manyAccounts = (accts.data?.length ?? 0) > 1; // with more than one bank account the statement must say which one it belongs to
  const bank = useQuery({ queryKey: ["bank", f], queryFn: () => get<BankPage>(f === "table" ? "/bank/transactions?limit=6000" : `/bank/transactions?limit=300${f === "all" ? "" : `&status=${f}`}`) });
  const cand = useQuery({ queryKey: ["cand", sel], enabled: sel !== null, queryFn: () => get<Candidate[]>(`/bank/candidates?txn_id=${sel}`) });
  const refresh = () => { qc.invalidateQueries(); };
  const link = useMutation({
    mutationFn: async (v: { txn: BankRow; c: Candidate }) => {
      const left = Math.abs(v.txn.amount_minor) - v.txn.matches.reduce((n, m) => n + m.allocated_minor, 0);
      if (left <= 0) throw new Error("This line is already fully matched. Remove its match first.");
      return post("/bank/links", { txn_id: v.txn.id, kind: v.c.kind, target_id: v.c.id, amount_minor: Math.min(left, v.c.open_minor) });
    },
    onSuccess: () => { notify.success("Linked."); refresh(); }, onError: (e: Error) => notify.error("Could not link", e.message),
  });
  const confirm = useMutation({ mutationFn: (id: number) => post(`/bank/matches/${id}/confirm`), onSuccess: () => { notify.success("Match confirmed."); refresh(); }, onError: (e: Error) => notify.error("Could not confirm", e.message) });
  const unlink = useMutation({ mutationFn: (id: number) => api(`/bank/matches/${id}`, { method: "DELETE" }), onSuccess: () => { notify.info("Match removed."); refresh(); }, onError: (e: Error) => notify.error("Could not remove", e.message) });
  const imp = useMutation({ mutationFn: () => post<{ added: number; skipped_already_imported: number; possible_duplicates: number; note?: string }>("/bank/import", { text: csv, name: "statement.csv", ...(acct ? { account_id: Number(acct) } : {}) }), onSuccess: (r) => { notify.success(`Imported ${r.added} ${r.added === 1 ? "line" : "lines"}${r.skipped_already_imported ? `, skipped ${r.skipped_already_imported} already here` : ""}${r.possible_duplicates ? `, ${r.possible_duplicates} look like duplicates (see Exceptions)` : ""}.${r.note ? ` ${r.note}` : ""}`); setCsv(""); setFileKey((k) => k + 1); refresh(); }, onError: (e: Error) => notify.error("Could not import", e.message) });
  const rows = bank.data?.rows ?? [];
  const current = rows.find((r) => r.id === sel) ?? null;
  const dropOn = (c: Candidate, txnId: number) => { const t = rows.find((r) => r.id === txnId); if (t) link.mutate({ txn: t, c }); };
  return (
    <div className="ll-page">
      <PageHead title="Reconciliation" sub="Bank lines on the left, open invoices and bills on the right. Drag a line onto one, or select a line and press L on a row to link it. Statements come in as CSV files only." />
      <Card title="Import a bank statement (CSV)">
        <div className="sx-row">
          {manyAccounts ? (
            <label className="sx-label" style={{ display: "grid", gap: 5 }}>Bank account
              <select className="ll-select" value={acct} onChange={(e) => setAcct(e.target.value)}>
                <option value="">Choose the account</option>
                {accts.data!.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.currency})</option>)}
              </select></label>
          ) : null}
          <CsvFileInput key={fileKey} onText={setCsv} required={["Date", "Description", "Amount"]} noun="bank line" />
          <Button variant="primary" disabled={!canWrite || !csv || (manyAccounts && !acct)} disabledReason={!canWrite ? "Your sign in can read but not change" : !csv ? "Choose a CSV file first" : "Choose the bank account first"} onClick={async () => { await imp.mutateAsync(); }}>Import</Button>
        </div>
      </Card>
      <FilterBar><SegmentedControl label="Show" value={f} onChange={setF} options={FILTERS} /></FilterBar>
      {f === "table" && bank.data ? (
        <div className="ll-noopen"><DataTable label="Every bank line" rows={bank.data.rows} rowKey={(r) => String(r.id)} height={560} columns={[
          { key: "d", header: "Date", width: "110px", render: (r: BankRow) => r.posted_on, sortValue: (r: BankRow) => r.posted_on },
          { key: "t", header: "Description", width: "1fr", render: (r: BankRow) => r.description, sortValue: (r: BankRow) => r.description },
          { key: "a", header: "Amount", width: "130px", align: "right", render: (r: BankRow) => money(r.amount_minor), sortValue: (r: BankRow) => r.amount_minor },
          { key: "s", header: "Status", width: "120px", render: (r: BankRow) => STATUS_LABEL[r.status] ?? r.status, sortValue: (r: BankRow) => r.status },
        ]} /></div>
      ) : bank.isError ? <LoadError error={bank.error} onRetry={() => bank.refetch()} what="bank lines" /> : !bank.data ? <TableSkeleton rows={8} columns={4} /> : (
        <div className="ll-recon">
          <Card title={`Bank lines (${bank.data.total})`}>
            {rows.length === 0 ? <EmptyState title="Nothing here" body="Every line in this view is dealt with." /> : (
              <ul className="ll-reconlist" aria-label="Bank lines">{rows.map((t) => (
                <li key={t.id}>
                  <button type="button" className="ll-reconrow" draggable data-selected={sel === t.id} aria-pressed={sel === t.id}
                    onDragStart={(e) => { e.dataTransfer.setData("text/plain", String(t.id)); setSel(t.id); }} onClick={() => setSel(t.id)}>
                    <span className="ll-reconrow__main"><strong className="ll-num">{moneyIn(t.amount_minor, t.currency)}</strong> <span>{t.description}</span></span>
                    <span className="ll-mini">{t.posted_on} <Badge tone={STATUS_TONE[t.status]}>{STATUS_LABEL[t.status] ?? t.status}</Badge></span>
                  </button>
                  {t.matches.map((m) => (
                    <div key={m.id} className="ll-matchline"><span>{m.number} {money(m.allocated_minor)} <span className="ll-mini">score {m.score}</span></span>
                      <span className="sx-row">{m.status === "suggested" ? <Button size="sm" disabled={!canWrite} disabledReason="Your sign in can read but not change" onClick={async () => { await confirm.mutateAsync(m.id); }}>Confirm</Button> : null}<Button size="sm" disabled={!canWrite} disabledReason="Your sign in can read but not change" onClick={async () => { await unlink.mutateAsync(m.id); }}>Remove</Button></span></div>))}
                </li>))}</ul>)}
          </Card>
          <Card title={current ? `Link ${money(current.amount_minor)} to` : "Open invoices and bills"}>
            {!current ? <EmptyState title="Pick a bank line" body="Select a line on the left to see what it could belong to." /> : !cand.data ? <TableSkeleton rows={4} columns={2} /> : (
              <ul className="ll-reconlist" aria-label="Open items">{cand.data.map((c) => {
                const key = `${c.kind}-${c.id}`;
                return (
                  <li key={key}>
                    <div className="ll-reconrow ll-reconrow--target" data-over={dragOver === key}
                      onDragOver={(e) => { e.preventDefault(); setDragOver(key); }} onDragLeave={() => setDragOver(null)}
                      onDrop={(e) => { e.preventDefault(); setDragOver(null); if (canWrite) dropOn(c, Number(e.dataTransfer.getData("text/plain"))); }}>
                      <span className="ll-reconrow__main"><strong>{c.number}</strong> {c.party} <span className="ll-num">{money(c.open_minor)}</span></span>
                      <Button size="sm" aria-label={`Link to ${c.number}`} disabled={!canWrite} disabledReason="Your sign in can read but not change" onClick={async () => { if (current) await link.mutateAsync({ txn: current, c }); }} onKeyDown={(e) => { if (e.key.toLowerCase() === "l" && current && canWrite) link.mutate({ txn: current, c }); }}>Link</Button>
                    </div>
                  </li>);
              })}</ul>)}
          </Card>
        </div>)}
    </div>
  );
}
