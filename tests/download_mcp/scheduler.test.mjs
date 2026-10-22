import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  authorizeSchedulerToken,
  handleSchedulerWake,
  readQueueRows,
  wakeDownloadExecutor,
} from "../../supabase/functions/download-mcp/scheduler.ts";

const NOW = Date.parse("2026-10-23T03:00:00.000Z");
const TOKEN = "test-only-64-character-scheduler-token-not-a-deployment-credential";
const HASH = createHash("sha256").update(TOKEN).digest("hex");
const SUCCESS = { mechanism: "github_app", status: "DISPATCHED", http_status: 204 };

function row(id, status = "QUEUED", extras = {}) {
  return {
    record_id: id,
    created_at: "2026-10-23T02:58:00.000Z",
    revision: 1,
    payload: { download_id: id, status, ...extras },
  };
}

function fixture(rows = [], initial = {}) {
  let state = { revision: 1, payload: structuredClone(initial) };
  let dispatchCount = 0;
  let nowMs = NOW;
  const source = structuredClone(rows);
  const pages = [];
  const store = {
    async read() { return structuredClone(state); },
    async compareAndSwap(revision, payload) {
      if (revision !== state.revision) return false;
      state = { revision: revision + 1, payload: structuredClone(payload) };
      return true;
    },
  };
  const deps = {
    now: () => nowMs,
    store,
    async readPage(cursor, limit) {
      pages.push({ cursor: structuredClone(cursor), limit });
      const ordered = [...source].sort((left, right) => {
        const time = Date.parse(left.created_at) - Date.parse(right.created_at);
        return time || (left.record_id < right.record_id ? -1 : left.record_id > right.record_id ? 1 : 0);
      });
      const remaining = cursor ? ordered.filter((item) =>
        Date.parse(item.created_at) > Date.parse(cursor.created_at) ||
        (Date.parse(item.created_at) === Date.parse(cursor.created_at) && item.record_id > cursor.record_id)
      ) : ordered;
      return structuredClone(remaining.slice(0, limit));
    },
    dispatcher: {
      async dispatch() {
        dispatchCount += 1;
        assert.equal(state.payload.next_allowed_at, new Date(nowMs + 300_000).toISOString());
        return SUCCESS;
      },
    },
  };
  return {
    deps, pages,
    state: () => structuredClone(state),
    dispatchCount: () => dispatchCount,
    setNow: (value) => { nowMs = value; },
    source: () => structuredClone(source),
    removeRows: (ids) => {
      for (let index = source.length - 1; index >= 0; index -= 1) {
        if (ids.includes(source[index].record_id)) source.splice(index, 1);
      }
    },
  };
}

test("scheduler authentication accepts only the bearer matching its configured SHA-256", async () => {
  assert.equal(await authorizeSchedulerToken(`Bearer ${TOKEN}`, HASH), true);
  for (const header of [null, "", TOKEN, "Bearer ", "Bearer wrong", `Basic ${TOKEN}`]) {
    assert.equal(await authorizeSchedulerToken(header, HASH), false);
  }
  for (const hash of [undefined, "", "bad", "f".repeat(64)]) {
    assert.equal(await authorizeSchedulerToken(`Bearer ${TOKEN}`, hash), false);
  }
});

test("unauthorized wake cannot scan jobs, mutate state, or dispatch", async () => {
  const f = fixture([row("queued")]);
  const before = f.state();
  const response = await handleSchedulerWake(new Request("https://example.org/internal/wake", {
    method: "POST", headers: { authorization: "Bearer incorrect" },
  }), { ...f.deps, stateKind: "download_job", readTokenHash: async () => HASH });
  assert.equal(response.status, 401);
  assert.deepEqual(f.pages, []);
  assert.deepEqual(f.state(), before);
  assert.equal(f.dispatchCount(), 0);
});

