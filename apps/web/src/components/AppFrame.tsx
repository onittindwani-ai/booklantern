"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BarChart3, ClipboardCheck, FileSearch, FileText, Gauge, Landmark, LogOut, Pause, Plug, Receipt, Send, ShieldCheck } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { AppShell, Badge, Button, CommandPalette, ConfirmDialog, notify, useTheme, type PaletteItem } from "@sendora/ui-kit";
import { api, get, post } from "@/lib/api";
import { useLiveRefresh, useMe, useRole, useSettings } from "@/lib/hooks";
import type { Overview } from "@/lib/types";

const NAV = [
  { id: "/", label: "Cash cockpit", icon: Gauge },
  { id: "/review", label: "Invoice review", icon: FileSearch },
  { id: "/bills", label: "Bills and payables", icon: Receipt },
  { id: "/aging", label: "Aging", icon: BarChart3 },
  { id: "/collections", label: "Collections", icon: Send },
  { id: "/reconcile", label: "Reconciliation", icon: Landmark },
  { id: "/exceptions", label: "Exceptions", icon: AlertTriangle },
  { id: "/reports", label: "Reports", icon: FileText },
  { id: "/integrations", label: "Integrations", icon: Plug },
  { id: "/approvals", label: "Approvals", icon: ClipboardCheck },
  { id: "/audit", label: "Audit log", icon: ShieldCheck },
];

