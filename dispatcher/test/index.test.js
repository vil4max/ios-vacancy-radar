import assert from "node:assert/strict";
import { test } from "node:test";

import { dueSlot, kyivClock, tick } from "../src/index.js";

const EMPTY = { days: {} };

test("Kyiv clock follows summer and winter time", () => {
  assert.deepEqual(kyivClock(new Date("2026-07-15T05:15:00Z")), { day: "2026-07-15", minutes: 8 * 60 + 15 });
  assert.deepEqual(kyivClock(new Date("2026-01-15T06:15:00Z")), { day: "2026-01-15", minutes: 8 * 60 + 15 });
});

test("a slot is due only after its lag and before the evening cutoff", () => {
  assert.equal(dueSlot(new Date("2026-07-15T05:14:00Z"), EMPTY), null);
  assert.deepEqual(dueSlot(new Date("2026-07-15T05:15:00Z"), EMPTY), { day: "2026-07-15", slot: 8 });
  assert.deepEqual(dueSlot(new Date("2026-07-15T10:00:00Z"), EMPTY), { day: "2026-07-15", slot: 8 });
  assert.deepEqual(dueSlot(new Date("2026-07-15T11:20:00Z"), EMPTY), { day: "2026-07-15", slot: 14 });
  assert.equal(dueSlot(new Date("2026-07-15T18:00:00Z"), EMPTY), null);
});

test("a completed slot is not dispatched again", () => {
  const slots = { days: { "2026-07-15": { slots: [8] } } };
  assert.equal(dueSlot(new Date("2026-07-15T06:00:00Z"), slots), null);
  assert.deepEqual(dueSlot(new Date("2026-07-15T11:30:00Z"), slots), { day: "2026-07-15", slot: 14 });
});

function fakeGitHub({ slots = EMPTY, active = 0 } = {}) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url, method: init.method ?? "GET" });
    if (url.includes("collect_slots.json")) return Response.json(slots);
    if (url.includes("/runs?status=")) return Response.json({ total_count: url.includes("in_progress") ? active : 0 });
    if (url.endsWith("/dispatches")) return new Response(null, { status: 204 });
    return new Response("unexpected", { status: 500 });
  };
  return calls;
}

test("tick dispatches a due slot once no run is active", async () => {
  const calls = fakeGitHub();
  assert.equal(await tick({ GITHUB_TOKEN: "test" }, new Date("2026-07-15T05:20:00Z")), "dispatched: 2026-07-15 slot 8");
  assert.equal(calls.filter((call) => call.method === "POST").length, 1);
});

test("tick skips while a Collect run is active", async () => {
  const calls = fakeGitHub({ active: 1 });
  assert.match(await tick({ GITHUB_TOKEN: "test" }, new Date("2026-07-15T05:20:00Z")), /^skip: Collect already active/);
  assert.equal(calls.filter((call) => call.method === "POST").length, 0);
});
