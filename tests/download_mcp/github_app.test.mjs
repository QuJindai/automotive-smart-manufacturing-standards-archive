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

function makeDispatcher(fetch, now = () => START) {
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
    now,
    webcrypto: crypto,
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
      return Response.json({ token: "installation-token", expires_at: "2030-01-15T08:00:00.000Z" }, { status: 201 });
    }
    assert.equal(String(url), DISPATCH_URL);
    assert.equal(init.method, "POST");
    assert.equal(init.headers.authorization, "Bearer installation-token");
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
  }, () => nowMs);

  assert.equal((await dispatcher.dispatch()).http_status, 204);
  await dispatcher.dispatch();
  assert.equal(exchanges, 1);

  nowMs += 62_000;
  await dispatcher.dispatch();
  assert.equal(exchanges, 2);
});

test("retries workflow dispatch once with a fresh token after a cached-token 401", async () => {
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
      ? new Response("expired", { status: 401 })
      : new Response(null, { status: 204 });
  });

  await dispatcher.dispatch();
  const evidence = await dispatcher.dispatch();

  assert.equal(exchanges, 2);
  assert.deepEqual(seenTokens, ["Bearer cached-token", "Bearer cached-token", "Bearer fresh-token"]);
  assert.equal(evidence.status, "DISPATCHED");
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

test("persists a queued job before dispatching and degrades thrown dispatch errors to polling", async () => {
  const calls = [];
  const original = { download_id: "download-1", status: "QUEUED" };
  const queued = await dispatchAfterDurableQueue(
    original,
    async (job) => {
      calls.push("persist");
      return { ...job, durable: true };
    },
    {
      async dispatch() {
        calls.push("dispatch");
        throw new Error("network unavailable");
      },
    },
  );

  assert.deepEqual(calls, ["persist", "dispatch"]);
  assert.equal(queued.status, "QUEUED");
  assert.equal(queued.durable, true);
  assert.deepEqual(queued.executor_dispatch, {
    mechanism: "github_app",
    status: "FALLBACK_POLLING",
    error_code: "GITHUB_APP_DISPATCH_FAILED",
    retry_after_seconds: 300,
  });
});

test("does not dispatch a job whose durable state is not queued", async () => {
  let dispatched = false;
  const result = await dispatchAfterDurableQueue(
    { download_id: "download-2", status: "QUEUED" },
    async (job) => ({ ...job, status: "RESOLVING" }),
    { async dispatch() { dispatched = true; throw new Error("must not run"); } },
  );

  assert.equal(dispatched, false);
  assert.equal(result.status, "RESOLVING");
  assert.equal("executor_dispatch" in result, false);
});