export function AppFrame({ children }: { children: ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const qc = useQueryClient();
  const me = useMe();
  const settings = useSettings();
  const overview = useQuery({ queryKey: ["overview"], queryFn: () => get<Overview>("/overview") });
  const { setChoice } = useTheme();
  const [palette, setPalette] = useState(false);
  const [confirmKill, setConfirmKill] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  useLiveRefresh();
  const { owner, canWrite } = useRole();
  const killOn = !!settings.data?.kill_switch;

  // G then 1 to 9 goes to that page (the palette shows these shortcuts). Ignored while typing and while a dialog is open.
  useEffect(() => {
    let armed = 0;
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.closest("[role=dialog], [role=alertdialog]"))) return;
      if (e.key.toLowerCase() === "g") { armed = Date.now(); return; }
      if (armed && Date.now() - armed < 1500 && /^[1-9]$/.test(e.key)) { armed = 0; const target = NAV[Number(e.key) - 1]; if (target) router.push(target.id); return; }
      armed = 0;
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  // A file dropped on the page must not make the browser open it and leave the app. Pages with a drop box handle the drop themselves.
  useEffect(() => {
    const stop = (e: DragEvent) => { if (e.dataTransfer?.types.includes("Files") && !(e.target as HTMLElement | null)?.closest("[data-dropzone]")) e.preventDefault(); };
    window.addEventListener("dragover", stop);
    window.addEventListener("drop", stop);
    return () => { window.removeEventListener("dragover", stop); window.removeEventListener("drop", stop); };
  }, []);

  const active = NAV.find((n) => (n.id === "/" ? path === "/" : path.startsWith(n.id)))?.id ?? "/";
  const demo = me.data?.demo_mode ?? false;
  const refresh = () => qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "me" });

  const run = useMutation({
    mutationFn: () => post<{ intake: { processed: number }; reminders: { drafted: number } }>("/demo/tick"),
    onSuccess: (r) => { notify.success(`Ran every job. Read ${r.intake.processed} new bills, drafted ${r.reminders.drafted} reminders.`); refresh(); },
    onError: (e: Error) => notify.error("The run failed", e.message),
  });
  const advance = useMutation({
    mutationFn: (hours: number) => post("/demo/advance", { hours }),
    onSuccess: () => { notify.info("Moved the demo clock forward."); refresh(); },
    onError: (e: Error) => notify.error("Could not move the clock", e.message),
  });
  const toggleKill = useMutation({
    mutationFn: (on: boolean) => post("/settings", { kill_switch: on }),
    onSuccess: () => { refresh(); qc.invalidateQueries({ queryKey: ["settings"] }); },
    onError: (e: Error) => notify.error("Could not change the kill switch", e.message),
  });
  const reset = useMutation({
    mutationFn: () => post("/demo/reset"),
    onSuccess: () => { notify.success("Demo data reset."); refresh(); },
    onError: (e: Error) => notify.error("Could not reset", e.message),
  });

  const items: PaletteItem[] = useMemo(() => [
    ...NAV.map((n, i) => ({ id: `go-${n.id}`, label: `Go to ${n.label}`, group: "Navigate", shortcut: i < 9 ? ["G", String(i + 1)] : undefined, onSelect: () => router.push(n.id) })),
    { id: "signout", label: "Sign out", group: "Account", onSelect: () => void api("/session", { method: "DELETE" }).catch(() => null).then(() => window.location.assign("/login")) },
    ...(owner ? [killOn ? { id: "kill", label: "Turn the kill switch off", group: "Account", onSelect: () => toggleKill.mutate(false) } : { id: "kill", label: "Pause everything (kill switch)", group: "Account", onSelect: () => setConfirmKill(true) }] : []),
    { id: "dark", label: "Switch to dark theme", group: "Actions", keywords: ["espresso", "night"], onSelect: () => setChoice("dark") },
    { id: "light", label: "Switch to light theme", group: "Actions", onSelect: () => setChoice("light") },
    ...(demo && canWrite ? [{ id: "run", label: "Run every job now", group: "Demo", onSelect: () => run.mutate() }, { id: "adv", label: "Move the demo clock forward one day", group: "Demo", onSelect: () => advance.mutate(24) }] : []),
    ...(demo && owner ? [{ id: "reset", label: "Reset the demo data", group: "Demo", onSelect: () => setConfirmReset(true) }] : []),
  ], [router, setChoice, demo, run, advance, owner, canWrite, killOn, toggleKill]);

  const s = settings.data;
  const o = overview.data;
  return (
    <>
      {/* One status strip that is always there, so nothing below it jumps when the mode is known. */}
      {s?.kill_switch ? (
        <div className="ll-banner ll-banner--danger" role="status"><strong>Kill switch is on.</strong> <span className="ll-hide-sm">No reminder goes out and nothing is posted to accounting.</span> <Button size="sm" variant="ghost" disabled={!owner} disabledReason="Only the owner can turn it off" onClick={async () => { await toggleKill.mutateAsync(false); }}>Turn it off</Button></div>
      ) : s?.effective_mode === "draft" ? (
        <div className="ll-banner" role="status"><strong>Draft mode.</strong> <span className="ll-hide-sm">Nothing is sent and nothing is posted to your accounting system. Drafts are saved.</span></div>
      ) : s && demo ? (
        <div className="ll-banner ll-banner--info" role="status"><strong>Demo mode.</strong> <span className="ll-grow ll-hide-sm">Sample company and bills. An offline stand in reads the documents.</span><span className="ll-grow show-sm-only" />
          <Button size="sm" variant="primary" disabled={!canWrite} disabledReason="Your sign in can read but not change" onClick={async () => { await run.mutateAsync(); }}>Run now</Button>
          <Button size="sm" disabled={!canWrite} disabledReason="Your sign in can read but not change" onClick={async () => { await advance.mutateAsync(24); }}>+1 day</Button></div>
      ) : s ? (
        <div className="ll-banner ll-banner--live" role="status"><strong>Live.</strong> <span className="ll-hide-sm">Live. Reminders go out after approval. Posting to accounting needs its own switch.</span></div>
      ) : (
        <div className="ll-banner ll-banner--info" role="status">Checking the mode...</div>
      )}
      <AppShell
        productName="Booklantern"
        nav={NAV.map((n) => ({ ...n, count: n.id === "/review" ? o?.bills_to_review || undefined : n.id === "/exceptions" ? o?.open_exceptions || undefined : n.id === "/approvals" ? o?.pending_approvals || undefined : undefined }))}
        activeId={active}
        onNavigate={(id) => router.push(id)}
        onOpenPalette={() => setPalette(true)}
        breadcrumbs={["Booklantern", NAV.find((n) => n.id === active)?.label ?? ""]}
        topRight={
          <>
            {owner ? <Button size="sm" variant="ghost" feedback={false} className="ll-iconify" aria-label={killOn ? "Turn the kill switch off" : "Pause all"} onClick={() => (killOn ? toggleKill.mutate(false) : setConfirmKill(true))}><Pause size={14} aria-hidden /><span className="ll-hide-sm">{killOn ? "Turn it off" : "Pause all"}</span></Button> : null}
            {me.data ? <span className="ll-hide-sm"><Badge tone="accent">{me.data.role}</Badge></span> : null}
            <Button size="sm" variant="ghost" feedback={false} className="ll-iconify" aria-label="Sign out" onClick={async () => { await api("/session", { method: "DELETE" }).catch(() => null); window.location.assign("/login"); }}><LogOut size={14} aria-hidden /><span className="ll-hide-sm">Sign out</span></Button>
          </>
        }
      >
        {children}
      </AppShell>
      <CommandPalette items={items} open={palette} onOpenChange={setPalette} />
      <ConfirmDialog open={confirmKill} onOpenChange={setConfirmKill} title="Pause everything?" description="The kill switch stops every reminder and every post to accounting at once. You can turn it off again from the banner or the top bar." confirmLabel="Pause all" destructive onConfirm={() => toggleKill.mutate(true)} />
      <ConfirmDialog open={confirmReset} onOpenChange={setConfirmReset} title="Reset the demo?" description="This puts the sample seed data back and clears everything you did in the demo." confirmLabel="Reset" destructive onConfirm={() => reset.mutate()} />
    </>
  );
}
