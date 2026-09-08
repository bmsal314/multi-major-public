import test from "node:test";
import assert from "node:assert/strict";
import {
  csrf,
  protect,
  equal,
  cookie,
  name,
  sign,
  origin,
} from "../server/security.ts";
process.env.NODE_ENV = "production";
process.env.INTERNAL_API_SECRET = "synthetic-test-key-not-a-real-secret-0000";
process.env.APP_ORIGIN = "https://example.invalid";
function response() {
  const headers = new Map();
  return {
    getHeader: (k) => headers.get(k),
    setHeader: (k, v) => headers.set(k, v),
    headers,
  };
}
test("constant-time comparison handles Unicode without throwing", () => {
  assert.equal(equal("é", "aa"), false);
  assert.equal(equal("a", "b"), false);
  assert.equal(equal("a", "a"), true);
});
test("all session cookies use protected attributes", () => {
  const r = response();
  cookie(r, "access", "test");
  const value = r.headers.get("Set-Cookie")[0];
  for (const attr of [
    "__Host-mm-access=",
    "HttpOnly",
    "Secure",
    "SameSite=Lax",
    "Path=/",
  ])
    assert.ok(value.includes(attr));
  assert.ok(!value.includes("Domain="));
});
test("CSRF binds header, HttpOnly cookie, signature and exact origin", () => {
  const r = response();
  const token = csrf({ cookies: {} }, r);
  const request = {
    cookies: { [name("csrf")]: token },
    headers: { origin: origin(), "x-csrf-token": token },
  };
  assert.doesNotThrow(() => protect(request));
  for (const headers of [
    { origin: "https://evil.invalid", "x-csrf-token": token },
    { origin: origin() },
    { origin: origin(), "x-csrf-token": "forged" },
  ])
    assert.throws(() => protect({ ...request, headers }));
});
test("a matching but unsigned CSRF cookie is rejected", () => {
  assert.throws(() =>
    protect({
      cookies: { [name("csrf")]: "forged.signature" },
      headers: { origin: origin(), "x-csrf-token": "forged.signature" },
    }),
  );
});
test("production rejects an HTTP origin", () => {
  process.env.APP_ORIGIN = "http://example.invalid";
  assert.throws(origin);
  process.env.APP_ORIGIN = "https://example.invalid";
});
test("a fresh CSRF token is issued even with no prior cookie", () => {
  const r = response();
  const token = csrf({ cookies: {} }, r);
  const [random, signature] = token.split(".");
  assert.ok(random.length >= 32);
  assert.equal(sign(random), signature);
  assert.ok(String(r.headers.get("Set-Cookie")[0]).startsWith(name("csrf")));
});
