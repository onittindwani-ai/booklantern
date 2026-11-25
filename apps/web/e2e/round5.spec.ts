import { expect, test, type Page } from "@playwright/test";
import { call, login, resetDemo, watch } from "./helpers";

const BASE = `http://localhost:${process.env.WEB_PORT ?? "3000"}`;
const get = async (page: Page, path: string) => (await page.request.get(`/api${path}`)).json();

async function fresh(browser: import("@playwright/test").Browser, who = "owner@example.test", size = { width: 1440, height: 900 }) {
  const ctx = await browser.newContext({ baseURL: BASE, viewport: size });
  const page = await ctx.newPage();
  await login(page, who);
  return page;
}

test.describe("round 5: every fix from the walk through the screens", () => {
  test("signing in lands on the page that was asked for, and an off site next value is ignored", async ({ browser }) => {
    const ctx = await browser.newContext({ baseURL: BASE });
    const page = await ctx.newPage();
    await page.goto("/audit");
    await expect(page).toHaveURL(/\/login\?next=%2Faudit$/);
    await page.getByLabel("Email").fill("owner@example.test");
    await page.getByLabel("Password").fill("demo-password-1");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: "Audit log" })).toBeVisible();
    await ctx.clearCookies();
    await page.goto("/login?next=//evil.example");
    await page.getByLabel("Email").fill("owner@example.test");
    await page.getByLabel("Password").fill("demo-password-1");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: "Cash cockpit" })).toBeVisible();
    await ctx.close();
  });

  test("G then a number goes to that page, and is ignored while typing or in a dialog", async ({ browser }) => {
    const page = await fresh(browser);
    await resetDemo(page);
    await page.goto("/"); await page.waitForLoadState("networkidle");
    await page.keyboard.press("g"); await page.keyboard.press("3");
    await expect(page.getByRole("heading", { name: "Bills and payables" })).toBeVisible();
    await page.goto("/collections"); await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "Promise to pay" }).first().click();
    await page.getByLabel(/Promised date/).fill("g4");
    await expect(page).toHaveURL(/\/collections$/);
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.context().close();
  });

  test("on a phone the Pause all and Sign out buttons stay in the top bar", async ({ browser }) => {
    const page = await fresh(browser, "owner@example.test", { width: 390, height: 844 });
    await page.goto("/"); await page.waitForLoadState("networkidle");
    await expect(page.getByRole("button", { name: "Pause all" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login/);
    await page.context().close();
  });

  test("the kill switch button and the palette say what they will do, and the banner is truthful", async ({ browser }) => {
    const page = await fresh(browser);
    await resetDemo(page);
    await page.goto("/"); await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "Pause all" }).click();
    await page.getByRole("button", { name: "Pause all" }).last().click();
    await expect(page.locator(".ll-banner")).toContainText("Kill switch is on.");
    await expect(page.locator(".ll-banner")).toContainText("No reminder goes out and nothing is posted to accounting.");
    await expect(page.getByRole("button", { name: "Turn the kill switch off" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Pause all" })).toHaveCount(0);
    await page.keyboard.press("Meta+k");
    await expect(page.getByRole("option", { name: /Turn the kill switch off/ })).toBeVisible();
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Turn the kill switch off" }).click();
    await expect(page.locator(".ll-banner")).not.toContainText("Kill switch is on.");
    await page.context().close();
  });

  test("a viewer sees every write control disabled with a reason and never triggers a 403", async ({ browser }) => {
    const owner = await fresh(browser);
    await resetDemo(owner);
    await owner.context().close();
    const page = await fresh(browser, "viewer@example.test");
    const errors = watch(page);
    const off = async (name: RegExp | string, nth = 0) => expect(page.getByRole("button", { name }).nth(nth)).toBeDisabled();
    await expect(page.getByRole("button", { name: "Run now" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "+1 day" })).toBeDisabled();
    await page.keyboard.press("Meta+k");
    await expect(page.getByRole("option", { name: /Run every job now/ })).toHaveCount(0);
    await expect(page.getByRole("option", { name: /Reset the demo data/ })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await page.goto("/bills"); await page.waitForLoadState("networkidle"); await off("Upload a bill");
    const id = (await get(page, "/bills?status=needs_review"))[3].id;
    await page.goto(`/review?bill=${id}`); await page.waitForLoadState("networkidle");
    await off("Approve"); await off("Reject");
    await page.goto("/collections"); await page.waitForLoadState("networkidle");
    await off("Promise to pay"); await off("Dispute"); await off("Payment link");
    await page.goto("/reconcile"); await page.waitForLoadState("networkidle"); await off("Import");
    await page.goto("/exceptions"); await page.waitForLoadState("networkidle"); await off("Mark dealt with");
    await page.goto("/integrations"); await page.waitForLoadState("networkidle"); await off("Test the one in use");
    expect(errors.filter((e) => e.includes("403"))).toEqual([]);
    await page.context().close();
  });

  test("a blank scan cannot be approved, a typed vendor is kept, and a bad amount is explained before anything is sent", async ({ browser }) => {
    const page = await fresh(browser);
    await resetDemo(page);
    const scan = (await get(page, "/bills?status=needs_review")).find((b: { vendor: string; total_minor: number }) => !b.vendor && b.total_minor === 0);
    await page.goto(`/review?bill=${scan.id}`); await page.waitForLoadState("networkidle");
    await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Approve", exact: true }).hover();
    await expect(page.getByText(/Fill in the vendor, bill date, total and save first/)).toBeVisible();
    await page.locator("#f-vendor").fill("Cobalt Office Supply");
    await page.locator("#f-total_minor").fill("abc");
    await expect(page.getByText("Type an amount like 1250.00, with no more than 2 decimals.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Save changes" })).toBeDisabled();
    await page.locator("#f-total_minor").fill("120.50");
    await page.locator("#f-subtotal_minor").fill("120.50");
    await page.locator("#f-issue_date").fill("2026-11-20");
    await page.locator("#f-issue_date").fill("2026-13-45");
    await expect(page.getByText("Type the date like 2026-12-15.")).toBeVisible();
    await page.locator("#f-issue_date").fill("2026-11-20");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText(/^Saved\./)).toBeVisible();
    await page.reload(); await page.waitForLoadState("networkidle");
    await expect(page.locator("#f-vendor")).toHaveValue("Cobalt Office Supply");
    await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeEnabled();
    await page.context().close();
  });

  test("the page of a scanned bill is shown next to the fields, and a dead picture falls back to a note", async ({ browser }) => {
    const page = await fresh(browser);
    await resetDemo(page);
    const scan = (await get(page, "/bills?status=needs_review")).find((b: { vendor: string; total_minor: number }) => !b.vendor && b.total_minor === 0);
    await page.goto(`/review?bill=${scan.id}`); await page.waitForLoadState("networkidle");
    const img = page.locator(".ll-viewer__img");
    await expect(img).toBeVisible();
    expect(await img.evaluate((i: HTMLImageElement) => i.complete && i.naturalWidth > 100)).toBe(true);
    await expect(page.getByText(/This page is a picture and the offline reader cannot read pictures/)).toBeVisible();
    await page.context().close();
  });

  test("a blocking finding can only be closed with a written reason", async ({ browser }) => {
    const page = await fresh(browser);
    await resetDemo(page);
    await page.goto("/exceptions"); await page.waitForLoadState("networkidle");
    const row = page.locator(".ll-field", { hasText: "Blocks approval" }).or(page.locator(".ll-field", { hasText: "Total does not add up" })).first();
    await row.getByRole("button", { name: "Mark dealt with" }).click();
    const close = page.getByRole("button", { name: "Close it with this reason" });
    await expect(close).toBeDisabled();
    await page.getByLabel(/Why is it safe to close this/).fill("The vendor sent a corrected bill");
    await close.click();
    await expect(page.getByText("Marked as dealt with.")).toBeVisible();
    const audit = await get(page, "/audit?limit=3");
    expect(audit.some((a: { action: string; detail: { note?: string } }) => a.action === "exception.resolved" && a.detail.note === "The vendor sent a corrected bill")).toBe(true);
    await page.context().close();
  });

  test("a promise to pay needs a real date that is not in the past", async ({ browser }) => {
    const page = await fresh(browser);
    await resetDemo(page);
    await page.goto("/collections"); await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "Promise to pay" }).first().click();
    const save = page.getByRole("button", { name: "Save the promise" });
    await page.getByLabel(/Promised date/).fill("2026-13-45");
    await expect(save).toBeDisabled();
    await page.getByLabel(/Promised date/).fill("2020-01-01");
    await page.getByLabel("Note").click();
    await expect(page.getByText(/The date is in the past/)).toBeVisible();
    await expect(save).toBeDisabled();
    await page.getByLabel(/Promised date/).fill("2026-12-20");
    await expect(save).toBeEnabled();
    await save.click();
    await expect(page.getByText(/Promise recorded/)).toBeVisible();
    await page.getByRole("tab", { name: /Promises/ }).click();
    await expect(page.getByText("2026-12-20").first()).toBeVisible();
    await page.context().close();
  });

  test("a bank file without the right columns says which are needed, with no words from another product, and the import message has no gaps", async ({ browser }) => {
    const page = await fresh(browser);
    await resetDemo(page);
    await page.goto("/reconcile"); await page.waitForLoadState("networkidle");
    await page.setInputFiles('input[type="file"]', { name: "a.csv", mimeType: "text/csv", buffer: Buffer.from("foo,bar\n1,2\n") });
    await expect(page.getByRole("alert").filter({ hasText: "needs these columns: Date, Description, Amount" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Import" })).toBeDisabled();
    await page.setInputFiles('input[type="file"]', { name: "b.csv", mimeType: "text/csv", buffer: Buffer.from("Date,Description,Amount,Currency,Reference\n2026-11-30,TEST DEPOSIT FICTIONAL,125.00,USD,Z1\n") });
    await expect(page.getByText(/1 row, 5 columns/)).toBeVisible();
    await expect(page.locator(".ll-file")).not.toContainText(/phone|call/i);
    await page.getByRole("button", { name: "Import" }).click();
    await expect(page.getByText("Imported 1 line.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Import" })).toHaveAttribute("data-state", "idle");
    await page.setInputFiles('input[type="file"]', { name: "c.csv", mimeType: "text/csv", buffer: Buffer.from("Date,Description,Amount,Currency,Reference\n2026-11-30,TEST EUR,12.34,EUR,Z2\n") });
    await page.getByRole("button", { name: "Import" }).click();
    await expect(page.getByText(/this account is in USD and the line is in EUR/)).toBeVisible();
    await expect(page.locator("body")).not.toContainText("undefined");
    await page.context().close();
  });

  test("a file dropped on the Bills page uploads it, and a file dropped anywhere else does not make the browser leave", async ({ browser }) => {
    const page = await fresh(browser);
    await resetDemo(page);
    await page.goto("/exceptions"); await page.waitForLoadState("networkidle");
    const prevented = await page.evaluate(() => { const dt = new DataTransfer(); dt.items.add(new File(["x"], "x.pdf", { type: "application/pdf" })); const e = new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }); document.body.dispatchEvent(e); return e.defaultPrevented; });
    expect(prevented).toBe(true);
    await expect(page).toHaveURL(/\/exceptions$/);
    await page.goto("/bills"); await page.waitForLoadState("networkidle");
    const bad = await page.evaluate(() => { const dt = new DataTransfer(); dt.items.add(new File(["not a bill"], "notes.txt", { type: "text/plain" })); const t = document.querySelector("[data-dropzone]")!; t.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true })); return true; });
    expect(bad).toBe(true);
    await expect(page.getByText("Only PDF, PNG and JPEG files are accepted.")).toBeVisible();
    await page.context().close();
  });

  test("a failed upload is a message, not an error in the console", async ({ browser }) => {
    const page = await fresh(browser);
    await resetDemo(page);
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto("/bills"); await page.waitForLoadState("networkidle");
    await page.setInputFiles('input[type="file"]', { name: "junk.txt", mimeType: "text/plain", buffer: Buffer.from("hello") });
    await expect(page.getByText("Only PDF, PNG and JPEG files are accepted.")).toBeVisible();
    expect(errors).toEqual([]);
    await page.context().close();
  });

  test("approving a draft on the Collections page closes its request on the Approvals page", async ({ browser }) => {
    const page = await fresh(browser);
    await resetDemo(page);
    await call(page, "/demo/advance", { hours: 24 });
    await call(page, "/demo/tick");
    await page.goto("/collections"); await page.waitForLoadState("networkidle");
    await page.getByRole("tab", { name: /Drafts/ }).click();
    await expect(page.getByText("Waiting for you").first()).toBeVisible();
    await page.getByRole("button", { name: "Approve" }).first().click();
    await expect(page.getByText(/Approved\. It goes out/)).toBeVisible();
    await page.goto("/approvals"); await page.waitForLoadState("networkidle");
    await expect(page.getByText("Waiting (0)")).toBeVisible();
    await expect(page.getByText(/approved by/).first()).toBeVisible();
    await page.context().close();
  });

  test("the audit log reads in plain words and every row opens a detail sheet", async ({ browser }) => {
    const page = await fresh(browser);
    await resetDemo(page);
    await call(page, "/demo/tick");
    await page.goto("/audit"); await page.waitForLoadState("networkidle");
    await expect(page.getByText("Bill read and added").first()).toBeVisible();
    await expect(page.locator("body")).not.toContainText("bill.created");
    await page.getByRole("button", { name: "Open" }).first().click();
    await expect(page.getByRole("dialog")).toContainText("Entry number");
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Check the chain" }).click();
    await expect(page.getByText("The audit log is intact.")).toBeVisible();
    await page.context().close();
  });

  test("the aging table says how late in words, and its footer does not promise an open that does nothing", async ({ browser }) => {
    const page = await fresh(browser);
    await resetDemo(page);
    await page.goto("/aging"); await page.waitForLoadState("networkidle");
    await page.locator(".ll-agebar button").first().click();
    await expect(page.getByText(/Not due yet|days late|31 to 60|61 to 90|Over 90/).first()).toBeVisible();
    await expect(page.locator(".ll-noopen .sx-table__footer")).toBeVisible();
    expect(await page.locator(".ll-noopen .sx-table__footer > span:last-child").evaluate((e) => getComputedStyle(e, "::after").content)).toContain("j k move");
    await page.context().close();
  });

  test("a bill that has left the queue is still shown with a closed note, and the exceptions page links to bank lines", async ({ browser }) => {
    const page = await fresh(browser);
    await resetDemo(page);
    const clean = (await get(page, "/bills?status=needs_review")).find((b: { flags: { severity: string }[]; vendor: string }) => b.vendor && !b.flags.length);
    await call(page, `/bills/${clean.id}/approve`, { note: "" });
    await call(page, `/bills/${clean.id}/post`);
    await page.goto(`/review?bill=${clean.id}`); await page.waitForLoadState("networkidle");
    await expect(page.getByText(/Nothing more can be done to it here|Post as a draft/).first()).toBeVisible();
    await page.goto("/exceptions"); await page.waitForLoadState("networkidle");
    await expect(page.getByRole("link", { name: "Open bank lines" }).first()).toBeVisible();
    await page.context().close();
  });

  test("the overview numbers count up in whole cents, never with a stray decimal, after load", async ({ browser }) => {
    const page = await fresh(browser);
    await resetDemo(page);
    await page.goto("/");
    const bad = new Set<string>();
    const start = Date.now();
    while (Date.now() - start < 2400) {
      const texts = await page.locator(".ll-stat__v").allInnerTexts();
      for (const block of texts) for (const t of block.split("\n").map((x) => x.trim()).filter(Boolean)) if (!/^-?\$[\d,]+\.\d{2}$/.test(t)) bad.add(t);
      await page.waitForTimeout(30);
    }
    expect([...bad]).toEqual([]);
    await page.context().close();
  });

  test("a payment link is shown on the invoice with a copy button, not only announced", async ({ browser }) => {
    const page = await fresh(browser);
    await resetDemo(page);
    await page.goto("/collections"); await page.waitForLoadState("networkidle");
    const row = page.locator(".ll-plan").filter({ hasText: "INV-2068" });
    await row.getByRole("button", { name: "Payment link" }).click();
    await expect(page.getByText(/Payment link created|so no link was saved/).first()).toBeVisible();
    await expect(row.getByText(/Link: /)).toContainText("INV-2068");
    await expect(row.getByRole("button", { name: "Copy link" })).toBeVisible();
    await page.context().close();
  });
});
