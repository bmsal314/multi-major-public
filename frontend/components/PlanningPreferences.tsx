import { useState } from "react";
import { Preferences } from "../lib/cloud";
import { MAX_TERM_CREDITS, TERM_OPTIONS, termsInWindow } from "../lib/terms";

/**
 * The server validates these too, and it has to — but its rejection is a single
 * generic 422, because a validation message that echoes the submitted body is a
 * way to leak a student's input back out. So the only place a person can be told
 * *which* field is wrong is here, before the request is sent.
 */
function problems(value: Preferences): string[] {
  const found: string[] = [];
  if (
    !Number.isFinite(value.credits_per_term) ||
    value.credits_per_term < 1 ||
    value.credits_per_term > MAX_TERM_CREDITS
  )
    found.push(`Set a credit ceiling between 1 and ${MAX_TERM_CREDITS}.`);
  if (
    !Number.isFinite(value.min_credits) ||
    value.min_credits < 0 ||
    value.min_credits > MAX_TERM_CREDITS
  )
    found.push(`Set a credit minimum between 0 and ${MAX_TERM_CREDITS}.`);
  else if (value.min_credits > value.credits_per_term)
    found.push(
      "Your credit minimum is above your ceiling. Lower the minimum or raise the ceiling.",
    );
  if (value.premed && value.mcat_terms.length > 0) {
    if (
      !Number.isFinite(value.mcat_course_ceiling) ||
      value.mcat_course_ceiling < 1 ||
      value.mcat_course_ceiling > 12
    )
      found.push("Choose between 1 and 12 classes for your MCAT semester.");
    if (
      !Number.isFinite(value.mcat_credit_ceiling) ||
      value.mcat_credit_ceiling < 1 ||
      value.mcat_credit_ceiling > MAX_TERM_CREDITS
    )
      found.push(
        `Choose between 1 and ${MAX_TERM_CREDITS} credits for your MCAT semester.`,
      );
  }
  const commitment = value.recurring_commitment;
  if (commitment.enabled) {
    if (!commitment.label.trim())
      found.push("Name the class you want every semester.");
    if (!/^[A-Za-z]{2,4}$/.test(commitment.code.trim()))
      found.push("Use a subject code such as DCE for your standing class.");
    if (!Number.isFinite(commitment.credits) || commitment.credits < 0 || commitment.credits > 6)
      found.push("Set your standing class between 0 and 6 credits.");
  }
  const start = TERM_OPTIONS.indexOf(value.start_term);
  const end = TERM_OPTIONS.indexOf(value.graduation_term);
  // The planner no longer guesses a finish date — only the student knows when
  // they intend to graduate, and the credit ceiling is judged against it.
  if (!value.graduation_term)
    found.push("Choose the semester you want to graduate in.");
  if (value.start_term && value.graduation_term && end < start)
    found.push("Your graduation target is before your first semester.");
  return found;
}

/** True when these preferences would be refused by the planning service. */
export function preferencesAreValid(value: Preferences): boolean {
  return problems(value).length === 0;
}

// Shown as guidance next to the MCAT workload inputs. These mirror the
// planner's defaults in backend/semester_planner.py.
const DEFAULT_MCAT_COURSES = 4;
const DEFAULT_MCAT_CREDITS = 12;

