import test from "node:test";
import assert from "node:assert/strict";
import { createPrivateKey, generateKeyPairSync } from "node:crypto";

import {
  createGitHubAppJwt,
  dispatchAfterDurableQueue,
  GitHubAppDispatcher,
} from "../../supabase/functions/download-mcp/github_app.ts";

const encoder = new TextEncoder();

function decodeJson(segment) {
  return JSON.parse(Buffer.from(segment, "base64url").toString("utf8"));
}

async function verifyJwtSignature(jwt, publicKey) {
  const [header, payload, signature] = jwt.split(".");
  return crypto.subtle.verify(
    { name: "RSASSA-PKCS1-v1_5" },
    publicKey,
    Buffer.from(signature, "base64url"),
    encoder.encode(`${header}.${payload}`),
  );
}

const fixtureKey = generateKeyPairSync("rsa", { modulusLength: 2048 }).privateKey
  .export({ type: "pkcs8", format: "pem" }).toString();
const START = 1_800_000_000_000;
const TOKEN_URL = "https://api.github.com/app/installations/67890/access_tokens";
const DISPATCH_URL = "https://api.github.com/repos/QuJindai/automotive-smart-manufacturing-standards-archive/actions/workflows/download-executor.yml/dispatches";

function makeDispatcher(fetch, options = {}) {
  return new GitHubAppDispatcher({
    environment: {
      DOWNLOAD_GITHUB_APP_ID: "12345",
      DOWNLOAD_GITHUB_APP_INSTALLATION_ID: "67890",
      DOWNLOAD_GITHUB_APP_PRIVATE_KEY: fixtureKey,
    },
    owner: "QuJindai",
    repository: "automotive-smart-manufacturing-standards-archive",
    workflow: "download-executor.yml",
    ref: "main",
    fetch,
    now: options.now ?? (() => START),
    webcrypto: crypto,
    requestTimeoutMs: options.requestTimeoutMs ?? 50,
  });
}

test("creates a verifiable RS256 app JWT from PKCS#8 and PKCS#1 PEM keys", async () => {
  const { privateKey, publicKey: nodePublicKey } = generateKeyPairSync("rsa", {
    modulusLength: 2048,
  });
  const pkcs8Pem = privateKey.export({ type: "pkcs8", format: "pem" }).toString();
  const pkcs1Pem = createPrivateKey(pkcs8Pem).export({ type: "pkcs1", format: "pem" }).toString();
  const publicKey = await crypto.subtle.importKey(
    "spki",
    nodePublicKey.export({ type: "spki", format: "der" }),
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["verify"],
  );

  for (const privateKeyPem of [pkcs8Pem, pkcs1Pem]) {
    const jwt = await createGitHubAppJwt({
      appId: "12345",
      privateKeyPem,
      nowMs: 1_800_000_000_000,
    });
    const [encodedHeader, encodedPayload] = jwt.split(".");
    const header = decodeJson(encodedHeader);
    const payload = decodeJson(encodedPayload);

    assert.equal(header.alg, "RS256");
    assert.equal(payload.iss, "12345");
    assert.equal(payload.iat, 1_799_999_940);
    assert.equal(payload.exp, 1_800_000_540);
    assert.equal(await verifyJwtSignature(jwt, publicKey), true);
  }
});

test("exchanges an App JWT and dispatches the fixed workflow contract", async () => {
  const requests = [];
  const dispatcher = makeDispatcher(async (url, init) => {
    requests.push({ url: String(url), init });
    if (String(url) === TOKEN_URL) {
      assert.equal(init.method, "POST");
      assert.match(init.headers.authorization, /^Bearer eyJ/);
      assert.equal(init.headers.accept, "application/vnd.github+json");
      assert.equal(init.headers["x-github-api-version"], "2026-03-10");
      assert.ok(init.signal instanceof AbortSignal);
      return Response.json({ token: "installation-token", expires_at: "2030-01-15T08:00:00.000Z" }, { status: 201 });
    }
    assert.equal(String(url), DISPATCH_URL);
    assert.equal(init.method, "POST");
    assert.equal(init.headers.authorization, "Bearer installation-token");
    assert.equal(init.headers.accept, "application/vnd.github+json");
    assert.equal(init.headers["x-github-api-version"], "2026-03-10");
    assert.ok(init.signal instanceof AbortSignal);
    assert.equal(init.body, '{"ref":"main"}');
    return Response.json({ workflow_run_id: 42, run_url: "https://github.com/example/run/42" }, { status: 200 });
  });

  assert.deepEqual(await dispatcher.dispatch(), {
    mechanism: "github_app",
    status: "DISPATCHED",
    http_status: 200,
    workflow_run_id: 42,
    run_url: "https://github.com/example/run/42",
  });
  assert.equal(requests.length, 2);
});