test("staging and unsupported methods fail before reading configuration or queue", async () => {
  for (const [stateKind, method, expected] of [
    ["download_job_staging", "POST", 404], ["download_job", "GET", 405],
  ]) {
    const f = fixture([row("queued")]);
    const response = await handleSchedulerWake(new Request("https://example.org/internal/wake", {
      method, headers: { authorization: `Bearer ${TOKEN}` },
    }), {
      ...f.deps, stateKind,
      readTokenHash: async () => { assert.fail("must not read configuration"); },
    });
    assert.equal(response.status, expected);
    assert.equal(f.dispatchCount(), 0);
    assert.deepEqual(f.pages, []);
  }
});

test("empty queue persists a sanitized heartbeat without dispatching", async () => {
  const f = fixture([], { unexpected_secret: "never-retain-this" });
  assert.deepEqual(await wakeDownloadExecutor(f.deps), { status: "empty" });
  assert.equal(f.dispatchCount(), 0);
  assert.deepEqual(f.state().payload, { last_check_at: "2026-10-23T03:00:00.000Z", last_outcome: "empty" });
});

test("queued work waits sixty seconds before watchdog dispatch", async () => {
  const queued = row("fresh");
  queued.created_at = "2026-10-23T02:59:01.000Z";
  const f = fixture([queued]);
  assert.equal((await wakeDownloadExecutor(f.deps)).status, "empty");
  assert.equal(f.dispatchCount(), 0);
  f.setNow(NOW + 1_000);
  assert.equal((await wakeDownloadExecutor(f.deps)).status, "dispatched");
  assert.equal(f.dispatchCount(), 1);
  assert.deepEqual(f.source(), [queued]);
});

test("an old job newly resolved or retried gets sixty seconds from its queue transition", async () => {
  const queued = row("old-job-newly-queued", "QUEUED", {
    created_at: "2026-08-31T00:00:00.000Z",
    updated_at: "2026-10-23T02:59:01.000Z",
  });
  queued.created_at = "2026-08-31T00:00:00.000Z";
  const f = fixture([queued]);
  assert.equal((await wakeDownloadExecutor(f.deps)).status, "empty");
  assert.equal(f.dispatchCount(), 0);
  f.setNow(NOW + 1_000);
  assert.equal((await wakeDownloadExecutor(f.deps)).status, "dispatched");
  assert.equal(f.dispatchCount(), 1);
  assert.deepEqual(f.source(), [queued]);
});

test("queue paging reaches eligible work behind twenty legacy FETCHING rows", async () => {
  const rows = Array.from({ length: 20 }, (_, index) => row(`legacy-${index}`, "FETCHING"));
  rows.push(row("queued-after-twenty"));
  const f = fixture(rows);
  const seen = [];
  for await (const current of readQueueRows(f.deps.readPage)) seen.push(current.payload.download_id);
  assert.equal(seen.at(-1), "queued-after-twenty");
  assert.equal(seen.length, 21);
  assert.equal((await wakeDownloadExecutor(f.deps)).status, "dispatched");
  assert.equal(f.dispatchCount(), 1);
  assert.deepEqual(f.source(), rows);
});

test("queue paging still sees active or queued work when earlier rows disappear", async () => {
  for (const active of [true, false]) {
    const earlier = Array.from({ length: 20 }, (_, index) => row(`legacy-${index}`, "FETCHING"));
    const tail = active ? row("tail", "FETCHING", {
      executor: { status: "CLAIMED", claim_expires_at: "2026-10-23T03:10:00.000Z" },
    }) : row("tail");
    tail.created_at = "2026-10-23T02:58:01.000Z";
    const f = fixture([...earlier, tail]);
    const readPage = f.deps.readPage;
    let first = true;
    f.deps.readPage = async (...args) => {
      const page = await readPage(...args);
      if (first) {
        first = false;
        f.removeRows(page.map((item) => item.record_id));
      }
      return page;
    };
    assert.equal((await wakeDownloadExecutor(f.deps)).status, active ? "active" : "dispatched");
  }
});

