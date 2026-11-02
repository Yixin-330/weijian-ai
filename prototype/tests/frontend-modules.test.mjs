import assert from "node:assert/strict";
import test from "node:test";
import { readFile, readdir } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { stripTypeScriptTypes } from "node:module";
import { SourceTextModule, createContext } from "node:vm";
import { webcrypto } from "node:crypto";

// Execute the actual TypeScript modules without bundling or installing a test framework.
const root = fileURLToPath(new URL("../src/", import.meta.url));
async function runtime(fetch, env = {}) {
  const context = createContext({ fetch, Response, Headers, AbortController, DOMException,
    crypto: webcrypto, setTimeout, clearTimeout, console,
    window: { setTimeout, location: { hostname: "localhost" } } });
  const cache = new Map();
  async function load(file) {
    if (cache.has(file)) return cache.get(file);
    const source = stripTypeScriptTypes(await readFile(file, "utf8"), { mode: "transform" });
    const module = new SourceTextModule(source, { context, identifier: file,
      initializeImportMeta(meta) { meta.env = env; } });
    cache.set(file, module);
    await module.link((specifier, parent) => load(resolve(dirname(parent.identifier), `${specifier}.ts`)));
    return module;
  }
  return async (path) => {
    const module = await load(resolve(root, path));
    if (module.status !== "evaluated") await module.evaluate();
    return module.namespace;
  };
}
const json = (value, status = 200) => Response.json(value, { status });
const complete = { job_id: "job-1", status: "completed", tick: { id: "tick-1", decision_reason: "授权议题" } };
const queued = { job_id: "job-1", status: "queued" };

test("request errors retain status and do not retry mutations", async () => {
  let calls = 0;
  const load = await runtime(async () => { calls++; return json({ detail: "版本冲突" }, 409); });
  const { requestJson, ApiError } = await load("shared/api/client.ts");
  await assert.rejects(requestJson("/changes", { method: "POST" }), (error) => error instanceof ApiError && error.status === 409 && error.message === "版本冲突");
  assert.equal(calls, 1);
});

test("validation detail arrays become readable fallback messages", async () => {
  const load = await runtime(async () => json({ detail: [{ msg: "invalid" }] }, 422));
  const { requestJson } = await load("shared/api/client.ts");
  await assert.rejects(requestJson("/test", undefined, "保存失败"), /保存失败（422）/);
});

test("transport forwards cancellation and uses configured backend", async () => {
  const controller = new AbortController();
  const load = await runtime(async (url, options) => {
    assert.equal(url, "https://example.test/api/v1/test");
    assert.equal(options.signal, controller.signal); return json({ ok: true });
  }, { VITE_API_BASE_URL: "https://example.test/" });
  const { requestJson } = await load("shared/api/client.ts");
  assert.equal((await requestJson("/test", { signal: controller.signal })).ok, true);
});

test("queued ticks poll reads only and keep the supplied idempotency key", async () => {
  const calls = [];
  const load = await runtime(async (url, options) => {
    calls.push({ url, options });
    return json(calls.length === 1 ? queued : complete);
  });
  const { advanceWorld } = await load("features/exploration/api.ts");
  const result = await advanceWorld("u1", { idempotencyKey: "same-intent" });
  assert.equal(result.tick.id, "tick-1");
  assert.equal(calls.filter((c) => c.options?.method === "POST").length, 1);
  assert.equal(calls[0].options.headers["Idempotency-Key"], "same-intent");
  assert.match(calls[1].url, /tick-jobs\/job-1$/);
});

test("completed tick does not poll", async () => {
  const load = await runtime(async () => { throw Error("unexpected fetch"); });
  const { waitForTick } = await load("features/exploration/api.ts");
  assert.equal((await waitForTick(complete)).tick.id, "tick-1");
});

for (const status of ["failed", "not_found"]) {
  test(`${status} is not treated as successful exploration`, async () => {
    const load = await runtime(async () => { throw Error("unexpected fetch"); });
    const { waitForTick } = await load("features/exploration/api.ts");
    await assert.rejects(waitForTick({ ...queued, status, error: "任务不可用" }), /任务不可用/);
  });
}

test("completed task must contain a tick reference", async () => {
  const load = await runtime(async () => json(complete));
  const { waitForTick } = await load("features/exploration/api.ts");
  await assert.rejects(waitForTick({ job_id: "j", status: "completed" }), /没有返回可读取/);
});

test("poll budget is bounded and timeout never resubmits", async () => {
  let calls = 0;
  const load = await runtime(async () => { calls++; return json(queued); });
  const { waitForTick } = await load("features/exploration/api.ts");
  await assert.rejects(waitForTick(queued, { maxAttempts: 2, intervalMs: 0 }), /不会重复执行/);
  assert.equal(calls, 2);
});