test("reuses a token with more than sixty seconds remaining and exchanges an expired token", async () => {
  let nowMs = START;
  let exchanges = 0;
  const dispatcher = makeDispatcher(async (url, init) => {
    if (String(url) === TOKEN_URL) {
      exchanges += 1;
      return Response.json({
        token: `installation-token-${exchanges}`,
        expires_at: new Date(nowMs + 61_000).toISOString(),
      }, { status: 201 });
    }
    assert.match(init.headers.authorization, /^Bearer installation-token-[12]$/);
    return new Response(null, { status: 204 });
  }, { now: () => nowMs });

  assert.equal((await dispatcher.dispatch()).http_status, 204);
  await dispatcher.dispatch();
  assert.equal(exchanges, 1);

  nowMs += 62_000;
  await dispatcher.dispatch();
  assert.equal(exchanges, 2);
});

test("retries workflow dispatch once with a fresh token after cached-token 401 or 403", async (t) => {
  for (const rejectedStatus of [401, 403]) {
    await t.test(String(rejectedStatus), async () => {
      const seenTokens = [];
      let exchanges = 0;
      let firstDispatch = true;
      const dispatcher = makeDispatcher(async (url, init) => {
        if (String(url) === TOKEN_URL) {
          exchanges += 1;
          return Response.json({
            token: exchanges === 1 ? "cached-token" : "fresh-token",
            expires_at: "2030-01-15T08:00:00.000Z",
          }, { status: 201 });
        }
        const token = init.headers.authorization;
        seenTokens.push(token);
        if (firstDispatch) {
          firstDispatch = false;
          return new Response(null, { status: 204 });
        }
        return token === "Bearer cached-token"
          ? new Response("expired", { status: rejectedStatus })
          : new Response(null, { status: 204 });
      });

      await dispatcher.dispatch();
      const evidence = await dispatcher.dispatch();

      assert.equal(exchanges, 2);
      assert.deepEqual(seenTokens, ["Bearer cached-token", "Bearer cached-token", "Bearer fresh-token"]);
      assert.equal(evidence.status, "DISPATCHED");
    });
  }
});

test("treats an unexpected successful workflow status as sanitized fallback", async () => {
  const responseSecret = "github-response-secret";
  const dispatcher = makeDispatcher(async (url) => {
    if (String(url) === TOKEN_URL) {
      return Response.json({
        token: "installation-token",
        expires_at: "2030-01-15T08:00:00.000Z",
      }, { status: 201 });
    }
    return new Response(responseSecret, { status: 202 });
  });

  const evidence = await dispatcher.dispatch();

  assert.deepEqual(evidence, {
    mechanism: "github_app",
    status: "FALLBACK_POLLING",
    error_code: "GITHUB_APP_WORKFLOW_DISPATCH_FAILED",
    http_status: 202,
    retry_after_seconds: 300,
  });
  assert.equal(JSON.stringify(evidence).includes(responseSecret), false);
});

test("bounds a stalled installation-token exchange with an abort signal", async () => {
  let sawSignal = false;
  const dispatcher = makeDispatcher(async (_url, init) => {
    sawSignal = init.signal instanceof AbortSignal;
    if (!sawSignal) return new Response(null, { status: 599 });
    return await new Promise((_resolve, reject) => {
      init.signal.addEventListener("abort", () => reject(init.signal.reason), { once: true });
    });
  }, { requestTimeoutMs: 10 });

  const startedAt = Date.now();
  const evidence = await dispatcher.dispatch();

  assert.equal(sawSignal, true);
  assert.equal(evidence.status, "FALLBACK_POLLING");
  assert.ok(Date.now() - startedAt < 1_000);
});

test("bounds a stalled workflow dispatch with an abort signal", async () => {
  let sawDispatchSignal = false;
  const dispatcher = makeDispatcher(async (url, init) => {
    if (String(url) === TOKEN_URL) {
      return Response.json({
        token: "installation-token",
        expires_at: "2030-01-15T08:00:00.000Z",
      }, { status: 201 });
    }
    sawDispatchSignal = init.signal instanceof AbortSignal;
    if (!sawDispatchSignal) return new Response("response-secret", { status: 500 });
    return await new Promise((_resolve, reject) => {
      init.signal.addEventListener("abort", () => reject(init.signal.reason), { once: true });
    });
  }, { requestTimeoutMs: 10 });

  const startedAt = Date.now();
  const evidence = await dispatcher.dispatch();

  assert.equal(sawDispatchSignal, true);
  assert.equal(evidence.status, "FALLBACK_POLLING");
  assert.ok(Date.now() - startedAt < 1_000);
  assert.equal(JSON.stringify(evidence).includes("response-secret"), false);
});

