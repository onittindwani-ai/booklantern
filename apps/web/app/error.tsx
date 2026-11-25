"use client";
import { Button } from "@sendora/ui-kit";

/** Shown when a page throws while it draws. The retry button asks Next to draw it again. */
export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="ll-page" id="main" style={{ maxWidth: 560, margin: "89px auto", padding: "0 16px" }} role="alert">
      <h1 className="ll-title">Something went wrong</h1>
      <p className="ll-sub">The page could not be shown. Try again, and if it keeps happening, check the Audit log before you repeat an action.{error.digest ? ` Reference: ${error.digest}.` : ""}</p>
      <div><Button variant="primary" onClick={() => reset()}>Try again</Button></div>
    </main>
  );
}
