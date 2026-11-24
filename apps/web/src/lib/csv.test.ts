import assert from "node:assert/strict";
import { test } from "node:test";
import { missingColumns, parseCsv, summariseCsv } from "./csv.ts";

test("reads quoted cells, commas inside quotes and both line endings", () => {
  const rows = parseCsv('Date,Description,Amount\r\n2026-11-30,"POS, HARDWARE ""WORLD""",-87.35\n');
  assert.deepEqual(rows, [["Date", "Description", "Amount"], ["2026-11-30", 'POS, HARDWARE "WORLD"', "-87.35"]]);
});

test("summarises a statement", () => {
  const s = summariseCsv("Date,Description,Amount\n2026-11-30,ACH CREDIT,125.00\n2026-11-29,PAYROLL,-6500.00\n");
  assert.equal(s.rows, 2);
  assert.deepEqual(s.columns, ["Date", "Description", "Amount"]);
  assert.equal(s.preview.length, 2);
});

test("skips a byte order mark and blank lines", () => {
  const s = summariseCsv("\uFEFFDate\n\n2026-11-30\n\n");
  assert.deepEqual(s.columns, ["Date"]);
  assert.equal(s.rows, 1);
});

test("limits the preview", () => {
  const body = Array.from({ length: 20 }, (_, i) => `2026-11-${String(i + 1).padStart(2, "0")}`).join("\n");
  const s = summariseCsv(`Date\n${body}`);
  assert.equal(s.rows, 20);
  assert.equal(s.preview.length, 5);
});

test("names the required columns a file does not have, in any case", () => {
  assert.deepEqual(missingColumns(["date", " AMOUNT "], ["Date", "Description", "Amount"]), ["Description"]);
  assert.deepEqual(missingColumns(["Date", "Description", "Amount"], ["Date", "Description", "Amount"]), []);
});

test("an empty file has no columns and no rows", () => {
  assert.deepEqual(summariseCsv(""), { columns: [], rows: 0, preview: [] });
});