export default function PlanningPreferences({
  value,
  onChange,
}: {
  value: Preferences;
  onChange: (p: Preferences) => void;
}) {
  const patch = (p: Partial<Preferences>) => onChange({ ...value, ...p });
  // An empty number field reads as NaN, not as zero. Treating it as zero would
  // silently send a ceiling of 0 and get an unexplained refusal back.
  const numeric = (raw: string) => (raw.trim() === "" ? NaN : Number(raw));
  const issues = problems(value);
  // Capacity implied by the two things they have already chosen.
  const pace = (() => {
    if (!value.graduation_term || !Number.isFinite(value.credits_per_term))
      return null;
    const window = termsInWindow(
      value.start_term || TERM_OPTIONS[0],
      value.graduation_term,
      value.include_summer,
    );
    const terms = Math.max(0, window.length - 1);
    if (terms <= 0) return null;
    const capacity = terms * value.credits_per_term;
    return { terms, capacity, tight: terms <= 2 };
  })();
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="planning-preferences">
      <label className="check-row premed-choice">
        <input
          type="checkbox"
          checked={value.premed}
          onChange={(e) =>
            patch({
              premed: e.target.checked,
              mcat_terms: e.target.checked ? value.mcat_terms : [],
            })
          }
        />
        <span>
          <strong>I’m planning for medical school</strong>
          <small>Add pre-med coursework and optional MCAT planning.</small>
        </span>
      </label>
      {/* A problem lives inside this panel, so the panel cannot stay shut while
          one exists — otherwise the submit button is disabled with the reason
          hidden. */}
      <details
        open={expanded || issues.length > 0}
        onToggle={(event) => setExpanded(event.currentTarget.open)}
      >
        <summary>
          Planning preferences{" "}
          <span>{issues.length > 0 ? "Needs attention" : "Optional"}</span>
        </summary>
        <div className="preference-grid">
          <label>
            First semester
            <select
              value={value.start_term}
              onChange={(e) => patch({ start_term: e.target.value })}
            >
              <option value="">Use my current semester</option>
              {TERM_OPTIONS.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>
          <label>
            When do you want to graduate?
            <select
              value={value.graduation_term}
              onChange={(e) => patch({ graduation_term: e.target.value })}
            >
              <option value="">Choose a semester</option>
              {TERM_OPTIONS.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>
          <label>
            Usual credit ceiling
            <input
              type="number"
              min="1"
              max={MAX_TERM_CREDITS}
              inputMode="numeric"
              value={Number.isFinite(value.credits_per_term) ? value.credits_per_term : ""}
              onChange={(e) =>
                patch({ credits_per_term: numeric(e.target.value) })
              }
            />
          </label>
          <label>
            Personal credit minimum
            <input
              type="number"
              min="0"
              max={MAX_TERM_CREDITS}
              inputMode="numeric"
              value={Number.isFinite(value.min_credits) ? value.min_credits : ""}
              onChange={(e) => patch({ min_credits: numeric(e.target.value) })}
            />
            <small>
              0 means no minimum. Check your own enrollment conditions.
            </small>
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={value.include_summer}
              onChange={(e) => patch({ include_summer: e.target.checked })}
            />
            Include summer semesters
          </label>
          {value.premed && (
            <label>
              MCAT semester
              <select
                value={value.mcat_terms[0] ?? ""}
                onChange={(e) =>
                  patch({ mcat_terms: e.target.value ? [e.target.value] : [] })
                }
              >
                <option value="">Not decided</option>
                {TERM_OPTIONS.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </label>
          )}
        </div>
        {/* Studying for the MCAT is a course load the map cannot see. How much
            room that leaves is the student's judgement, not ours, so we ask
            rather than assume — and we honour whatever they answer. */}
        {value.premed && value.mcat_terms.length > 0 && (
          <fieldset className="mcat-load">
            <legend>Your {value.mcat_terms[0]} workload</legend>
            <p className="small">
              You’ll be studying for the MCAT this semester. Tell us how much
              coursework you want alongside it — we’ll hold the term to it.
            </p>
            <div className="preference-grid">
              <label>
                Classes that semester
                <input
                  type="number"
                  min={1}
                  max={12}
                  value={value.mcat_course_ceiling}
                  onChange={(e) =>
                    patch({
                      mcat_course_ceiling: Number(e.target.value) || 1,
                    })
                  }
                />
              </label>
              <label>
                Credits that semester
                <input
                  type="number"
                  min={1}
                  max={30}
                  value={value.mcat_credit_ceiling}
                  onChange={(e) =>
                    patch({
                      mcat_credit_ceiling: Number(e.target.value) || 1,
                    })
                  }
                />
              </label>
            </div>
            <p className="small">
              Most pre-med students take {DEFAULT_MCAT_COURSES} classes
              ({DEFAULT_MCAT_CREDITS} credits) in their exam semester. Set it
              higher or lower — this is your call, and nothing overrides it.
            </p>
          </fieldset>
        )}
        {/*
          The pace their own answer implies. This is the feedback loop the
          planner is for: they name a finish date, and the ceiling is either
          enough to get there or it is not. Saying so before the upload beats
          discovering it in a map full of unplaced classes.
        */}
        {pace !== null && (
          <p className={`pace-note ${pace.tight ? "pace-tight" : ""}`} role="status">
            {pace.terms} semester{pace.terms === 1 ? "" : "s"} until{" "}
            {value.graduation_term}.{" "}
            {pace.tight ? (
              <>
                A {value.credits_per_term}-credit ceiling holds{" "}
                {pace.capacity} credits over that span. If you have more than
                that left, you will need a higher ceiling, summer terms, or a
                later graduation — the map will tell you exactly how much once
                it has read your audits.
              </>
            ) : (
              <>
                At {value.credits_per_term} credits a term that is up to{" "}
                {pace.capacity} credits. The map will tell you whether your
                remaining work fits.
              </>
            )}
          </p>
        )}
        {/*
          A standing class the student keeps taking every term — a dance class,
          an ensemble, a language section. It is not a graduation requirement,
          so it runs until they finish and never past it. Asking here is the
          point: this was previously a hardcoded dance rule, which meant nobody
          else could protect a weekly commitment and the plan claimed a 2038
          graduation for a 2029 student.
        */}
        <fieldset className="standing-commitment">
          <legend>A class you want every semester</legend>
          <label className="check-row">
            <input
              type="checkbox"
              checked={value.recurring_commitment.enabled}
              onChange={(e) =>
                patch({
                  recurring_commitment: {
                    ...value.recurring_commitment,
                    enabled: e.target.checked,
                  },
                })
              }
            />
            <span>
              Keep room for one class every semester until I graduate — a dance
              class, an ensemble, a language section. It is not a degree
              requirement, and it stops when you finish.
            </span>
          </label>
          {value.recurring_commitment.enabled && (
            <div className="preference-grid">
              <label>
                What is it?
                <input
                  type="text"
                  maxLength={60}
                  placeholder="Dance class"
                  value={value.recurring_commitment.label}
                  onChange={(e) =>
                    patch({
                      recurring_commitment: {
                        ...value.recurring_commitment,
                        label: e.target.value,
                      },
                    })
                  }
                />
              </label>
              <label>
                Subject code
                <input
                  type="text"
                  maxLength={12}
                  placeholder="DCE"
                  value={value.recurring_commitment.code}
                  onChange={(e) =>
                    patch({
                      recurring_commitment: {
                        ...value.recurring_commitment,
                        code: e.target.value.toUpperCase(),
                      },
                    })
                  }
                />
              </label>
              <label>
                Credits each time
                <input
                  type="number"
                  min={0}
                  max={6}
                  step={0.5}
                  value={value.recurring_commitment.credits}
                  onChange={(e) =>
                    patch({
                      recurring_commitment: {
                        ...value.recurring_commitment,
                        credits: numeric(e.target.value),
                      },
                    })
                  }
                />
              </label>
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={value.recurring_commitment.include_summer}
                  onChange={(e) =>
                    patch({
                      recurring_commitment: {
                        ...value.recurring_commitment,
                        include_summer: e.target.checked,
                      },
                    })
                  }
                />
                <span>Summers too</span>
              </label>
            </div>
          )}
        </fieldset>
        {issues.length > 0 && (
          <ul className="preference-problems" role="alert">
            {issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        )}
        <p className="small">
          Adjust each semester’s ceiling on the map. A credit setting is a
          planning preference, not enrollment approval.
        </p>
        <details className="personal-rules">
          <summary>My confirmed advisor decisions</summary>
          <p className="small">
            Only select rules your advisor has confirmed apply to you. These
            never change another student’s plan.
          </p>
          {(
            [
              ["finance_sequence", "Use my confirmed Finance sequence"],
              [
                "finance_equivalence",
                "FIN 303 covers FIN 361, with a replacement FIN elective",
              ],
              [
                "dance",
                "Reserve a two-credit dance commitment each regular semester",
              ],
            ] as const
          ).map(([key, label]) => (
            <label className="check-row" key={key}>
              <input
                type="checkbox"
                checked={value.personal_rules[key]}
                onChange={(e) =>
                  patch({
                    personal_rules: {
                      ...value.personal_rules,
                      [key]: e.target.checked,
                    },
                  })
                }
              />
              {label}
            </label>
          ))}
        </details>
      </details>
    </div>
  );
}