test("queue paging fails closed on invalid or nonadvancing cursors", async () => {
  await assert.rejects(async () => {
    for await (const _row of readQueueRows(async () => [{ payload: { status: "QUEUED" }, revision: 1 }])) {}
  }, /invalid queue cursor/);
  const repeated = Array.from({ length: 20 }, (_, index) => row(`same-${String(index).padStart(2, "0")}`));
  let reads = 0;
  await assert.rejects(async () => {
    for await (const _row of readQueueRows(async () => {
      if (++reads > 2) throw new Error("cursor failed to stop repeated pages");
      return repeated;
    })) {}
  }, /nonadvancing queue cursor/);
  assert.equal(reads, 2);
});

test("queue cursor preserves PostgreSQL microseconds when the next record ID sorts earlier", async () => {
  const first = Array.from({ length: 20 }, (_, index) => ({
    ...row(`z-${String(index).padStart(2, "0")}`), created_at: "2026-10-23T02:58:00.123456+00:00",
  }));
  const next = { ...row("a-next-microsecond"), created_at: "2026-10-23T02:58:00.123457+00:00" };
  let calls = 0;
  const seen = [];
  for await (const item of readQueueRows(async (cursor, limit) => {
    assert.equal(limit, 20);
    calls += 1;
    if (calls === 1) {
      assert.equal(cursor, null);
      return first;
    }
    assert.deepEqual(cursor, { created_at: "2026-10-23T02:58:00.123456+00:00", record_id: "z-19" });
    return [next];
  })) seen.push(item.record_id);
  assert.equal(calls, 2);
  assert.equal(seen.length, 21);
  assert.equal(seen.at(-1), "a-next-microsecond");
});

test("an active lease on a later page prevents dispatch even with older queued work", async () => {
  const rows = Array.from({ length: 20 }, (_, index) => row(`queued-${index}`));
  const active = row("active", "FETCHING", {
    executor: { status: "CLAIMED", claim_expires_at: "2026-10-23T03:10:00.000Z" },
  });
  active.created_at = "2026-10-23T02:58:01.000Z";
  rows.push(active);
  const f = fixture(rows);
  assert.deepEqual(await wakeDownloadExecutor(f.deps), { status: "active" });
  assert.equal(f.dispatchCount(), 0);
  assert.deepEqual(f.source(), rows);
});

test("expired claimed work wakes but legacy and terminal jobs never revive", async () => {
  const inactive = [
    ...["COMPLETED", "FAILED", "PARTIAL", "RESOLVING", "AUTH_REQUIRED", "BLOCKED"].map((status) => row(status, status)),
    row("legacy", "FETCHING"),
    row("invalid-lease", "FETCHING", { executor: { status: "CLAIMED", claim_expires_at: "invalid" } }),
  ];
  const f = fixture(inactive);
  assert.equal((await wakeDownloadExecutor(f.deps)).status, "empty");
  assert.equal(f.dispatchCount(), 0);
  const expired = row("expired", "FETCHING", {
    executor: { status: "CLAIMED", claim_expires_at: "2026-10-23T03:00:00.000Z" },
  });
  const g = fixture([...inactive, expired]);
  assert.equal((await wakeDownloadExecutor(g.deps)).status, "dispatched");
  assert.deepEqual(g.source(), [...inactive, expired]);
});

test("concurrent wake requests reserve one durable five-minute dispatch window", async () => {
  const f = fixture([row("queued")]);
  const results = await Promise.all([wakeDownloadExecutor(f.deps), wakeDownloadExecutor(f.deps)]);
  assert.deepEqual(results.map((value) => value.status).sort(), ["cooling", "dispatched"]);
  assert.equal(f.dispatchCount(), 1);
  assert.equal(f.state().payload.last_attempt_at, "2026-10-23T03:00:00.000Z");
  assert.equal(f.state().payload.next_allowed_at, "2026-10-23T03:05:00.000Z");
  assert.deepEqual(f.state().payload.last_dispatch, SUCCESS);
  f.setNow(NOW + 299_999);
  assert.equal((await wakeDownloadExecutor(f.deps)).status, "cooling");
  assert.equal(f.dispatchCount(), 1);
  f.setNow(NOW + 300_000);
  assert.equal((await wakeDownloadExecutor(f.deps)).status, "dispatched");
  assert.equal(f.dispatchCount(), 2);
});

