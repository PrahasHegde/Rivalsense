import test from "node:test";
import assert from "node:assert/strict";
import { createApi, ApiError } from "../src/lib/apiClient.js";
import { impact, safeLink, money } from "../src/lib/presentation.js";

const auth = { getSession: async () => ({ data: { session: { access_token: "test-only-token" } } }) };
test("API forwards Bearer token and JSON contract", async () => {
  let captured;
  const api = createApi({ auth, baseUrl: "https://backend.example/", fetchImpl: async (...args) => { captured = args; return { ok: true, json: async () => ({ answer: "test" }) }; } });
  assert.deepEqual(await api("/api/ai/ask", { method: "POST", body: { question: "Question?" } }), { answer: "test" });
  assert.equal(captured[0], "https://backend.example/api/ai/ask");
  assert.equal(captured[1].headers.Authorization, "Bearer test-only-token");
  assert.deepEqual(JSON.parse(captured[1].body), { question: "Question?" });
});
test("API refuses unauthenticated requests before fetch", async () => {
  let called = false;
  const api = createApi({ auth: { getSession: async () => ({ data: { session: null } }) }, fetchImpl: () => { called = true; } });
  await assert.rejects(api("/api/ai/history"), error => error.status === 401);
  assert.equal(called, false);
});
test("API refreshes expiring session", async () => {
  let token;
  const api = createApi({ auth: { getSession: async () => ({ data: { session: { expires_at: 1, access_token: "old" } } }), refreshSession: async () => ({ data: { session: { access_token: "fresh" } } }) }, fetchImpl: async (_url, options) => { token = options.headers.Authorization; return { ok: true, json: async () => ({}) }; } });
  await api("/api/ai/history"); assert.equal(token, "Bearer fresh");
});
test("API surfaces useful auth and provider errors", async () => {
  const api = createApi({ auth, fetchImpl: async () => ({ ok: false, status: 503, json: async () => ({ detail: "Provider unavailable" }) }) });
  await assert.rejects(api("/api/ai/ask"), error => error instanceof ApiError && error.message === "Provider unavailable");
});
test("API explains empty proxy errors without exposing raw response content", async () => {
  const api = createApi({ auth, fetchImpl: async () => new Response("", { status: 502, headers: { "Content-Type": "text/plain" } }) });
  await assert.rejects(api("/api/ai/ask"), error => error.status === 502 && error.message.includes("API service may be starting or restarting"));
});
test("API handles HTML errors and successful HTML fallback pages", async () => {
  for (const status of [404, 200]) {
    const api = createApi({ auth, fetchImpl: async () => new Response("<html>private diagnostics</html>", { status, headers: { "Content-Type": "text/html" } }) });
    await assert.rejects(api("/api/ai/ask"), error => error.status === status && !error.message.includes("private diagnostics") && (status === 200 ? error.message.includes("Vite proxy") : error.message.includes("HTTP 404")));
  }
});
test("source links reject executable or credential URLs", () => {
  assert.equal(safeLink("javascript:alert(1)"), null);
  assert.equal(safeLink("https://user:password@example.com"), null);
  assert.equal(safeLink("https://example.com/facts"), "https://example.com/facts");
});
test("simulator calculates explicit estimates and handles zero/missing input", () => {
  assert.deepEqual(impact("20", "12", "100"), { revenue: 2000, grossProfit: 800, margin: 40 });
  assert.equal(impact("", "12", "100"), null);
  assert.equal(impact("20", "12", "1.5"), null);
  assert.equal(impact("0", "12", "0").margin, null);
  assert.equal(money(null, "EUR"), "Unknown");
});
