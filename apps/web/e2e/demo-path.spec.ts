import { expect, test, type Page } from "@playwright/test";
import { readdirSync } from "node:fs";
import { resolve } from "node:path";
import { call, login, resetDemo, watch } from "./helpers";

const ROOT = resolve(__dirname, "../../..");

async function findBill(page: Page, kind: string) {
  const r = await page.request.get("/api/bills?status=needs_review");
  const rows = (await r.json()) as { id: number; flags: { kind: string }[] }[];
  const hit = rows.find((b) => b.flags.some((f) => f.kind === kind));
  expect(hit, `a bill with ${kind}`).toBeTruthy();
  return hit!.id;
}

test.describe.serial("demo path", () => {
  let page: Page;
  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage({ baseURL: `http://localhost:${process.env.WEB_PORT ?? "3000"}`, viewport: { width: 1440, height: 900 } });
    await login(page);
    await resetDemo(page);
  });
  test.afterAll(async () => { await page.close(); });

  test("cockpit: the what if sliders change the forecast and the explanation stays", async () => {
    const errors = watch(page);
    await page.goto("/");
    await expect(page.getByText("Closing cash in week 13")).toBeVisible();
    await page.locator("#s-collect").fill("21");
    await expect(page.getByText("instead of")).toBeVisible();
    await page.getByRole("button", { name: "Reset the sliders" }).click();
    await expect(page.getByText("instead of")).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("review: a blocking finding needs a written reason before approval works", async () => {
    const id = await findBill(page, "wrong_company");
    await page.goto(`/review?bill=${id}`);
    await expect(page.getByText("Addressed to someone else").first()).toBeVisible();
    const approve = page.getByRole("button", { name: "Approve" });
    await expect(approve).toBeDisabled();
    await page.getByLabel(/Why approve despite/).fill("Vendor confirmed the total by phone");
    await expect(approve).toBeEnabled();
    await approve.click();
    await expect(page.getByRole("button", { name: "Post as a draft" })).toBeVisible();
    await page.getByRole("button", { name: "Post as a draft" }).click();
    await expect(page.getByText(/Nothing was posted/).first()).toBeVisible();
  });

  test("review: fixing the total in the field re-runs the checks", async () => {
    const r = await page.request.get("/api/bills?status=needs_review");
    const rows = (await r.json()) as { id: number; subtotal_minor: number; tax_minor: number; flags: { kind: string }[] }[];
    const b = rows.find((x) => x.flags.some((f) => f.kind === "wrong_total"));
    expect(b, "a bill with a wrong total").toBeTruthy();
    await page.goto(`/review?bill=${b!.id}`);
    await page.locator("#f-total_minor").fill(((b!.subtotal_minor + b!.tax_minor) / 100).toFixed(2));
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("Total does not add up")).toHaveCount(0);
  });

  test("bills: upload a PDF and land on its review page", async () => {
    const file = resolve(ROOT, "data/heldout/documents", readdirSync(resolve(ROOT, "data/heldout/documents")).filter((f) => f.endsWith(".pdf")).sort()[0]!);
    await page.goto("/bills");
    await page.setInputFiles('input[type="file"]', file);
    await expect(page).toHaveURL(/review\?bill=\d+/);
    await expect(page.getByText("The page on the left")).toBeVisible();
  });

  test("collections: a dispute stops reminders", async () => {
    await call(page, "/demo/tick");
    await page.goto("/collections");
    await page.getByRole("button", { name: "Dispute" }).first().click();
    await expect(page.getByText(/Marked in dispute/).first()).toBeVisible();
    await expect(page.locator("span.ll-mini", { hasText: "In dispute" }).first()).toBeVisible();
  });

  test("reconciliation: link a bank line by hand, then import a CSV", async () => {
    await page.goto("/reconcile");
    await page.locator("li:not(:has(.ll-matchline)) > .ll-reconrow").first().click();
    await expect(page.getByRole("list", { name: "Open items" })).toBeVisible();
    await page.getByRole("button", { name: /^Link to / }).first().click();
    await expect(page.getByText("Linked.").first()).toBeVisible();
    await page.setInputFiles('input[type="file"]', { name: "extra.csv", mimeType: "text/csv", buffer: Buffer.from("Date,Description,Amount,Currency,Reference\n2026-11-30,\"TEST DEPOSIT SAMPLE\",125.00,USD,X900\n") });
    await page.getByRole("button", { name: "Import" }).click();
    await expect(page.getByText("Imported 1 line.")).toBeVisible();
  });

  test("reports: the month end pack is a real PDF", async () => {
    const r = await page.request.get("/api/reports/month-end.pdf");
    expect(r.status()).toBe(200);
    expect((await r.body()).subarray(0, 4).toString()).toBe("%PDF");
    await page.goto("/reports");
    await expect(page.getByRole("link", { name: "Download the PDF" })).toBeVisible();
  });

  test("other currencies: a euro bill shows its own amount and the converted one, and a rate can be added", async () => {
    await page.goto("/bills");
    await expect(page.getByText("Some bills are in another currency.")).toBeVisible();
    await expect(page.getByText(/at 1\.0800/).first()).toBeVisible();
    await page.goto("/");
    await expect(page.getByTestId("fx-banner")).toContainText("Converted into USD");
    await page.goto("/reports");
    await expect(page.getByTestId("fx-banner")).toBeVisible();
    await expect(page.getByRole("gridcell", { name: "1.0800" }).first()).toBeVisible();
    await page.getByLabel("Currency code").fill("GBP");
    await page.getByLabel("USD for one unit").fill("1.2700");
    await page.getByRole("button", { name: "Save rate" }).click();
    await expect(page.getByText("Rate saved. Totals use it from its date on.")).toBeVisible();
    await expect(page.getByRole("gridcell", { name: "1.2700" }).first()).toBeVisible();
  });

  test("the app cannot be told to go live and a change without the header is refused", async () => {
    const bad = await page.request.post("/api/demo/tick", { headers: {} });
    expect(bad.status()).toBeGreaterThanOrEqual(400);
    const s = await (await page.request.get("/api/settings")).json();
    expect(s.accounting_write).toBe(false);
  });
});
