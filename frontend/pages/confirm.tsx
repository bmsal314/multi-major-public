import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import Head from "next/head";
import { auth, readSession } from "../lib/cloud";
// Two shapes of link arrive here.
//
// A custom Supabase email template sends /confirm?token_hash=…&type=…, and this
// page spends that token itself — the "token" mode below.
//
// Supabase's own sender cannot use a custom template on the free tier, so its
// links go to /auth/v1/verify instead. That endpoint spends the token and
// redirects here with the outcome in the URL fragment. A confirmed signup needs
// nothing further, because the account already has a password. Recovery does:
// the fragment is the only proof of who is resetting, so it is handed to the
// server over POST and exchanged for the app's own session cookies.
type Mode = "token" | "recovery" | "confirmed" | "error" | "none";
export default function Confirm() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<Mode>("none");
  const [grant, setGrant] = useState<{ access: string; refresh: string } | null>(
    null,
  );
  useEffect(() => {
    void readSession()
      .then(() => setReady(true))
      .catch((e) => setMessage(e.message));
  }, []);
  useEffect(() => {
    const fragment = new URLSearchParams(
      window.location.hash.replace(/^#/, ""),
    );
    // The fragment holds a live session. Take it out of the address bar before
    // it can reach browser history, a bookmark or a copied link.
    if (window.location.hash)
      window.history.replaceState(
        null,
        "",
        window.location.pathname + window.location.search,
      );
    const failure =
      fragment.get("error_description") ?? fragment.get("error") ?? "";
    const access = fragment.get("access_token");
    const refresh = fragment.get("refresh_token");
    if (failure) {
      setMessage(failure.replace(/\+/g, " "));
      setMode("error");
    } else if (access && refresh && fragment.get("type") === "recovery") {
      setGrant({ access, refresh });
      setMode("recovery");
    } else if (access) {
      setMode("confirmed");
    } else if (new URLSearchParams(window.location.search).has("token_hash")) {
      setMode("token");
    }
  }, []);
  async function verify() {
    setBusy(true);
    try {
      const data = await auth<{ recovery: boolean }>("verify", {
        token_hash: router.query.token_hash,
        type: router.query.type,
      });
      await router.replace(data.recovery ? "/account?recovery=1" : "/");
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function adopt() {
    if (!grant) return;
    setBusy(true);
    try {
      await auth("adopt", {
        type: "recovery",
        access_token: grant.access,
        refresh_token: grant.refresh,
      });
      setGrant(null);
      await router.replace("/account?recovery=1");
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const recovering =
    mode === "recovery" ||
    (mode === "token" && router.query.type === "recovery");
  const heading = recovering
    ? "Recover your account"
    : mode === "confirmed"
      ? "Email confirmed"
      : "Confirm your email";
  return (
    <>
      <Head>
        <title>Confirm your email · Multi-Major</title>
        <meta name="referrer" content="no-referrer" />
      </Head>
      <main className="account-page">
        <a className="platform-brand" href="/">
          Multi-Major
        </a>
        <section className="account-card">
          <h1>{heading}</h1>
          {mode === "confirmed" ? (
            <p>
              Your email address is confirmed. Sign in with the password you
              chose to start planning.
            </p>
          ) : mode === "error" || mode === "none" ? (
            <p>
              This link is no longer usable. Request a new one from the sign-in
              page and open it as soon as it arrives.
            </p>
          ) : (
            <p>
              Continue to finish setting up your secure account. This link can
              be used once.
            </p>
          )}
          {(mode === "token" || mode === "recovery") && (
            <button
              className="button button-primary"
              disabled={!ready || busy}
              onClick={() => void (mode === "token" ? verify() : adopt())}
            >
              {busy ? "Verifying…" : "Continue"}
            </button>
          )}
          {message && (
            <p role="alert" className="form-error">
              {message}
            </p>
          )}
          <p>
            <a href="/">Back to sign in</a>
          </p>
        </section>
      </main>
    </>
  );
}

// Per-request rendering supplies a fresh script nonce; no shared HTML cache.
export async function getServerSideProps() {
  return { props: {} };
}
