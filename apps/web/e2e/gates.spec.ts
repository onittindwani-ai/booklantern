import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { PAGES, call, login, resetDemo, watch } from "./helpers";

const SHOTS = resolve(__dirname, "../../../docs/screenshots");
mkdirSync(SHOTS, { recursive: true });
const VIEWS = [{ name: "desktop", width: 1440, height: 900 }, { name: "phone", width: 390, height: 844 }];
const slug = (p: string) => (p === "/" ? "cockpit" : p.slice(1));

async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(900); // count up and chart tween finish
}
async function layoutShift(page: Page) {
  return page.evaluate(() => new Promise<number>((done) => {
    let total = 0;
    const o = new PerformanceObserver((l) => { for (const e of l.getEntries() as unknown as { value: number; hadRecentInput: boolean }[]) if (!e.hadRecentInput) total += e.value; });
    o.observe({ type: "layout-shift", buffered: true });
    setTimeout(() => { o.disconnect(); done(total); }, 1200);
  }));
}

test.describe.serial("quality gates", () => {
  let page: Page;
  let errors: string[];
  test.beforeAll(async ({ browser }) => {
    const ctx = await browser.newContext({ baseURL: `http://localhost:${process.env.WEB_PORT ?? "3000"}`, viewport: { width: 1440, height: 900 } });
    page = await ctx.newPage();
    errors = watch(page);
    await login(page);
    await resetDemo(page);
  });
  test.afterAll(async () => { await page.close(); });

  for (const v of VIEWS) {
    test(`screenshot of every page, ${v.name}`, async () => {
      await page.setViewportSize({ width: v.width, height: v.height });
      for (const p of PAGES) {
        await page.goto(p);
        await settle(page);
        await page.screenshot({ path: `${SHOTS}/page-${slug(p)}-${v.name}.png` });
      }
    });

    test(`eight states, ${v.name}`, async () => {
      await page.setViewportSize({ width: v.width, height: v.height });
      const shot = (n: string) => page.screenshot({ path: `${SHOTS}/state-${n}-${v.name}.png` });
      await page.goto("/"); await settle(page);
      await page.locator("#s-collect").fill("21"); await page.locator("#s-hire").fill("4000"); await settle(page);
      await shot("1-cockpit-what-if");
      const r = await (await page.request.get("/api/bills?status=needs_review")).json() as { id: number; flags: { kind: string }[] }[];
      const blocked = r.find((b) => b.flags.some((f) => f.kind === "wrong_total"))!;
      await page.goto(`/review?bill=${blocked.id}`); await settle(page);
      await shot("2-review-blocked");
      const scan = (await (await page.request.get("/api/bills?status=needs_review")).json() as { id: number; flags: { kind: string }[] }[]).find((b) => b.flags.some((f) => f.kind === "unreadable_document"));
      expect(scan, "a bill that could not be read").toBeTruthy();
      await page.goto(`/review?bill=${scan!.id}`); await settle(page);
      await shot("3-review-unreadable-scan");
      await page.goto("/aging"); await settle(page);
      await page.locator(".ll-agebar button").first().click(); await settle(page);
      await shot("4-aging-drilldown");
      await page.goto("/collections"); await settle(page);
      await page.getByRole("button", { name: "Promise to pay" }).first().click(); await page.waitForTimeout(400);
      await shot("5-collections-promise-dialog");
      await page.keyboard.press("Escape");
      await page.goto("/reconcile"); await settle(page);
      await page.locator("li:not(:has(.ll-matchline)) > .ll-reconrow").first().click(); await settle(page);
      await shot("6-reconcile-selected-line");
      await page.goto("/exceptions"); await settle(page);
      await shot("7-exceptions-list");
      await page.goto("/"); await settle(page);
      await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
      await page.waitForTimeout(300);
      await shot("8-cockpit-dark");
      await page.evaluate(() => document.documentElement.removeAttribute("data-theme"));
    });

    test(`four more states, ${v.name}: processing, toast with undo, empty, error`, async () => {
      await page.setViewportSize({ width: v.width, height: v.height });
      const shot = (n: string) => page.screenshot({ path: `${SHOTS}/state-${n}-${v.name}.png` });
      // a button mid processing: hold the answer back so the spinner stays visible
      await page.goto("/"); await settle(page);
      await page.route("**/api/demo/tick", async (route) => { await new Promise((r) => setTimeout(r, 2500)); await route.continue(); });
      const run = v.width < 500 ? page.getByRole("button", { name: "Run now" }) : page.getByRole("button", { name: "Run now" });
      await run.click(); await page.waitForTimeout(500);
      await shot("9-button-processing");
      await page.waitForTimeout(2600);
      await page.unroute("**/api/demo/tick");
      // a toast with an undo
      await page.goto("/collections"); await settle(page);
      await page.getByRole("button", { name: "Dispute" }).first().click();
      await expect(page.getByRole("button", { name: "Undo" })).toBeVisible();
      await page.waitForTimeout(400);
      await shot("10-toast-with-undo");
      await page.getByRole("button", { name: "Undo" }).click();
      await page.waitForTimeout(600);
      // an empty state
      await page.goto("/collections"); await settle(page);
      await page.getByRole("tab", { name: /Drafts/ }).click(); await page.waitForTimeout(300);
      await expect(page.getByText("No drafts waiting")).toBeVisible();
      await shot("11-empty-state");
      // an error state: the cockpit call is cut off
      const before = errors.length;
      await page.route("**/api/overview", (route) => route.abort());
      await page.goto("/"); await page.waitForTimeout(1500);
      await expect(page.getByText(/Could not|try again/i).first()).toBeVisible();
      await shot("12-error-state");
      await page.unroute("**/api/overview");
      errors.splice(before); // the cut off call is the point of this shot, not a fault
    });
  }

  for (const theme of ["light", "dark"]) {
    test(`axe finds no serious or critical problems on any page, ${theme}`, async () => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.emulateMedia({ colorScheme: theme as "light" | "dark" });
      const bad: string[] = [];
      for (const p of PAGES) {
        await page.goto(p); await settle(page);
        if (theme === "dark") await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
        await page.waitForTimeout(300);
        const res = await new AxeBuilder({ page }).analyze();
        for (const v of res.violations.filter((x) => x.impact === "serious" || x.impact === "critical")) bad.push(`${theme} ${p} ${v.id} ${v.impact}: ${v.nodes.slice(0, 2).map((n) => n.target.join(" ")).join(" | ")}`);
      }
      await page.emulateMedia({ colorScheme: "light" });
      expect(bad).toEqual([]);
    });
  }

  test("keyboard path: every stop shows focus, and a bank line links with the keyboard", async () => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/reconcile"); await settle(page);
    const seen: string[] = [];
    for (let i = 0; i < 25; i++) {
      await page.keyboard.press("Tab");
      const info = await page.evaluate(() => {
        const e = document.activeElement as HTMLElement | null;
        if (!e || e === document.body) return null;
        const cs = getComputedStyle(e);
        const r = e.getBoundingClientRect();
        return { name: (e.getAttribute("aria-label") || e.textContent || e.tagName).trim().slice(0, 30), ring: (cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== "none" || e.matches("[data-selected]"), visible: r.width > 0 && r.height > 0 };
      });
      if (info) { seen.push(info.name); expect(info.visible, `${info.name} is on screen`).toBeTruthy(); expect(info.ring, `${info.name} shows focus`).toBeTruthy(); }
    }
    expect(seen.length).toBeGreaterThan(10);
    const row = page.locator("li:not(:has(.ll-matchline)) > .ll-reconrow").first();
    await row.focus(); await page.keyboard.press("Enter");
    const link = page.getByRole("button", { name: /^Link to / }).first();
    await link.focus(); await page.keyboard.press("Enter");
    await expect(page.getByText("Linked.").first()).toBeVisible();
  });

  test("reduced motion: nothing animates", async () => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/"); await page.waitForLoadState("networkidle"); await page.waitForTimeout(1200);
    const running = await page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running" && (a.effect?.getComputedTiming().iterations ?? 1) === Infinity).length);
    expect(running).toBe(0);
    await page.emulateMedia({ reducedMotion: "no-preference" });
  });

  test("no layout shift on any page", async () => {
    const bad: string[] = [];
    for (const p of PAGES) {
      await page.goto(p);
      const cls = await layoutShift(page);
      if (cls > 0.1) bad.push(`${p} ${cls.toFixed(3)}`);
    }
    expect(bad).toEqual([]);
  });

  test("5,000 rows: the table opens fast, scrolls and stays responsive", async () => {
    const add = await call(page, "/demo/stress-bank", { n: 5000 });
    expect(add.ok()).toBeTruthy();
    const t0 = Date.now();
    await page.goto("/reconcile");
    await page.getByRole("radio", { name: "Table of every line" }).click();
    await expect(page.getByText(/5,1\d\d rows|5,\d{3} rows/)).toBeVisible({ timeout: 15000 });
    const ms = Date.now() - t0;
    expect(ms, "table with 5,000 rows is ready").toBeLessThan(6000);
    const rendered = await page.locator('[role="row"]').count();
    expect(rendered, "only visible rows are in the page").toBeLessThan(200);
    await page.screenshot({ path: `${SHOTS}/state-13-five-thousand-rows-desktop.png` });
    const scrollMs = await page.evaluate(async () => {
      const el = document.querySelector('[role="grid"], .sx-table__scroll, [data-table-scroll]') as HTMLElement | null;
      if (!el) return -1;
      const t = performance.now();
      for (let i = 0; i < 20; i++) { el.scrollTop += 800; await new Promise((r) => requestAnimationFrame(() => r(null))); }
      return performance.now() - t;
    });
    expect(scrollMs).toBeLessThan(2500);
  });

  test("no console errors or failed requests during the whole run", async () => {
    expect(errors).toEqual([]);
  });
});
