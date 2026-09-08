import { createClient, type Session } from "@supabase/supabase-js";
import type { NextApiRequest, NextApiResponse } from "next";
import { ApiError, cookie, name, sign } from "./security";
export function authClient() {
  const url = process.env.SUPABASE_URL,
    key = process.env.SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key)
    throw new ApiError(503, "Account services are not configured yet.");
  return createClient(url, key, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
      detectSessionInUrl: false,
    },
  });
}
export function setSession(
  res: NextApiResponse,
  session: Pick<Session, "access_token" | "refresh_token">,
) {
  cookie(res, "access", session.access_token);
  cookie(res, "refresh", session.refresh_token);
}
export function clearSession(res: NextApiResponse) {
  for (const key of ["access", "refresh", "recovery"]) cookie(res, key, "", 0);
}
export async function session(
  req: NextApiRequest,
  res: NextApiResponse,
  required = true,
) {
  // Read the cookies before building a client. A signed-out visitor has nothing
  // to validate, and constructing the client first made the sign-in page itself
  // fail whenever account services were unreachable — locking people out of the
  // one screen that could have recovered the situation.
  let token = req.cookies[name("access")];
  const refresh = req.cookies[name("refresh")];
  if (!token && !refresh) {
    if (required) throw new ApiError(401, "Sign in to continue.");
    return null;
  }
  const client = authClient();
  let check = token ? await client.auth.getUser(token) : null;
  if (check?.error || !check?.data.user) {
    if (!refresh) {
      clearSession(res);
      if (required) throw new ApiError(401, "Sign in again.");
      return null;
    }
    const renewed = await client.auth.refreshSession({
      refresh_token: refresh,
    });
    if (renewed.error || !renewed.data.session) {
      clearSession(res);
      if (required)
        throw new ApiError(401, "Your session ended. Sign in again.");
      return null;
    }
    token = renewed.data.session.access_token;
    setSession(res, renewed.data.session);
    check = await client.auth.getUser(token);
  }
  if (!check?.data.user?.email_confirmed_at)
    throw new ApiError(403, "Confirm your email before continuing.");
  return { user: check.data.user, token: token! };
}
export async function rateLimit(req: NextApiRequest, address?: string) {
  const url = process.env.SUPABASE_URL,
    key = process.env.SUPABASE_SECRET_KEY;
  if (!url || !key)
    throw new ApiError(503, "Account services are not configured yet.");
  // Vercel overwrites this header; never use a client-supplied forwarded chain.
  const ip = process.env.VERCEL
    ? String(req.headers["x-vercel-forwarded-for"] ?? "unknown")
    : (req.socket.remoteAddress ?? "local");
  const email =
    address ??
    (typeof req.body?.email === "string"
      ? req.body.email.trim().toLowerCase()
      : "");
  for (const [scope, keyValue] of [
    ["ip", ip],
    ...(email ? [["address", email]] : []),
  ]) {
    const r = await fetch(`${url}/rest/v1/rpc/auth_rate_limit`, {
      method: "POST",
      headers: { apikey: key, "Content-Type": "application/json" },
      body: JSON.stringify({ p_key: sign(keyValue), p_scope: scope }),
      signal: AbortSignal.timeout(10000),
    });
    if (!r.ok) throw new ApiError(503, "Please try again shortly.");
    if (!(await r.json()))
      throw new ApiError(
        429,
        "Too many attempts. Please wait before trying again.",
      );
  }
}
export async function captcha(token: unknown) {
  const key = process.env.TURNSTILE_SECRET_KEY;
  if (!key) {
    if (process.env.NODE_ENV === "production")
      throw new ApiError(503, "Bot protection is not configured.");
    return;
  }
  if (typeof token !== "string" || token.length > 3000)
    throw new ApiError(422, "Complete the security check.");
  const r = await fetch(
    "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    {
      method: "POST",
      body: new URLSearchParams({ secret: key, response: token }),
      signal: AbortSignal.timeout(10000),
    },
  );
  const data = await r.json();
  if (!data.success)
    throw new ApiError(422, "Complete the security check again.");
}

export async function reauthenticate(email: string, password: unknown) {
  if (typeof password !== "string" || !password || password.length > 128)
    throw new ApiError(422, "Enter your current password.");
  const client = authClient();
  const check = await client.auth.signInWithPassword({ email, password });
  if (check.error || !check.data.session)
    throw new ApiError(401, "The current password is incorrect.");
  // Verification creates a short-lived extra session; revoke it immediately.
  await client.auth.signOut({ scope: "local" });
}
