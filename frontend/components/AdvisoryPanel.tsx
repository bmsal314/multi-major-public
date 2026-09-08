import { useState } from "react";
import type { AdvisoryNote } from "../lib/api";

const SEVERITY_LABEL: Record<AdvisoryNote["severity"], string> = {
  applied: "Applied to your plan",
  confirm: "Confirm with an advisor",
  sequencing: "Ordering rule",
  cap: "Hour cap",
};

/**
 * Rules the major maps state that a DARS report cannot.
 *
 * These matter most where they *disagree* with DARS. A rule marked "applied" has
 * already changed what the plan schedules — the honours FIN 303 equivalence
 * removes a class the audit still lists as owed — so those lead, ahead of the
 * ones still awaiting a decision and the ordering rules the planner enforces on
 * its own.
 */
export default function AdvisoryPanel({
  advisories,
}: {
  advisories: AdvisoryNote[];
}) {
  const [open, setOpen] = useState<string | null>(
    (
      advisories.find((note) => note.severity === "applied") ??
      advisories.find((note) => note.severity === "confirm")
    )?.id ?? null,
  );

  if (advisories.length === 0) return null;

  // Applied rules lead: they have already changed what the plan schedules, so
  // they are the ones a reader most needs to know about.
  const rank = (note: AdvisoryNote) =>
    note.severity === "applied" ? 0 : note.severity === "confirm" ? 1 : 2;
  const ordered = [...advisories].sort(
    (first, second) => rank(first) - rank(second),
  );
  const applied = ordered.filter((note) => note.severity === "applied").length;
  const toConfirm = ordered.filter(
    (note) => note.severity === "confirm",
  ).length;

  return (
    <section className="content-section advisory-section" id="rules">
      <div className="section-heading">
        <div>
          <p className="eyebrow">From your major maps, not your DARS</p>
          <h2>Rules from your major maps</h2>
        </div>
        <span>
          {[
            applied > 0 ? `${applied} changed your plan` : "",
            toConfirm > 0
              ? `${toConfirm} need${toConfirm === 1 ? "s" : ""} a decision`
              : "",
          ]
            .filter(Boolean)
            .join(" · ") || "all enforced automatically"}
        </span>
      </div>
      <p className="section-intro">
        A degree audit lists what is left. It does not carry the footnotes on
        the eAdvisor major map. A rule marked <strong>applied</strong> has
        changed what this plan schedules because you confirmed it holds; your
        DARS will keep listing the requirement until an advisor records the
        substitution. Everything else is shown for you to decide, not decided
        for you.
      </p>

      <ul className="advisory-list">
        {ordered.map((note) => (
          <li key={note.id} className={`advisory advisory-${note.severity}`}>
            <button
              type="button"
              aria-expanded={open === note.id}
              onClick={() => setOpen(open === note.id ? null : note.id)}
            >
              <span className="advisory-severity">
                {SEVERITY_LABEL[note.severity]}
              </span>
              <strong>{note.title}</strong>
              <small>{note.program}</small>
              <i aria-hidden="true">{open === note.id ? "−" : "+"}</i>
            </button>
            {open === note.id && (
              <div className="advisory-body">
                <p>{note.detail}</p>
                <footer>
                  {note.courses.length > 0 && (
                    <span className="advisory-courses">
                      Affects {note.courses.join(", ")}
                    </span>
                  )}
                  <cite>Source: {note.source}</cite>
                </footer>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
