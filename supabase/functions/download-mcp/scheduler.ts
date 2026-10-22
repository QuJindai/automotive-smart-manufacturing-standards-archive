import { isClaimEligible } from "./core.ts";
import type { ExecutorDispatchEvidence } from "./github_app.ts";

export type QueueRow = {
  record_id: string;
  payload: Record<string, any>;
  revision: number;
  created_at: string;
};
export type QueueCursor = { created_at: string; record_id: string };
type ReadPage = (cursor: QueueCursor | null, limit: number) => Promise<QueueRow[]>;
type SchedulerState = Record<string, unknown>;
type SchedulerStore = {
  read(): Promise<{ payload: SchedulerState; revision: number }>;
  compareAndSwap(revision: number, payload: SchedulerState): Promise<boolean>;
};
type WakeInput = {
  now: () => number;
  readPage: ReadPage;
  store: SchedulerStore;
  dispatcher: { dispatch(): Promise<ExecutorDispatchEvidence> };
};
type WakeResult = {
  status: "empty" | "cooling" | "active" | "dispatched" | "fallback";
  executor_dispatch?: ExecutorDispatchEvidence;
};

const COOLDOWN_MS = 5 * 60_000;
const QUEUED_GRACE_MS = 60_000;
const ERROR_CODES = new Set([
  "GITHUB_APP_CONFIGURATION_INVALID",
  "GITHUB_APP_TOKEN_EXCHANGE_FAILED",
  "GITHUB_APP_WORKFLOW_DISPATCH_FAILED",
  "GITHUB_APP_DISPATCH_FAILED",
]);

export async function authorizeSchedulerToken(header: unknown, tokenSha256: unknown): Promise<boolean> {
  if (typeof tokenSha256 !== "string" || !/^[a-f0-9]{64}$/.test(tokenSha256)) return false;
  if (typeof header !== "string") return false;
  const match = /^Bearer ([^\s]{1,512})$/i.exec(header);
  if (!match) return false;
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(match[1])));
  let difference = 0;
  for (let index = 0; index < digest.length; index += 1) {
    difference |= digest[index] ^ Number.parseInt(tokenSha256.slice(index * 2, index * 2 + 2), 16);
  }
  return difference === 0;
}

// Both claim and watchdog scans must reach work behind old, ineligible records.
export async function* readQueueRows(readPage: ReadPage): AsyncGenerator<QueueRow> {
  const pageSize = 20;
  let cursor: QueueCursor | null = null;
  for (;;) {
    const rows = await readPage(cursor, pageSize);
    if (!Array.isArray(rows)) throw new Error("invalid queue page");
    if (rows.length === 0) return;
    const last = rows[rows.length - 1];
    if (typeof last?.record_id !== "string" || !last.record_id) throw new Error("invalid queue cursor");
    const next = { created_at: last.created_at, record_id: last.record_id };
    const nextTime = queueTimeKey(next.created_at);
    if (cursor) {
      const previousTime = queueTimeKey(cursor.created_at);
      if (nextTime < previousTime || (nextTime === previousTime && next.record_id <= cursor.record_id)) {
        throw new Error("nonadvancing queue cursor");
      }
    }
    for (const row of rows) yield row;
    if (rows.length < pageSize) return;
    cursor = next;
  }
}

function queueTimeKey(value: unknown): bigint {
  const match = typeof value === "string"
    ? /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(value)
    : null;
  const seconds = match ? Date.parse(`${match[1]}${match[3]}`) : NaN;
  if (!match || !Number.isFinite(seconds)) throw new Error("invalid queue cursor");
  // Keep PostgreSQL microseconds: Date alone would round the page boundary.
  return BigInt(seconds) * 1000n + BigInt((match[2] ?? "").padEnd(6, "0"));
}

function dispatchEvidence(value: unknown): ExecutorDispatchEvidence {
  const item = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const httpStatus = Number(item.http_status);
  if (item.status === "DISPATCHED" && (httpStatus === 200 || httpStatus === 204)) {
    const runId = Number(item.workflow_run_id);
    return {
      mechanism: "github_app", status: "DISPATCHED", http_status: httpStatus,
      ...(Number.isSafeInteger(runId) && runId > 0 ? { workflow_run_id: runId } : {}),
    };
  }
  return {
    mechanism: "github_app", status: "FALLBACK_POLLING",
    error_code: typeof item.error_code === "string" && ERROR_CODES.has(item.error_code)
      ? item.error_code : "GITHUB_APP_DISPATCH_FAILED",
    ...(Number.isInteger(httpStatus) && httpStatus >= 100 && httpStatus <= 599 ? { http_status: httpStatus } : {}),
    retry_after_seconds: 300,
  };
}