test("a failed dispatch records only safe evidence and retries on the next allowed tick", async () => {
  const f = fixture([row("queued")]);
  f.deps.dispatcher.dispatch = async () => { throw new Error(`secret=${TOKEN}`); };
  const failed = await wakeDownloadExecutor(f.deps);
  assert.deepEqual(failed, {
    status: "fallback",
    executor_dispatch: {
      mechanism: "github_app", status: "FALLBACK_POLLING",
      error_code: "GITHUB_APP_DISPATCH_FAILED", retry_after_seconds: 300,
    },
  });
  assert.equal(JSON.stringify(f.state()).includes(TOKEN), false);
  assert.equal((await wakeDownloadExecutor(f.deps)).status, "cooling");
  f.setNow(NOW + 300_000);
  f.deps.dispatcher.dispatch = async () => SUCCESS;
  assert.equal((await wakeDownloadExecutor(f.deps)).status, "dispatched");
});

test("cancelled requests leave their reservation intact and cannot cause immediate redispatch", async () => {
  const f = fixture([row("queued")]);
  let release;
  f.deps.dispatcher.dispatch = () => new Promise((resolve) => { release = resolve; });
  const pending = wakeDownloadExecutor(f.deps);
  while (!release) await new Promise((resolve) => setImmediate(resolve));
  assert.equal((await wakeDownloadExecutor(f.deps)).status, "cooling");
  release(SUCCESS);
  assert.equal((await pending).status, "dispatched");
});

test("dispatch evidence strips arbitrary fields, URLs and unknown error bodies", async () => {
  const f = fixture([row("queued")]);
  f.deps.dispatcher.dispatch = async () => ({
    mechanism: "github_app", status: "FALLBACK_POLLING", http_status: 503,
    error_code: `secret=${TOKEN}`, response_body: TOKEN, retry_after_seconds: 1,
  });
  const result = await wakeDownloadExecutor(f.deps);
  assert.deepEqual(result.executor_dispatch, {
    mechanism: "github_app", status: "FALLBACK_POLLING", http_status: 503,
    error_code: "GITHUB_APP_DISPATCH_FAILED", retry_after_seconds: 300,
  });
  assert.equal(JSON.stringify(f.state()).includes(TOKEN), false);
});

test("authenticated endpoint ignores body targets and returns safe fallback status", async () => {
  const f = fixture([row("queued")]);
  f.deps.dispatcher.dispatch = async () => { throw new Error(TOKEN); };
  const response = await handleSchedulerWake(new Request("https://example.org/internal/wake?kind=other", {
    method: "POST", headers: { authorization: `Bearer ${TOKEN}` },
    body: JSON.stringify({ repository: "other", stateKind: "other" }),
  }), { ...f.deps, stateKind: "download_job", readTokenHash: async () => HASH });
  assert.equal(response.status, 503);
  assert.equal((await response.json()).status, "fallback");
  assert.equal(f.state().payload.last_outcome, "fallback");
});

test("storage failures expose no secrets or false empty-queue result", async () => {
  const f = fixture([row("queued")]);
  f.deps.readPage = async () => { throw new Error(TOKEN); };
  const response = await handleSchedulerWake(new Request("https://example.org/internal/wake", {
    method: "POST", headers: { authorization: `Bearer ${TOKEN}` },
  }), { ...f.deps, stateKind: "download_job", readTokenHash: async () => HASH });
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { status: "fallback", error_code: "SCHEDULER_UNAVAILABLE" });
  assert.equal(f.dispatchCount(), 0);
});
