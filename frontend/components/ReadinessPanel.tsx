import { useState } from "react";
import { GraduationReadiness, CheckStatus } from "../lib/api";
import { checkProgram, programClass, programColour } from "../lib/programs";

const STATUS_COPY: Record<
  GraduationReadiness["status"],
  { headline: string; lede: string; tone: string }
> = {
  on_track: {
    headline: "Draft checks completed",
    lede: "No gap was found among interpreted requirements. Advisor review is still required.",
    tone: "readiness-ok",
  },
  on_track_with_notes: {
    headline: "Draft needs review",
    lede: "No known scheduling gap was found in interpreted requirements. This does not confirm graduation eligibility.",
    tone: "readiness-note",
  },
  blocked: {
    headline: "Unresolved requirements",
    lede: "Review unmet or uninterpreted conditions before relying on this map.",
    tone: "readiness-gap",
  },
};

const GROUP_ORDER: CheckStatus[] = ["gap", "note", "pass"];

const GROUP_LABEL: Record<CheckStatus, string> = {
  gap: "Blocking",
  note: "Confirm",
  pass: "Clear",
};

const MARKER: Record<CheckStatus, string> = {
  gap: "!",
  note: "?",
  pass: "✓",
};

/** Beyond this, a check's evidence list stops informing and starts burying. */
const EVIDENCE_PREVIEW = 6;

export default function ReadinessPanel({
  readiness,
  programs = [],
}: {
  readiness: GraduationReadiness;
  /** In audit order, so a colour means the same program as on the map. */
  programs?: string[];
}) {
  // Cleared rules collapse by default; the point of the panel is what still needs work.
  const [showCleared, setShowCleared] = useState(false);
  const copy = STATUS_COPY[readiness.status];

  return (
    <section className="readiness" id="readiness" aria-label="Planning checks">
      <header className={`readiness-head ${copy.tone}`}>
        <div>
          <p className="eyebrow">Planning checks</p>
          <h2>
            {copy.headline}
            {readiness.graduation_term ? (
              <em> · {readiness.graduation_term}</em>
            ) : null}
          </h2>
          <p className="readiness-lede">{copy.lede}</p>
        </div>
        <ul className="readiness-tally">
          <li className="tally-gap">
            <strong>{readiness.gap_count}</strong>
            <span>blocking</span>
          </li>
          <li className="tally-note">
            <strong>{readiness.note_count}</strong>
            <span>to confirm</span>
          </li>
          <li className="tally-pass">
            <strong>{readiness.pass_count}</strong>
            <span>clear</span>
          </li>
        </ul>
      </header>

      {GROUP_ORDER.map((status) => {
        const checks = readiness.checks.filter(
          (check) => check.status === status,
        );
        if (checks.length === 0) return null;
        if (status === "pass" && !showCleared) {
          return (
            <p className="readiness-cleared" key={status}>
              <button
                type="button"
                className="button-text"
                onClick={() => setShowCleared(true)}
              >
                Show {checks.length} cleared rule
                {checks.length === 1 ? "" : "s"}
              </button>
            </p>
          );
        }
        return (
          <div
            className={`readiness-group readiness-group-${status}`}
            key={status}
          >
            <h3>
              {GROUP_LABEL[status]}
              <span>{checks.length}</span>
              {status === "pass" ? (
                <button
                  type="button"
                  className="button-text"
                  onClick={() => setShowCleared(false)}
                >
                  Hide
                </button>
              ) : null}
            </h3>
            <ul>
              {checks.map((check) => {
                // A check that names a program is tinted like that program, so
                // a reader can tell at a glance whose requirement is at issue.
                const owner = checkProgram(programs, check.label);
                return (
                  <li
                    key={check.id}
                    className={owner ? programClass(programs, owner) : ""}
                  >
                    <span
                      className={`readiness-marker marker-${status}`}
                      aria-hidden="true"
                    >
                      {MARKER[status]}
                    </span>
                    <div>
                      <strong>
                        {owner ? (
                          <span
                            className="program-dot"
                            style={{ background: programColour(programs, owner) }}
                            aria-hidden="true"
                          />
                        ) : null}
                        {check.label}
                      </strong>
                      {status === "pass" ? null : <p>{check.detail}</p>}
                      {check.evidence.length > 0 && status !== "pass" ? (
                        <>
                          <ul className="readiness-evidence">
                            {check.evidence
                              .slice(0, EVIDENCE_PREVIEW)
                              .map((item) => (
                                <li key={item}>{item}</li>
                              ))}
                          </ul>
                          {check.evidence.length > EVIDENCE_PREVIEW ? (
                            <details className="readiness-more">
                              <summary>
                                {check.evidence.length - EVIDENCE_PREVIEW} more
                              </summary>
                              <ul className="readiness-evidence">
                                {check.evidence
                                  .slice(EVIDENCE_PREVIEW)
                                  .map((item) => (
                                    <li key={item}>{item}</li>
                                  ))}
                              </ul>
                            </details>
                          ) : null}
                        </>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </section>
  );
}
