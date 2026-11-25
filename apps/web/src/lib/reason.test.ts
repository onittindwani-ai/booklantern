import assert from "node:assert/strict";
import { test } from "node:test";
import { realReason } from "./reason.ts";

test("a one character note, a row of one letter and a repeated pair are not reasons", () => {
  for (const n of ["", "x", "ok", "aaaaaaaaaaaaaaaa", "ok ok ok ok ok ok", "............", "a a a a a a a a"]) assert.equal(realReason(n), false, n);
});

test("a short sentence that says what was checked is a reason", () => {
  for (const n of ["Phoned the vendor", "Vendor confirmed the total by phone", "Owner decision: account confirmed"]) assert.equal(realReason(n), true, n);
});
