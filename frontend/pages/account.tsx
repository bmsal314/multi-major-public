import { FormEvent, useEffect, useState } from "react";
import Head from "next/head";
import { useRouter } from "next/router";
import { api, auth, readSession, User } from "../lib/cloud";
import PasswordField from "../components/PasswordField";
export default function Account() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  // Two different questions asked in two different sections. One shared value
  // would put whatever was typed in the danger zone into the change-password
  // request as well, so each form keeps its own.
  const [currentPassword, setCurrentPassword] = useState("");
  const [deletePassword, setDeletePassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  // A recovery link is only good for ten minutes. Past that the server asks for
  // the old password again, so the field has to come back rather than leaving
  // the page asking for something it never shows a box for.
  const [needCurrent, setNeedCurrent] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [audits, setAudits] = useState<{ id: string; created_at: string }[]>(
    [],
  );
  useEffect(() => {
    void readSession()
      .then(async (s) => {
        if (!s.user) {
          await router.replace("/");
          return;
        }
        setUser(s.user);
        setAudits(await api("audits"));
      })
      .catch((e) => setMessage(e.message));
  }, []);
  const recovering = Boolean(router.query.recovery) && !needCurrent;
  const passwordMismatch =
    confirmPassword.length > 0 && password !== confirmPassword;
  async function change(e: FormEvent) {
    e.preventDefault();
    if (password !== confirmPassword) {
      setMessage("Both new passwords must match. Check them and try again.");
      return;
    }
    setBusy(true);
    try {
      const r = await auth<{ message: string }>("password", {
        password,
        current_password: currentPassword,
      });
      setMessage(r.message);
      setPassword("");
      setConfirmPassword("");
      setCurrentPassword("");
    } catch (e) {
      // Only the reauthentication failure means the link lapsed; a rejected new
      // password has to keep saying what was actually wrong with it.
      const detail = (e as Error).message;
      if (recovering && /current password/i.test(detail)) {
        setNeedCurrent(true);
        setMessage(
          "That recovery link has expired. Enter your current password, or request a new recovery email from the sign-in page.",
        );
      } else {
        setMessage(detail);
      }
    } finally {
      setBusy(false);
    }
  }
  async function exportData() {
    setBusy(true);
    try {
      const data: Record<string, unknown> = await api("account/export");
      for (const table of [
        "audits",
        "plans",
        "plan_revisions",
        "analysis_jobs",
      ]) {
        const records: unknown[] = [];
        let offset: number | null = 0;
        while (offset !== null) {
          const page: { records: unknown[]; next_offset: number | null } =
            await api(`account/export?table=${table}&offset=${offset}`);
          records.push(...page.records);
          offset = page.next_offset;
        }
        data[table] = records;
      }
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
      );
      const a = document.createElement("a");
      a.href = url;
      a.download = "multi-major-data.json";
      a.click();
      URL.revokeObjectURL(url);
      setMessage("Your export was downloaded. Keep it somewhere private.");
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function removeAudit(id: string) {
    if (
      !window.confirm(
        "Delete this parsed audit and every semester map based on it?",
      )
    )
      return;
    setBusy(true);
    try {
      await api(`audits/${id}`, "DELETE");
      setAudits(audits.filter((a) => a.id !== id));
      setMessage("Audit and related maps deleted.");
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function removeAccount() {
    setBusy(true);
    try {
      await api("account", "DELETE", {
        confirmation,
        current_password: deletePassword,
      });
      await router.replace("/");
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Head>
        <title>Account · Multi-Major</title>
      </Head>
      <main className="account-page">
        <a className="platform-brand" href="/">
          ← Multi-Major
        </a>
        <h1>Your account</h1>
        <p>{user?.email ?? "Loading…"}</p>
        {message && (
          <p className="inline-notice" role="status">
            {message}
          </p>
        )}
        <section className="account-card">
          <h2>{recovering ? "Set a new password" : "Change password"}</h2>
          <form onSubmit={change}>
            {!recovering && (
              <PasswordField
                label="Current password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={setCurrentPassword}
              />
            )}
            <PasswordField
              label="New password"
              autoComplete="new-password"
              minLength={12}
              hint="At least 12 characters. Password managers are welcome."
              value={password}
              onChange={setPassword}
            />
            <PasswordField
              label="Confirm new password"
              autoComplete="new-password"
              minLength={12}
              hint="Type it a second time so a typo cannot lock you out."
              problem={
                passwordMismatch ? "Both new passwords must match." : undefined
              }
              value={confirmPassword}
              onChange={setConfirmPassword}
            />
            <button className="button button-primary" disabled={busy}>
              Update password
            </button>
          </form>
        </section>
        <section className="account-card">
          <h2>Your academic data</h2>
          <p>
            Export your account data or remove parsed audits. Original PDFs are
            not kept as a library.
          </p>
          <button
            className="button button-secondary"
            disabled={busy}
            onClick={() => void exportData()}
          >
            Export my data
          </button>
          <ul className="file-list">
            {audits.map((a) => (
              <li key={a.id}>
                <span>
                  Audit set · {new Date(a.created_at).toLocaleDateString()}
                </span>
                <button disabled={busy} onClick={() => void removeAudit(a.id)}>
                  Delete audit & maps
                </button>
              </li>
            ))}
          </ul>
        </section>
        <section className="account-card danger-zone">
          <h2>Delete account</h2>
          <p>
            This removes your active account, parsed audits and plans.
            Processing is cancelled. Backup copies expire under the provider’s
            retention policy.
          </p>
          <label>
            Current password
            <input
              type="password"
              autoComplete="current-password"
              value={deletePassword}
              onChange={(e) => setDeletePassword(e.target.value)}
            />
          </label>
          <label>
            Type DELETE to confirm
            <input
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
              autoComplete="off"
            />
          </label>
          <button
            className="button button-secondary"
            disabled={busy || confirmation !== "DELETE" || !deletePassword}
            onClick={() => void removeAccount()}
          >
            Delete my account
          </button>
        </section>
      </main>
    </>
  );
}

// Per-request rendering supplies a fresh script nonce; no shared HTML cache.
export async function getServerSideProps() {
  return { props: {} };
}