function cleanState(value: SchedulerState): SchedulerState {
  const output: SchedulerState = {};
  for (const field of ["last_check_at", "last_attempt_at", "next_allowed_at"]) {
    const time = typeof value[field] === "string" ? Date.parse(value[field] as string) : NaN;
    if (Number.isFinite(time)) output[field] = new Date(time).toISOString();
  }
  if (["empty", "active", "dispatching", "dispatched", "fallback"].includes(String(value.last_outcome))) {
    output.last_outcome = value.last_outcome;
  }
  if (value.last_dispatch && typeof value.last_dispatch === "object") {
    output.last_dispatch = dispatchEvidence(value.last_dispatch);
  }
  return output;
}

export async function wakeDownloadExecutor(input: WakeInput): Promise<WakeResult> {
  const nowMs = input.now();
  const now = new Date(nowMs).toISOString();
  const row = await input.store.read();
  const state = cleanState(row.payload);
  if (Date.parse(String(state.next_allowed_at ?? "")) > nowMs) return { status: "cooling" };

  let eligible = false;
  let active = false;
  for await (const candidate of readQueueRows(input.readPage)) {
    const job = candidate?.payload;
    if (!job) continue;
    const leaseEnd = Date.parse(String(job.executor?.claim_expires_at ?? ""));
    if (job.status === "FETCHING" && job.executor?.status === "CLAIMED" &&
      Number.isFinite(leaseEnd) && leaseEnd > nowMs) {
      active = true;
      break;
    }
    if (!isClaimEligible(job, nowMs)) continue;
    if (job.status === "QUEUED") {
      const queuedAt = Date.parse(String(job.updated_at ?? job.created_at ?? candidate.created_at ?? ""));
      if (!Number.isFinite(queuedAt) || nowMs - queuedAt < QUEUED_GRACE_MS) continue;
    }
    eligible = true;
  }

  if (active || !eligible) {
    const status = active ? "active" : "empty";
    await input.store.compareAndSwap(row.revision, { ...state, last_check_at: now, last_outcome: status });
    return { status };
  }

  const reserved = {
    ...state,
    last_check_at: now,
    last_attempt_at: now,
    next_allowed_at: new Date(nowMs + COOLDOWN_MS).toISOString(),
    last_outcome: "dispatching",
  };
  if (!(await input.store.compareAndSwap(row.revision, reserved))) return { status: "cooling" };

  let evidence: ExecutorDispatchEvidence;
  try {
    evidence = dispatchEvidence(await input.dispatcher.dispatch());
  } catch {
    evidence = dispatchEvidence(null);
  }
  const status = evidence.status === "DISPATCHED" ? "dispatched" : "fallback";
  // An expired attempt cannot overwrite a newer reservation. Requests within the
  // cooldown do not write this row, leaving the result's revision available.
  await input.store.compareAndSwap(row.revision + 1, {
    ...reserved, last_outcome: status, last_dispatch: evidence,
  });
  return { status, executor_dispatch: evidence };
}

export async function handleSchedulerWake(
  req: Request,
  input: WakeInput & { stateKind: string; readTokenHash: () => Promise<unknown> },
): Promise<Response> {
  const reply = (body: unknown, status = 200) => Response.json(body, {
    status,
    headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" },
  });
  if (input.stateKind !== "download_job") return reply({ error: "not_found" }, 404);
  if (req.method !== "POST") return reply({ error: "method_not_allowed" }, 405);
  try {
    const authorization = req.headers.get("authorization");
    if (!authorization || !(await authorizeSchedulerToken(authorization, await input.readTokenHash()))) {
      return reply({ error: "unauthorized" }, 401);
    }
    const result = await wakeDownloadExecutor(input);
    return reply(result, result.status === "fallback" ? 503 : 200);
  } catch {
    return reply({ status: "fallback", error_code: "SCHEDULER_UNAVAILABLE" }, 503);
  }
}
