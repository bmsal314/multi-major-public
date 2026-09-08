import Head from "next/head";
import { useCallback, useEffect, useRef, useState } from "react";
import AccountForm from "../components/AccountForm";
import PlanningPreferences, {
  preferencesAreValid,
} from "../components/PlanningPreferences";
import Dashboard from "../components/Dashboard";
import {
  api,
  auth,
  defaults,
  Job,
  Preferences,
  readSession,
  SavedPlan,
  Session,
  upload,
} from "../lib/cloud";
import type { PlanState, PlanResult } from "../lib/api";
import { flushPendingSaves } from "../lib/saveQueue";

export default function Home() {
  const [reviewPrograms, setReviewPrograms] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [files, setFiles] = useState<File[]>([]);
  const [consent, setConsent] = useState(false);
  const [preferences, setPreferences] = useState<Preferences>(defaults);
  const [plans, setPlans] = useState<SavedPlan[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [editorPlan, setEditorPlan] = useState<PlanResult | null>(null);
  const [loaded, setLoaded] = useState<SavedPlan | null>(null);
  const [replayNotes, setReplayNotes] = useState<string[]>([]);
  const sessionEpoch = useRef(0);
  const current = useRef<SavedPlan | null>(null);
  const [drag, setDrag] = useState(false);
  const refresh = useCallback(async () => {
    const epoch = sessionEpoch.current;
    try {
      const s = await readSession();
      if (epoch !== sessionEpoch.current) return;
      setSession(s);
      if (s.user) {
        const [p, j, profile] = await Promise.all([
          api<SavedPlan[]>("plans"),
          api<Job[]>("analyses"),
          api<{ preferences: Partial<Preferences> }>("profile"),
        ]);
        if (epoch !== sessionEpoch.current) return;
        setPlans(p);
        setJobs(j);
        setPreferences({
          ...defaults,
          ...profile.preferences,
          personal_rules: {
            ...defaults.personal_rules,
            ...profile.preferences.personal_rules,
          },
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not connect.");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
    const ended = () => {
      sessionEpoch.current += 1;
      setPreferences(defaults);
      setSession(null);
      setLoaded(null);
      setEditorPlan(null);
      current.current = null;
      setPlans([]);
      setJobs([]);
      setFiles([]);
      setError("Your session ended. Sign in again to continue.");
    };
    window.addEventListener("session-ended", ended);
    return () => window.removeEventListener("session-ended", ended);
  }, [refresh]);
  // The permutations dashboard links back here as /?plan=<id>.
  useEffect(() => {
    if (!session?.user || current.current) return;
    const wanted = new URLSearchParams(window.location.search).get("plan");
    if (wanted) void open(wanted);
    // Opening is keyed on the id in the URL, so it must not re-run on every
    // plan-list refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user]);
  useEffect(() => {
    if (
      !session?.user ||
      !jobs.some((j) => ["queued", "processing"].includes(j.status))
    )
      return;
    const epoch = sessionEpoch.current;
    const timer = setInterval(() => {
      void api<Job[]>("analyses")
        .then((next) => {
          if (epoch !== sessionEpoch.current) return;
          setJobs(next);
          const finished = next.find(
            (j) =>
              j.status === "completed" &&
              jobs.find((old) => old.id === j.id)?.status !== "completed",
          );
          if (finished)
            void api<SavedPlan[]>("plans").then((p) => {
              if (epoch !== sessionEpoch.current) return;
              setPlans(p);
              // Waiting on a map and then being left on the upload page with a
              // list is a dead end: the thing that was asked for is ready and
              // nothing shows it. Open it, unless the student has already
              // opened something else in the meantime.
              if (finished.plan_id && !current.current)
                void open(finished.plan_id, true);
            });
        })
        .catch(() => undefined);
    }, 3000);
    return () => clearInterval(timer);
  }, [session?.user, jobs]);
  const open = async (id: string, review = false) => {
    const epoch = sessionEpoch.current;
    setBusy(true);
    setError("");
    try {
      const p = await api<SavedPlan>(`plans/${id}`);
      if (epoch !== sessionEpoch.current) return;
      setPreferences(p.preferences);
      if (epoch !== sessionEpoch.current) return;
      current.current = p;
      setLoaded(p);
      setEditorPlan(p.result.plan);
      setReplayNotes([]);
      setReviewPrograms(review);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const save = useCallback(async (state: PlanState) => {
    const epoch = sessionEpoch.current;
    const p = current.current;
    if (!p) throw new Error("Open a saved plan first.");
    const next = await api<SavedPlan>(`plans/${p.id}`, "PUT", {
      revision: p.revision,
      state,
    });
    if (epoch !== sessionEpoch.current)
      throw new Error("Session changed while saving.");
    current.current = next;
    setLoaded(next);
    // The service rebuilds the map from the audit and can refuse part of an edit
    // — a placeholder filled with a course the requirement does not list, a move
    // into a term that no longer exists. The editor keeps showing what was typed,
    // so without this the refusal would only surface after a reload.
    setReplayNotes(
      (next.result.plan.warnings ?? []).filter((warning) =>
        /no longer matches|remains unresolved|no longer in the plan|term no longer/i.test(
          warning,
        ),
      ),
    );
  }, []);
  const receive = (incoming: File[]) => {
    setError("");
    if (incoming.some((f) => !f.name.toLowerCase().endsWith(".pdf"))) {
      setError("Choose PDF reports only.");
      return;
    }
    const merged = [...files, ...incoming];
    if (merged.length > 8) {
      setError("Choose no more than eight reports.");
      return;
    }
    setFiles(merged);
  };
  async function run() {
    setBusy(true);
    setProgress(0);
    setError("");
    try {
      await api("profile", "PUT", { preferences });
      await upload(files, preferences, setProgress);
      setFiles([]);
      setConsent(false);
      // The service now reads the reports while the request is open, so a job can
      // already be finished here. Nothing would poll for it in that case, so ask
      // for the saved maps too rather than leaving the new one out of the list.
      const [j, p] = await Promise.all([
        api<Job[]>("analyses"),
        api<SavedPlan[]>("plans"),
      ]);
      setJobs(j);
      setPlans(p);
      // The service reads the reports while this request is open, so the job can
      // already be finished here and no poll would ever run for it.
      const ready = j.find((job) => job.status === "completed" && job.plan_id);
      if (ready?.plan_id) await open(ready.plan_id, true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function leave() {
    try {
      await flushPendingSaves();
      setLoaded(null);
      setEditorPlan(null);
      setReplayNotes([]);
      current.current = null;
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function logout() {
    try {
      await flushPendingSaves();
      sessionEpoch.current += 1;
      await auth("logout");
      setPreferences(defaults);
      setSession(null);
      setLoaded(null);
      setEditorPlan(null);
      current.current = null;
      setPlans([]);
      setJobs([]);
      setFiles([]);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function remove(p: SavedPlan) {
    if (
      !window.confirm(
        `Delete “${p.name}”? Your parsed audit will remain until you delete it in account settings.`,
      )
    )
      return;
    try {
      await api(`plans/${p.id}`, "DELETE");
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  // A disabled button with no explanation is a dead end. There are four
  // separate reasons this one can be unavailable, and each has its own fix.
  const activeJob = jobs.some((j) =>
    ["awaiting_upload", "queued", "processing"].includes(j.status),
  );
  const blockedReason = !files.length
    ? "Choose at least one Full Requirements PDF to continue."
    : !preferencesAreValid(preferences)
      ? "Fix the highlighted planning preferences above to continue."
      : !consent
        ? "Tick the storage agreement above to continue."
        : activeJob
          ? "One report set is already being processed. Wait for it to finish, or cancel it above."
          : "";
  async function variant() {
    const epoch = sessionEpoch.current;
    if (!loaded) return;
    setBusy(true);
    try {
      await flushPendingSaves();
      const p = await api<SavedPlan>("plans", "POST", {
        audit_id: loaded.audit_id,
        name: `${loaded.name} — alternative`,
        preferences,
      });
      if (epoch !== sessionEpoch.current) return;
      current.current = p;
      setLoaded(p);
      setEditorPlan(p.result.plan);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Head>
        <title>Multi-Major · Your degrees, one semester map</title>
        <meta
          name="description"
          content="Bring your DARS reports together into a private, personalized semester plan."
        />
      </Head>
      <header className="platform-header">
        <a
          className="platform-brand"
          href="/"
          onClick={
            loaded
              ? (e) => {
                  e.preventDefault();
                  void leave();
                }
              : undefined
          }
        >
          <span className="brand-symbol" aria-hidden="true">
            M<span>↗</span>
          </span>
          Multi-Major
        </a>
        <nav aria-label="Account">
          {session?.user ? (
            <>
              <a href="/plans">My maps</a>
              <a href="/account">Account</a>
              <button onClick={() => void logout()}>Sign out</button>
            </>
          ) : (
            <a href="/privacy">Privacy</a>
          )}
        </nav>
      </header>
      {error && (
        <div className="global-message" role="alert">
          {error}
          <button onClick={() => setError("")} aria-label="Dismiss message">
            ×
          </button>
        </div>
      )}
      {loading ? (
        <main className="platform-main">
          <p role="status">Loading your workspace…</p>
        </main>
      ) : !session?.user ? (
        <main className="welcome-layout">
          <section className="welcome-copy">
            <p className="eyebrow">For undergraduate students</p>
            <h1>
              More than one path.
              <br />
              <em>One clear plan.</em>
            </h1>
            <p className="lede">
              Turn your degree audits into a semester map that makes room for
              all your goals.
            </p>
            <div
              className="path-preview"
              role="group"
              aria-label="Upload your DARS, review requirements, build your semester map"
            >
              <span>
                <b>01</b>Your DARS
              </span>
              <i />
              <span>
                <b>02</b>Your requirements
              </span>
              <i />
              <span>
                <b>03</b>Your semester map
              </span>
            </div>
            <div className="welcome-points">
              <p>
                <strong>Your programs, together.</strong> Bring majors, minors,
                certificates and honors into one view.
              </p>
              <p>
                <strong>Room for your plans.</strong> Choose pre-med, adjust
                your workload and keep your decisions.
              </p>
              <p>
                <strong>Evidence stays visible.</strong> See what your audit
                says and what needs an advisor’s review.
              </p>
            </div>
            <p className="small">
              Independent student planning tool. Not affiliated with or endorsed
              by any university.
            </p>
          </section>
          <AccountForm
            onSignedIn={() => void refresh()}
            emailReady={session?.email_ready ?? false}
          />
        </main>
      ) : loaded ? (
        <main className="plan-workspace">
          <div className="workspace-toolbar">
            <button
              className="button button-secondary"
              onClick={() => void leave()}
            >
              ← My plans
            </button>
            <span>
              {loaded.name} <small>Revision {loaded.revision}</small>
            </span>
            <button
              className="text-button"
              onClick={() => void open(loaded.id)}
            >
              Reload saved version
            </button>
          </div>
          {reviewPrograms ? (
            <section className="program-confirmation account-card">
              <p className="eyebrow">Step 2 · Confirm your programs</p>
              <h2>Is this the right set of degrees?</h2>
              <p>
                We read {loaded.result.audits.length} program
                {loaded.result.audits.length === 1 ? "" : "s"} out of your
                upload. The catalog year is the set of rules you graduate under
                — normally the year you started — and it decides which
                requirements apply. If a program is missing or the year looks
                wrong, upload a fresh Full Requirements report for it.
              </p>
              <ul>
                {loaded.result.audits.map((a, i) => (
                  <li key={i}>
                    <strong>{a.name}</strong>
                    <small>
                      Graduating under the{" "}
                      {a.summary.catalog_year ?? "unidentified"} catalog ·{" "}
                      {a.campus || "campus not identified"} · we read{" "}
                      {a.requirements.length} requirements from it
                    </small>
                  </li>
                ))}
              </ul>
              <p className="small">
                Anything we could not interpret stays visible on the map for
                your advisor. Confirming this list does not confirm graduation
                eligibility.
              </p>
              <button
                className="button button-primary"
                onClick={() => setReviewPrograms(false)}
              >
                Confirm programs & review map →
              </button>
            </section>
          ) : (
            <Dashboard
              result={loaded.result}
              editorPlan={editorPlan ?? loaded.result.plan}
              initialState={loaded.state}
              onReset={() => void leave()}
              onSavePlan={save}
            >
              {replayNotes.length > 0 && (
                <section className="replay-notes" role="status">
                  <strong>
                    The saved map is not identical to what is on screen
                  </strong>
                  <p>
                    Your edits were saved, but rebuilding the map from your audit
                    could not keep all of them. Reload the saved version to see
                    exactly what is stored.
                  </p>
                  <ul>
                    {replayNotes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                  <button
                    className="button button-secondary"
                    onClick={() => void open(loaded.id)}
                  >
                    Reload saved version
                  </button>
                </section>
              )}
              <section className="variant-panel">
                <h2>Try another workload</h2>
                <p>
                  Create a separate plan from the same parsed requirements. Your
                  current map stays saved.
                </p>
                <PlanningPreferences
                  value={preferences}
                  onChange={setPreferences}
                />
                <button
                  className="button button-secondary"
                  disabled={busy || !preferencesAreValid(preferences)}
                  onClick={() => void variant()}
                >
                  Create alternative plan
                </button>
              </section>
            </Dashboard>
          )}
        </main>
      ) : (
        <main className="platform-main">
          <div className="workspace-title">
            <div>
              <p className="eyebrow">Your private workspace</p>
              <h1>Plan what comes next.</h1>
            </div>
            <span className="pilot-badge">Student pilot</span>
          </div>
          {plans.length > 0 && (
            <section className="saved-section">
              <h2>
                My semester maps
                <a className="text-button" href="/plans">
                  Compare permutations →
                </a>
              </h2>
              <div className="saved-grid">
                {plans.map((p) => (
                  <article key={p.id}>
                    <small>
                      {p.preferences.premed ? "Pre-med · " : ""}Saved{" "}
                      {new Date(p.updated_at).toLocaleDateString()}
                    </small>
                    <h3>{p.name}</h3>
                    <p>
                      {p.preferences.credits_per_term} credit ceiling ·{" "}
                      {p.preferences.include_summer
                        ? "Includes summer"
                        : "Regular semesters"}
                    </p>
                    <div>
                      <button
                        className="button button-secondary"
                        disabled={busy}
                        onClick={() => void open(p.id)}
                      >
                        Open map →
                      </button>
                      <button
                        className="text-button"
                        onClick={() => void remove(p)}
                      >
                        Delete
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          )}
          <div className="workspace-columns">
          <div className="workspace-primary">
          {jobs.some((j) => j.status !== "cancelled") && (
            <section
              className="jobs-section"
              aria-label="Recent processing jobs"
            >
              {jobs
                .filter((j) => j.status !== "cancelled")
                .slice(0, 4)
                .map((j) => (
                  <div className="job-row" key={j.id}>
                    <span>
                      <strong>
                        {j.status === "completed"
                          ? "Your map is ready"
                          : j.status === "failed"
                            ? "A report needs attention"
                            : j.status === "awaiting_upload"
                              ? "Upload incomplete"
                              : "Building your semester map"}
                      </strong>
                      <small>
                        {j.error ??
                          (j.status === "queued" || j.status === "processing"
                            ? (j.stage ?? "Getting started") +
                              " · You can leave this page. We’ll keep your result here."
                            : new Date(j.created_at).toLocaleString())}
                      </small>
                      {(j.status === "queued" || j.status === "processing") && (
                        <progress
                          className="job-progress"
                          max={100}
                          value={j.progress || undefined}
                          aria-label={`Analysis progress: ${j.stage ?? "starting"}`}
                        />
                      )}
                    </span>
                    {j.plan_id ? (
                      <button
                        className="button button-secondary"
                        onClick={() => void open(j.plan_id!, true)}
                      >
                        Review map →
                      </button>
                    ) : ["awaiting_upload", "queued", "processing"].includes(
                        j.status,
                      ) ? (
                      <button
                        onClick={() =>
                          void api(`analyses/${j.id}`, "DELETE").then(() =>
                            refresh(),
                          )
                        }
                      >
                        Cancel
                      </button>
                    ) : null}
                  </div>
                ))}
            </section>
          )}
          <section className="upload-workspace">
            <div className="upload-heading">
              <span className="step-dot">1</span>
              <div>
                <h2>Bring your DARS reports.</h2>
                <p>
                  One Full Requirements PDF per program. We’ll identify the
                  requirements and keep the evidence visible.
                </p>
              </div>
            </div>
            <div
              className={`cloud-drop ${drag ? "dragging" : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setDrag(true);
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDrag(false);
                receive(Array.from(e.dataTransfer.files));
              }}
            >
              <span className="upload-icon" aria-hidden="true">
                ↥
              </span>
              <strong>Drop your PDFs here</strong>
              <span>or choose files from your device</span>
              <label className="button button-secondary">
                Choose DARS PDFs
                <input
                  type="file"
                  accept=".pdf,application/pdf"
                  multiple
                  onChange={(e) => {
                    receive(Array.from(e.target.files ?? []));
                    e.target.value = "";
                  }}
                />
              </label>
              <small>
                Up to 8 PDFs · 25 MB each · 100 MB total · text-based reports
              </small>
            </div>
            {files.length > 0 && (
              <ul className="file-list">
                {files.map((f, i) => (
                  <li key={i}>
                    <span>
                      {f.name}
                      <small>{(f.size / 1024).toFixed(0)} KB</small>
                    </span>
                    <button
                      onClick={() => setFiles(files.filter((_, n) => i !== n))}
                      aria-label={`Remove ${f.name}`}
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="upload-heading second">
              <span className="step-dot">2</span>
              <div>
                <h2>Make it yours.</h2>
                <p>
                  Start with your audits. Fine-tune the details when you need
                  them.
                </p>
              </div>
            </div>
            <PlanningPreferences
              value={preferences}
              onChange={setPreferences}
            />
            <label className="check-row consent">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
              />
              <span>
                I agree to store my parsed academic requirements and plans in my
                account. Original PDFs are deleted after processing.{" "}
                <a href="/privacy">Read the privacy notice.</a>
              </span>
            </label>
            <div className="upload-submit">
              <button
                className="button button-primary"
                disabled={busy || blockedReason !== ""}
                onClick={() => void run()}
              >
                {busy ? `Uploading · ${progress}%` : "Build my semester map →"}
              </button>
              <span>
                {blockedReason ||
                  "No saved or shared PDF library. Only the reports you upload."}
              </span>
            </div>
          </section>
          </div>
          <aside className="workspace-side">
            <div className="draft-note">
              <strong>A useful draft, with the evidence attached.</strong>
              <p>
                Verify your programs, catalog years and flagged requirements
                when your map is ready. Course offerings, substitutions and
                graduation decisions still need your academic advisor.
              </p>
            </div>
            <div className="draft-note">
              <strong>What a Full Requirements report looks like.</strong>
              <p>
                In your university's student portal, open <em>Degree Audit
                Reports</em>, run an audit for each program, then use{" "}
                <em>Download PDF</em>. Save the PDF
                rather than printing the page — a printed or scanned copy has no
                text to read.
              </p>
            </div>
          </aside>
          </div>
        </main>
      )}
      <footer className="platform-footer">
        <span>Multi-Major · Independent semester planning</span>
        <a href="/privacy">Privacy & planning notice</a>
      </footer>
    </>
  );
}

// Per-request rendering supplies a fresh script nonce; no shared HTML cache.
export async function getServerSideProps() {
  return { props: {} };
}
