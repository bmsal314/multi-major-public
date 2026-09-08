import type { NextApiRequest, NextApiResponse } from "next";
import {
  authClient,
  captcha,
  clearSession,
  rateLimit,
  reauthenticate,
  session,
  setSession,
} from "../../../server/auth";
import {
  ApiError,
  cookie,
  csrf,
  equal,
  fail,
  name,
  noStore,
  origin,
  protect,
  sign,
} from "../../../server/security";
export const config = { api: { bodyParser: { sizeLimit: "12kb" } } };
export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse,
) {
  noStore(res);
  try {
    const action = String(req.query.action);
    if (action === "session" && req.method === "GET") {
      const token = csrf(req, res);
      // This response is what lets the browser make any request at all, because
      // it carries the CSRF token. If looking up the signed-in user fails, the
      // answer is "nobody is signed in", not an error that leaves the page
      // unable to submit the sign-in form either.
      let current: Awaited<ReturnType<typeof session>> = null;
      try {
        current = await session(req, res, false);
      } catch {
        current = null;
      }
      return res.json({
        csrf: token,
        user: current
          ? { id: current.user.id, email: current.user.email }
          : null,
        email_ready: process.env.AUTH_EMAIL_READY === "true",
      });
    }
    if (req.method !== "POST") throw new ApiError(405, "Method not allowed.");
    protect(req);
    if (
      ![
        "register",
        "login",
        "resend",
        "reset",
        "verify",
        "adopt",
        "password",
        "logout",
      ].includes(action)
    )
      throw new ApiError(404, "Not found.");
    await rateLimit(req);
    const body = req.body ?? {};
    const client = authClient();
    const email =
      typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
    const password = typeof body.password === "string" ? body.password : "";
    if (
      ["register", "login", "resend", "reset"].includes(action) &&
      (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 254)
    )
      throw new ApiError(422, "Enter a valid email address.");
    if (
      ["register", "password"].includes(action) &&
      (password.length < 12 || password.length > 128)
    )
      throw new ApiError(422, "Use a password between 12 and 128 characters.");
    if (["register", "resend", "reset"].includes(action)) {
      if (process.env.AUTH_EMAIL_READY !== "true")
        throw new ApiError(
          503,
          "Email delivery is not configured yet. Registration and recovery are unavailable.",
        );
      await captcha(body.captcha);
    }
    if (action === "register") {
      const result = await client.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: origin() + "/confirm" },
      });
      if (result.error)
        throw new ApiError(
          422,
          "Registration could not be completed. Check your details or try account recovery.",
        );
      if (result.data.session) {
        await client.auth.signOut();
        throw new ApiError(
          503,
          "Email confirmation must be enabled before registration can open.",
        );
      }
      return res.json({
        message:
          "Check your email to confirm your account. If you already have an account, sign in or reset your password.",
      });
    }
    if (action === "login") {
      if (!password || password.length > 128)
        throw new ApiError(401, "Email or password is incorrect.");
      const result = await client.auth.signInWithPassword({ email, password });
      if (
        result.error ||
        !result.data.session ||
        !result.data.user.email_confirmed_at
      )
        throw new ApiError(
          401,
          "Sign-in failed. Check your email confirmation and password.",
        );
      setSession(res, result.data.session);
      cookie(res, "recovery", "", 0);
      return res.json({ ok: true });
    }
    if (action === "resend") {
      await client.auth.resend({
        type: "signup",
        email,
        options: { emailRedirectTo: origin() + "/confirm" },
      });
      return res.json({
        message: "If confirmation is needed, a new email will arrive shortly.",
      });
    }
    if (action === "reset") {
      await client.auth.resetPasswordForEmail(email, {
        redirectTo: origin() + "/confirm",
      });
      return res.json({
        message: "If the account exists, a recovery email will arrive shortly.",
      });
    }
    if (action === "verify") {
      if (
        !["signup", "recovery", "email"].includes(body.type) ||
        typeof body.token_hash !== "string" ||
        body.token_hash.length > 256
      )
        throw new ApiError(422, "Invalid confirmation link.");
      const result = await client.auth.verifyOtp({
        token_hash: body.token_hash,
        type: body.type,
      });
      if (result.error || !result.data.session)
        throw new ApiError(
          422,
          "This link expired or was already used. Request a new email.",
        );
      setSession(res, result.data.session);
      if (body.type === "recovery") {
        const payload = `${result.data.user!.id}:${Date.now()}`;
        cookie(res, "recovery", `${payload}.${sign(payload)}`, 600);
      }
      return res.json({ ok: true, recovery: body.type === "recovery" });
    }
    if (action === "adopt") {
      // Supabase's own sender cannot use a custom email template on the free
      // tier, so recovery links point at /auth/v1/verify. That endpoint spends
      // the one-time token itself and redirects here with the session in the
      // URL fragment, which never reaches a server. Only recovery needs this:
      // a confirmed signup can simply sign in with the password it already set.
      if (body.type !== "recovery")
        throw new ApiError(422, "Invalid confirmation link.");
      const access =
        typeof body.access_token === "string" ? body.access_token : "";
      const refresh =
        typeof body.refresh_token === "string" ? body.refresh_token : "";
      if (
        !access ||
        access.length > 4096 ||
        !refresh ||
        refresh.length > 512
      )
        throw new ApiError(422, "Invalid confirmation link.");
      // Trust nothing from the fragment until Supabase vouches for it.
      const holder = await client.auth.getUser(access);
      if (holder.error || !holder.data.user?.email_confirmed_at)
        throw new ApiError(
          422,
          "This link expired or was already used. Request a new email.",
        );
      setSession(res, { access_token: access, refresh_token: refresh });
      const payload = `${holder.data.user.id}:${Date.now()}`;
      cookie(res, "recovery", `${payload}.${sign(payload)}`, 600);
      return res.json({ ok: true, recovery: true });
    }
    const current = await session(req, res);
    if (!current) throw new ApiError(401, "Sign in again.");
    if (action === "logout") {
      const r = await fetch(
        `${process.env.SUPABASE_URL}/auth/v1/logout?scope=global`,
        {
          method: "POST",
          headers: {
            apikey: process.env.SUPABASE_PUBLISHABLE_KEY!,
            Authorization: `Bearer ${current.token}`,
          },
        },
      );
      clearSession(res);
      if (!r.ok)
        throw new ApiError(
          503,
          "Local session cleared. Server sign-out could not be confirmed.",
        );
      return res.json({ ok: true });
    }
    if (action === "password") {
      await rateLimit(req, current.user.email!);
      const recovery = req.cookies[name("recovery")] ?? "";
      const [payload, signature] = recovery.split(".");
      const [uid, stamp] = (payload ?? "").split(":");
      const elapsed = Date.now() - Number(stamp);
      const recovering =
        uid === current.user.id &&
        elapsed >= 0 &&
        elapsed < 600000 &&
        signature &&
        equal(sign(payload), signature);
      if (!recovering) {
        await reauthenticate(current.user.email!, body.current_password);
      }
      const r = await fetch(`${process.env.SUPABASE_URL}/auth/v1/user`, {
        method: "PUT",
        headers: {
          apikey: process.env.SUPABASE_PUBLISHABLE_KEY!,
          Authorization: `Bearer ${current.token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ password }),
      });
      if (!r.ok)
        throw new ApiError(
          422,
          "Password could not be changed. Request a new recovery email.",
        );
      const revoked = await fetch(
        `${process.env.SUPABASE_URL}/auth/v1/logout?scope=others`,
        {
          method: "POST",
          headers: {
            apikey: process.env.SUPABASE_PUBLISHABLE_KEY!,
            Authorization: `Bearer ${current.token}`,
          },
          signal: AbortSignal.timeout(10000),
        },
      );
      cookie(res, "recovery", "", 0);
      return res.json({
        message: revoked.ok
          ? "Password updated. Other sessions have been signed out."
          : "Password updated. Other sessions could not be revoked; use Sign out and sign in again.",
      });
    }
  } catch (error) {
    return fail(res, error);
  }
}
