"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, Dialog, EmptyState, Field, notify } from "@sendora/ui-kit";
import { ListSkeleton, LoadError, PageHead } from "@/components/Parts";
import { get, post } from "@/lib/api";
import { useRole } from "@/lib/hooks";
import { finding, sevTone } from "@/lib/labels";
import type { ExceptionRow } from "@/lib/types";

export default function ExceptionsPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["exceptions"], queryFn: () => get<ExceptionRow[]>("/exceptions") });
  const { canWrite } = useRole();
  const [asking, setAsking] = useState<ExceptionRow | null>(null);
  const [why, setWhy] = useState("");
  const done = useMutation({ mutationFn: (v: { id: number; note: string }) => post(`/exceptions/${v.id}/resolve`, { note: v.note }), onSuccess: () => { notify.success("Marked as dealt with."); setAsking(null); setWhy(""); qc.invalidateQueries(); }, onError: (e: Error) => notify.error("Could not update", e.message) });
  if (q.isError) return <div className="ll-page"><PageHead title="Exceptions" /><LoadError error={q.error} onRetry={() => q.refetch()} what="exceptions" /></div>;
  if (!q.data) return <div className="ll-page"><PageHead title="Exceptions" /><ListSkeleton /></div>;
  return (
    <div className="ll-page">
      <PageHead title="Exceptions" sub="Things the checks found that a person has to look at. Nothing here moves money." />
      {q.data.length === 0 ? <Card><EmptyState title="Nothing needs you" body="No open exceptions." /></Card> : (
        <Card><div className="ll-stack">{q.data.map((e) => {
          const f = finding(e.kind);
          return (
            <div key={e.id} className="ll-field" style={{ gridTemplateColumns: "1fr auto" }}>
              <span><Badge tone={sevTone(e.severity)}>{f.label}</Badge> <span>{e.detail}</span><br /><span className="ll-mini" style={{ fontSize: "var(--sx-text-caption)", color: "var(--sx-ink-2)" }}>{f.help}</span></span>
              <span className="sx-row">
                {e.ref_type === "bill" ? <Link className="sx-btn sx-btn--sm" href={`/review?bill=${e.ref_id}`}>Open bill</Link> : e.ref_type === "bank_txn" || e.ref_type === "bank" ? <Link className="sx-btn sx-btn--sm" href="/reconcile">Open bank lines</Link> : null}
                <Button size="sm" disabled={!canWrite} disabledReason="Your sign in can read but not change" onClick={async () => { if (e.severity === "block") { setWhy(""); setAsking(e); } else await done.mutateAsync({ id: e.id, note: "" }); }}>Mark dealt with</Button>
              </span>
            </div>);
        })}</div></Card>)}
      <Dialog open={asking !== null} onOpenChange={(o) => !o && setAsking(null)} title="This finding blocks approval" description={asking ? `${finding(asking.kind).label}. Closing it takes the block off the bill, so write down why that is safe. The reason goes in the audit log.` : undefined}
        actions={<Button variant="primary" disabled={!why.trim()} disabledReason="Write the reason first" onClick={async () => { if (asking) await done.mutateAsync({ id: asking.id, note: why.trim() }); }}>Close it with this reason</Button>}>
        <Field label="Why is it safe to close this (required)" value={why} onChange={setWhy} />
      </Dialog>
    </div>
  );
}
