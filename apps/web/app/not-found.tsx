import Link from "next/link";

export default function NotFound() {
  return (
    <main className="ll-page" id="main" style={{ maxWidth: 560, margin: "89px auto", padding: "0 16px" }}>
      <h1 className="ll-title">That page does not exist</h1>
      <p className="ll-sub">The address may be old or mistyped.</p>
      <p><Link href="/">Go to the cash overview</Link></p>
    </main>
  );
}