test("reports safe GitHub App failure metadata without exposing secret material", async () => {
  let appJwt = "";
  const dispatcher = makeDispatcher(async (_url, init) => {
    appJwt = init.headers.authorization.replace("Bearer ", "");
    return new Response(`private=${fixtureKey}; jwt=${appJwt}; body-secret`, { status: 500 });
  });

  const evidence = await dispatcher.dispatch();
  assert.deepEqual(evidence, {
    mechanism: "github_app",
    status: "FALLBACK_POLLING",
    error_code: "GITHUB_APP_TOKEN_EXCHANGE_FAILED",
    http_status: 500,
    retry_after_seconds: 300,
  });
  const text = JSON.stringify(evidence);
  assert.equal(text.includes(fixtureKey), false);
  assert.equal(text.includes(appJwt), false);
  assert.equal(text.includes("body-secret"), false);
});

async function exerciseQueueTransition({ label, previousStatus, stateKind, status = "QUEUED" }) {
  const calls = [];
  let durable = false;
  const result = await dispatchAfterDurableQueue({
    job: { download_id: `download-${label}`, status },
    previousStatus,
    stateKind,
    persist: async (job) => {
      calls.push("persist");
      durable = true;
      return { ...job, durable: true };
    },
    dispatcher: {
      async dispatch() {
        assert.equal(durable, true, `${label} dispatched before persistence`);
        calls.push("dispatch");
        return { mechanism: "github_app", status: "DISPATCHED", http_status: 204 };
      },
    },
  });
  return { calls, result };
}

test("production durable orchestration dispatches direct creation, first resolution, and retry only after persistence", async () => {
  const transitions = [
    ["direct-creation", null],
    ["first-resolution", "RESOLVING"],
    ["retry", "FAILED"],
  ];
  for (const [label, previousStatus] of transitions) {
    const { calls, result } = await exerciseQueueTransition({
      label,
      previousStatus,
      stateKind: "download_job",
    });
    assert.deepEqual(calls, ["persist", "dispatch"], label);
    assert.equal(result.durable, true);
    assert.equal(result.executor_dispatch.status, "DISPATCHED");
  }
});

test("production idempotent queued resolution persists without duplicate dispatch", async () => {
  const { calls, result } = await exerciseQueueTransition({
    label: "idempotent-resolution",
    previousStatus: "QUEUED",
    stateKind: "download_job",
  });

  assert.deepEqual(calls, ["persist"]);
  assert.equal(result.durable, true);
  assert.equal("executor_dispatch" in result, false);
});

test("staging durable orchestration never calls the production dispatcher", async () => {
  const transitions = [
    ["direct-creation", null, true],
    ["first-resolution", "RESOLVING", true],
    ["idempotent-resolution", "QUEUED", false],
    ["retry", "FAILED", true],
  ];
  for (const [label, previousStatus, enteredQueue] of transitions) {
    const { calls, result } = await exerciseQueueTransition({
      label,
      previousStatus,
      stateKind: "download_job_staging",
    });
    assert.deepEqual(calls, ["persist"], label);
    assert.equal(result.durable, true);
    if (enteredQueue) {
      assert.deepEqual(result.executor_dispatch, {
        mechanism: "github_app",
        status: "FALLBACK_POLLING",
        error_code: "GITHUB_APP_DISPATCH_DISABLED_FOR_STAGING",
        retry_after_seconds: 300,
      });
    } else {
      assert.equal("executor_dispatch" in result, false);
    }
  }
});

test("production dispatch failure leaves the durably queued job in fallback polling", async () => {
  const calls = [];
  const queued = await dispatchAfterDurableQueue({
    job: { download_id: "download-fallback", status: "QUEUED" },
    previousStatus: null,
    stateKind: "download_job",
    persist: async (job) => {
      calls.push("persist");
      return { ...job, durable: true };
    },
    dispatcher: {
      async dispatch() {
        calls.push("dispatch");
        throw new Error("network unavailable with response-secret");
      },
    },
  });

  assert.deepEqual(calls, ["persist", "dispatch"]);
  assert.equal(queued.status, "QUEUED");
  assert.equal(queued.durable, true);
  assert.deepEqual(queued.executor_dispatch, {
    mechanism: "github_app",
    status: "FALLBACK_POLLING",
    error_code: "GITHUB_APP_DISPATCH_FAILED",
    retry_after_seconds: 300,
  });
  assert.equal(JSON.stringify(queued).includes("response-secret"), false);
});

test("durable orchestration does not dispatch a persisted non-queued state", async () => {
  const { calls, result } = await exerciseQueueTransition({
    label: "resolving",
    previousStatus: null,
    stateKind: "download_job",
    status: "RESOLVING",
  });

  assert.deepEqual(calls, ["persist"]);
  assert.equal(result.status, "RESOLVING");
  assert.equal("executor_dispatch" in result, false);
});
