"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Badge, Button, Card, DataTable, EmptyState, FilterBar, SegmentedControl, TableSkeleton, notify, type Column } from "@sendora/ui-kit";
import { FxAmount, FxBanner } from "@/components/Fx";
import { LoadError, PageHead } from "@/components/Parts";
import { api, get } from "@/lib/api";
import { useRole } from "@/lib/hooks";
import { BILL_STATE, finding, sevTone } from "@/lib/labels";
import type { BillRow } from "@/lib/types";

const FILTERS = [{ value: "all", label: "All" }, { value: "needs_review,inbox", label: "Needs review" }, { value: "approved,posted_draft", label: "Approved" }, { value: "paid", label: "Paid" }, { value: "rejected", label: "Rejected" }];

export default function BillsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const { canWrite, known } = useRole();
  const [f, setF] = useState("needs_review,inbox");
  const [over, setOver] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const q = useQuery({ queryKey: ["bills", f], queryFn: () => get<BillRow[]>(f === "all" ? "/bills" : `/bills?status=${f}`) });
  const up = useMutation({
    mutationFn: async (fl: File) => api<{ duplicate: boolean; bill_id?: number }>("/documents/upload", { method: "POST", raw: await fl.arrayBuffer(), headers: { "x-filename": fl.name, "content-type": "application/octet-stream" } }),
    onSuccess: (r) => { notify.success(r.duplicate ? "That file was already received, nothing new was added." : "Read the bill and added it to the review queue."); qc.invalidateQueries(); if (r.bill_id) router.push(`/review?bill=${r.bill_id}`); },
    onError: (e: Error) => notify.error("Could not upload", e.message),
  });
  const upload = (x: File | undefined) => { if (x && (canWrite || !known)) up.mutate(x); }; // before the role is known the server decides (a viewer gets a plain 403 message)
  const columns: Column<BillRow>[] = [
    { key: "vendor", header: "Vendor", width: "1.4fr", render: (r) => r.vendor || "Unknown vendor", sortValue: (r) => r.vendor },
    { key: "num", header: "Number", width: "110px", render: (r) => r.number, sortValue: (r) => r.number },
    { key: "due", header: "Due", width: "110px", render: (r) => r.due_date ?? "", sortValue: (r) => r.due_date ?? "" },
    { key: "total", header: "Total", width: "170px", align: "right", render: (r) => <FxAmount minor={r.total_minor} currency={r.currency} fx={r.fx} />, sortValue: (r) => r.fx?.base_minor ?? r.total_minor },
    { key: "state", header: "State", width: "130px", render: (r) => <Badge tone={BILL_STATE[r.status]?.tone}>{BILL_STATE[r.status]?.label ?? r.status}</Badge>, sortValue: (r) => r.status },
    { key: "flags", header: "Findings", width: "1.6fr", render: (r) => <span className="sx-row" style={{ flexWrap: "nowrap", overflow: "hidden" }}>{r.flags.slice(0, 3).map((x) => <Badge key={x.kind} tone={sevTone(x.severity)}>{finding(x.kind).label}</Badge>)}{r.flags.length > 3 ? <Badge>+{r.flags.length - 3}</Badge> : null}</span>, sortValue: (r) => r.flags.length },
  ];
  return (
    <div className="ll-page" data-dropzone data-over={over || undefined}
      onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setOver(true); } }} onDragLeave={(e) => { if (e.currentTarget === e.target) setOver(false); }}
      onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files?.[0]); }}>
      <PageHead title="Bills and payables" sub="Everything vendors sent. New bills are read, checked by code, and wait here for a person."
        actions={<><input ref={file} type="file" accept="application/pdf,image/png,image/jpeg" hidden aria-label="Choose a bill to upload" onChange={(e) => { upload(e.target.files?.[0]); e.target.value = ""; }} />
          <Button variant="primary" disabled={!canWrite} disabledReason="Your sign in can read but not change" onClick={() => file.current?.click()} feedback={false}>Upload a bill</Button></>} />
      {q.data && q.data.some((b) => b.fx) ? <div className="ll-fxnote" role="status"><p><strong>Some bills are in another currency.</strong> Each one shows its own amount first, then the amount in {q.data.find((b) => b.fx)?.fx?.base_currency} at the manual rate used. A bill with no rate is flagged and left out of totals.</p></div> : null}
      <FilterBar><SegmentedControl label="State" value={f} onChange={setF} options={FILTERS} /></FilterBar>
      {q.isError ? <LoadError error={q.error} onRetry={() => q.refetch()} what="bills" /> : !q.data ? <TableSkeleton rows={8} columns={6} /> : q.data.length === 0 ? <Card><EmptyState title="No bills here" body={f === "needs_review,inbox" || f === "all" ? "Upload a PDF (or drop one on this page), or use Run now to read the mailbox." : "No bill is in this state."} /></Card> : <DataTable label="Bills" rows={q.data} rowKey={(r) => String(r.id)} columns={columns} height={560} onRowOpen={(r) => router.push(`/review?bill=${r.id}`)} />}
    </div>
  );
}
