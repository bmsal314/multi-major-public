import Head from "next/head";
import { useCallback, useEffect, useState } from "react";
import PlanComparison from "../components/PlanComparison";
import { api, readSession, SavedPlan, Session } from "../lib/cloud";
import type { AnalysisResponse } from "../lib/api";

/**
 * The permutations dashboard.
 *
 * Every saved map is a permutation of the same parsed audit, and the reason to
 * keep several is to decide between them. That decision needs the numbers that
 * differ — how heavy the worst term gets, how much is still unplaced, what the
 * exam semester was held to — which is why each row reads from the stored
 * summary rather than the result it came from.
 */
export default function Plans() {
  const [session, setSession] = useState<Session | null>(null);
  const [plans, setPlans] = useState<SavedPlan[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [comparing, setComparing] = useState(false);
  const [results, setResults] = useState<Record<string, AnalysisResponse>>({});

  const refresh = useCallback(async () => {
    try {
      const s = await readSession();
      setSession(s);
      if (s.user) setPlans(await api<SavedPlan[]>("plans"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load your maps.");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggle = (id: string) =>
    setSelected((current) =>
      current.includes(id)
        ? current.filter((x) => x !== id)
        : // Comparison is between two maps, so selecting a third replaces the
          // older of the pair rather than refusing the click.
          [...current, id].slice(-2),
    );

  async function compare() {
    setError("");
    try {
      // Full results are large, so they are fetched only for the two maps
      // actually being compared, and only when the comparison is opened.
      const [a, b] = await Promise.all(
        selected.map((id) => api<SavedPlan>(`plans/${id}`)),
      );
      setResults({ [a.id]: a.result, [b.id]: b.result });
      setComparing(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const left = plans.find((p) => p.id === selected[0]);
  const right = plans.find((p) => p.id === selected[1]);

  return (
    <>
      <Head>
        <title>My semester maps · Multi-Major</title>
      </Head>
      <header className="platform-header">
        <a className="platform-brand" href="/">
          <span className="brand-symbol" aria-hidden="true">
            M<span>↗</span>
          </span>
          Multi-Major
        </a>
        <nav aria-label="Account">
          <a href="/">Upload</a>
          <a href="/account">Account</a>
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

      <main className="platform-main">
        <div className="workspace-title">
          <div>
            <p className="eyebrow">Your saved permutations</p>
            <h1>Compare your options.</h1>
          </div>
          <span className="pilot-badge">{plans.length} saved</span>
        </div>

        {loading ? (
          <p role="status">Loading your maps…</p>
        ) : !session?.user ? (
          <p>
            <a href="/">Sign in</a> to see your saved maps.
          </p>
        ) : plans.length === 0 ? (
          <div className="empty-state">
            <strong>No saved maps yet.</strong>
            <span>
              <a href="/">Upload your DARS reports</a> to build your first one.
            </span>
          </div>
        ) : (
          <>
            <div className="compare-bar" role="status">
              <span>
                {selected.length === 0
                  ? "Select two maps to compare them."
                  : selected.length === 1
                    ? "Select one more map to compare."
                    : `Comparing ${left?.name} with ${right?.name}.`}
              </span>
              <button
                className="button button-primary"
                disabled={selected.length !== 2}
                onClick={() => void compare()}
              >
                Compare these two →
              </button>
            </div>

            {comparing && left && right && (
              <PlanComparison
                left={left}
                right={right}
                leftResult={results[left.id] ?? null}
                rightResult={results[right.id] ?? null}
                onClose={() => setComparing(false)}
              />
            )}

            <div className="permutation-grid">
              {plans.map((plan) => {
                const s = plan.summary;
                const chosen = selected.includes(plan.id);
                return (
                  <article
                    key={plan.id}
                    className={`permutation-card ${chosen ? "chosen" : ""}`}
                  >
                    <label className="permutation-select">
                      <input
                        type="checkbox"
                        checked={chosen}
                        onChange={() => toggle(plan.id)}
                      />
                      <span>Compare</span>
                    </label>
                    <h2>{plan.name}</h2>
                    <p className="small">
                      {(s?.programs ?? []).join(" · ") || "Programs not recorded"}
                      {" · "}Saved {new Date(plan.updated_at).toLocaleDateString()}
                    </p>
                    <dl className="permutation-metrics">
                      <div>
                        <dt>Graduates</dt>
                        <dd>{s?.graduation_term || "—"}</dd>
                      </div>
                      <div>
                        <dt>Credits</dt>
                        <dd>{s?.planned_credits ?? 0}</dd>
                      </div>
                      <div>
                        <dt>Heaviest term</dt>
                        <dd>{s?.heaviest_term_credits ?? 0} cr</dd>
                      </div>
                      <div>
                        <dt>Ceiling</dt>
                        <dd>{s?.credits_per_term ?? 0} cr</dd>
                      </div>
                      <div>
                        <dt>Still to choose</dt>
                        <dd>{s?.placeholder_count ?? 0}</dd>
                      </div>
                      <div>
                        <dt>Not yet placed</dt>
                        <dd>{s?.unplaced_count ?? 0}</dd>
                      </div>
                    </dl>
                    <ul className="permutation-flags">
                      {s?.premed && (
                        <li>
                          Pre-med
                          {s.mcat_terms.length
                            ? ` · MCAT ${s.mcat_terms[0]} held to ${s.mcat_course_ceiling} classes`
                            : ""}
                        </li>
                      )}
                      {s?.include_summer && <li>Summer terms included</li>}
                      {Object.entries(s?.personal_rules ?? {})
                        .filter(([, on]) => on)
                        .map(([rule]) => (
                          <li key={rule}>
                            {rule.replace(/_/g, " ")} rule applied
                          </li>
                        ))}
                      {(s?.gap_count ?? 0) > 0 && (
                        <li className="flag-warning">
                          {s.gap_count} unresolved check
                          {s.gap_count === 1 ? "" : "s"}
                        </li>
                      )}
                    </ul>
                    <a className="button button-secondary" href={`/?plan=${plan.id}`}>
                      Open map →
                    </a>
                  </article>
                );
              })}
            </div>
          </>
        )}
      </main>
      <footer className="platform-footer">
        <span>Multi-Major · Independent planning for ASU students</span>
        <a href="/privacy">Privacy & planning notice</a>
      </footer>
    </>
  );
}

export async function getServerSideProps() {
  return { props: {} };
}
