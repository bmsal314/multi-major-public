import { FormEvent, useState, useEffect, useRef } from "react";
import Script from "next/script";
import { auth } from "../lib/cloud";
import PasswordField from "./PasswordField";
declare global {
  interface Window {
    turnstile?: {
      render: (el: HTMLElement, options: { sitekey: string }) => string;
      reset: (id: string) => void;
      remove: (id: string) => void;
    };
  }
}
export default function AccountForm({
  onSignedIn,
  emailReady,
}: {
  onSignedIn: () => void;
  emailReady: boolean;
}) {
  const [mode, setMode] = useState<"login" | "register" | "reset" | "resend">(
    "register",
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const container = useRef<HTMLDivElement>(null);
  const widget = useRef<string | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (mode === "login" || !ready || !container.current || !window.turnstile)
      return;
    widget.current = window.turnstile.render(container.current, {
      sitekey: process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY!,
    });
    return () => {
      if (widget.current) window.turnstile?.remove(widget.current);
      widget.current = null;
    };
  }, [mode, ready]);
  // Switching tabs asks a different question. Anything already typed belongs to
  // the question that was on screen a moment ago, not this one.
  useEffect(() => {
    setPassword("");
    setConfirm("");
    setError("");
    setMessage("");
  }, [mode]);
  const mismatch =
    mode === "register" && confirm.length > 0 && password !== confirm;
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (mode === "register" && password !== confirm) {
      setError("Both passwords must match. Check them and try again.");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    const data = new FormData(e.currentTarget);
    try {
      const result = await auth<{ message?: string }>(mode, {
        email,
        password,
        captcha: data.get("cf-turnstile-response"),
      });
      setPassword("");
      setConfirm("");
      if (mode === "login") onSignedIn();
      else setMessage(result.message ?? "Check your email.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Please try again.");
    } finally {
      setBusy(false);
      if (widget.current) window.turnstile?.reset(widget.current);
    }
  }
  return (
    <section className="account-card" aria-labelledby="account-title">
      <div className="segmented">
        <button
          type="button"
          className={mode === "register" ? "active" : ""}
          onClick={() => setMode("register")}
        >
          Create account
        </button>
        <button
          type="button"
          className={mode === "login" ? "active" : ""}
          onClick={() => setMode("login")}
        >
          Sign in
        </button>
      </div>
      <h2 id="account-title">
        {mode === "register"
          ? "A home for your next semester."
          : mode === "login"
            ? "Welcome back."
            : mode === "reset"
              ? "Reset your password."
              : "Confirm your email."}
      </h2>
      <p>Your audits and plans stay private to your account.</p>
      <form onSubmit={submit}>
        <label>
          Email address
          <input
            name="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            maxLength={254}
          />
        </label>
        {(mode === "register" || mode === "login") && (
          <PasswordField
            label="Password"
            name="password"
            autoComplete={
              mode === "register" ? "new-password" : "current-password"
            }
            minLength={mode === "register" ? 12 : 1}
            hint={
              mode === "register"
                ? "At least 12 characters. Password managers are welcome."
                : undefined
            }
            value={password}
            onChange={setPassword}
          />
        )}
        {mode === "register" && (
          <PasswordField
            label="Confirm password"
            autoComplete="new-password"
            minLength={12}
            hint="Type it a second time so a typo cannot lock you out."
            problem={mismatch ? "Both passwords must match." : undefined}
            value={confirm}
            onChange={setConfirm}
          />
        )}
        {mode !== "login" && process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY && (
          <>
            <Script
              src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"
              strategy="afterInteractive"
              onReady={() => setReady(true)}
            />
            <div ref={container} />
          </>
        )}
        {mode === "register" && (
          <p className="small">
            By creating an account, you agree to the{" "}
            <a href="/privacy">privacy and planning notice</a>. We’ll email you
            a confirmation link.
          </p>
        )}
        {!emailReady && mode !== "login" && (
          <p className="inline-notice">
            Registration opens after email delivery is configured.
          </p>
        )}
        <button
          className="button button-primary wide"
          disabled={busy || (!emailReady && mode !== "login")}
        >
          {busy
            ? "Working…"
            : mode === "register"
              ? "Create account"
              : mode === "login"
                ? "Sign in"
                : "Send email"}
        </button>
      </form>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="inline-notice" role="status">
          {message}
        </p>
      )}
      <div className="text-actions">
        <button onClick={() => setMode("reset")}>Forgot password?</button>
        <button onClick={() => setMode("resend")}>Resend confirmation</button>
      </div>
    </section>
  );
}