test("aborted polling exits before another read", async () => {
  let calls = 0;
  const load = await runtime(async () => { calls++; return json(queued); });
  const { waitForTick } = await load("features/exploration/api.ts");
  const controller = new AbortController(); controller.abort();
  await assert.rejects(waitForTick(queued, { signal: controller.signal }), { name: "AbortError" });
  assert.equal(calls, 0);
});

test("poll timer is cancellable while waiting", async () => {
  const load = await runtime(async () => { throw Error("unexpected fetch"); });
  const { waitForTick } = await load("features/exploration/api.ts");
  const controller = new AbortController();
  const pending = waitForTick(queued, { signal: controller.signal, intervalMs: 10_000 });
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
});

test("no encounter is a normal result rather than demo fallback", async () => {
  let mutations = 0;
  const world = { user: { id: "real-user" }, lifeform: { id: "real-lifeform" }, latest_tick: { matching_status: "waiting" } };
  const load = await runtime(async (url, options) => {
    if (url.endsWith("/exploration")) return json({ last_encounter_id: null });
    if (url.endsWith("/next-action")) { mutations++; return json(complete); }
    if (url.endsWith("/encounter")) return json({ detail: "not found" }, 404);
    if (url.endsWith("/world")) return json(world);
    throw Error(`unexpected ${url}`);
  });
  const { advanceToEncounter } = await load("features/encounters/api.ts");
  const result = await advanceToEncounter(world);
  assert.equal(result.encounter, null); assert.equal(result.companion, null);
  assert.equal(result.world.user.id, "real-user"); assert.equal(mutations, 1);
});

test("existing encounter is loaded without another tick", async () => {
  const world = { user: { id: "u1" }, lifeform: { id: "a" }, latest_tick: { id: "t1" } };
  const encounter = { id: "e1", relationship_id: "r1", lifeform_ids: ["a", "b"] };
  const load = await runtime(async (url, options) => {
    assert.notEqual(options?.method, "POST");
    if (url.endsWith("/encounter")) return json(encounter);
    if (url.endsWith("/relationships/r1")) return json({ id: "r1" });
    if (url.endsWith("/world")) return json(world);
    if (url.endsWith("/lifeforms/b")) return json({ id: "b" });
    throw Error(`unexpected ${url}`);
  });
  const { advanceToEncounter } = await load("features/encounters/api.ts");
  assert.equal((await advanceToEncounter(world)).companion.id, "b");
});

test("real onboarding failures never silently create demo identities", async () => {
  const load = await runtime(async () => json({ detail: "服务不可用" }, 503));
  const { createWorldFromOnboarding } = await load("features/onboarding/api.ts");
  await assert.rejects(createWorldFromOnboarding({ topics: [], currentQuestion: "test" }, "key"), /服务不可用/);
});

test("standalone calibration changes future exploration without network calls", async () => {
  const load = await runtime(async () => { throw Error("demo must not fetch"); });
  const { calibrateStandalone } = await load("demo/calibration.ts");
  const world = { user: { id: "demo" }, lifeform: { current_island_id: "stability" }, memories: [{ id: "m", status: "candidate" }] };
  const result = await calibrateStandalone(world, "opposing", true, world.memories[0]);
  assert.equal(result.world.lifeform.current_island_id, "intimacy");
  assert.equal(result.world.memories[0].allow_social_recommendation, false);
  assert.equal(world.memories[0].status, "candidate");
});

test("calibration partial success does not masquerade as an unsaved correction", async () => {
  const load = await runtime(async (url) => url.endsWith("/calibrations")
    ? json({ ok: true }) : json({ detail: "队列不可用" }, 503));
  const { calibrateAndAdvance } = await load("features/understandings/api.ts");
  await assert.rejects(calibrateAndAdvance({ user: { id: "u" }, memories: [{ id: "m", status: "candidate" }] }, "like-me", false), /校准已保存/);
});

test("app modules have one HTTP transport and no feature-to-shell imports", async () => {
  async function files(dir) {
    const found = [];
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      if (entry.name === "mobile") continue;
      const full = resolve(dir, entry.name);
      if (entry.isDirectory()) found.push(...await files(full));
      else if (/\.tsx?$/.test(entry.name)) found.push(full);
    }
    return found;
  }
  for (const file of await files(root)) {
    const source = await readFile(file, "utf8");
    if (!file.endsWith("shared\\api\\client.ts") && !file.endsWith("shared/api/client.ts")) {
      assert.doesNotMatch(source, /\bfetch\(/, file);
    }
    if (file.includes("features")) assert.doesNotMatch(source, /from ["'][^"']*\/app\//, file);
  }
});
