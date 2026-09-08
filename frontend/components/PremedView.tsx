import type { PremedRequirement, PremedSummary } from "../lib/api";

/** Where a course sits on the semester map, so this panel agrees with it. */
export type CoursePlacement = Record<
  string,
  { term: string; unplaced: boolean }
>;

function CourseEvidence({
  requirement,
  placement,
}: {
  requirement: PremedRequirement;
  placement: CoursePlacement;
}) {
  return (
    <div className="premed-evidence">
      {requirement.completed_courses.map((code) => (
        <span className="premed-course is-complete" key={`done:${code}`}>
          {code}
          <small>complete</small>
        </span>
      ))}
      {requirement.in_progress_courses.map((code) => (
        <span className="premed-course is-progress" key={`progress:${code}`}>
          {code}
          <small>in progress</small>
        </span>
      ))}
      {requirement.remaining_courses.map((code) => {
        // Tie the checklist to the map: "remaining" is very different from
        // "remaining and nowhere on the plan".
        const placed = placement[code];
        const label = !placed
          ? "not on the map"
          : placed.unplaced
            ? "needs a term"
            : placed.term;
        return (
          <span
            className={`premed-course ${placed && !placed.unplaced ? "is-planned" : "is-remaining"}`}
            key={`remaining:${code}`}
          >
            {code}
            <small>{label}</small>
          </span>
        );
      })}
    </div>
  );
}

export default function PremedView({
  premed,
  placement = {},
}: {
  premed: PremedSummary;
  placement?: CoursePlacement;
}) {
  const core = premed.requirements.filter(
    (requirement) => requirement.required,
  );
  const recommended = premed.requirements.filter(
    (requirement) => !requirement.required,
  );

  return (
    <section className="content-section" id="premed">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Transcript matched to current guidance</p>
          <h2>Pre-med readiness</h2>
        </div>
        <span>
          {premed.complete_count} complete · {premed.in_progress_count} underway
          · {premed.remaining_count} remaining
        </span>
      </div>
      <p className="section-intro">
        This uses the pre-health core sequence as a planning baseline.
        Medical schools set their own policies, so the checklist separates core
        preparation from useful—but non-universal—recommendations.
      </p>

      <div className="premed-summary" role="group" aria-label="Pre-med core summary">
        <div>
          <strong>{premed.complete_count}</strong>
          <span>core areas complete</span>
        </div>
        <div>
          <strong>{premed.in_progress_count}</strong>
          <span>core areas in progress</span>
        </div>
        <div className={premed.remaining_count ? "has-remaining" : ""}>
          <strong>{premed.remaining_count}</strong>
          <span>core areas still open</span>
        </div>
      </div>

      <div className="premed-grid">
        {core.map((requirement) => (
          <article
            className={`premed-card status-border-${requirement.status}`}
            key={requirement.id}
          >
            <header>
              <span className={`status-dot status-${requirement.status}`} />
              <small>{requirement.status.replace("_", " ")}</small>
            </header>
            <h3>{requirement.name}</h3>
            <p>{requirement.detail}</p>
            <CourseEvidence requirement={requirement} placement={placement} />
          </article>
        ))}
      </div>

      <details className="premed-recommended">
        <summary>
          ASU-recommended preparation beyond the core{" "}
          <span>
            {recommended.filter((item) => item.status === "complete").length}{" "}
            already completed
          </span>
        </summary>
        <div>
          <p className="premed-recommended-note">
            Recommended coursework is <strong>not</strong> scheduled on the
            semester map. It is not required by either degree or by ASU
            Pre-Health, and adding it automatically would push required work out
            of the plan. To plan one anyway, use <em>+ Add a class</em> on the
            term you want it in.
          </p>
          {recommended.map((requirement) => (
            <article key={requirement.id}>
              <span className={`status-dot status-${requirement.status}`} />
              <div>
                <strong>{requirement.name}</strong>
                <small>{requirement.note}</small>
              </div>
              <CourseEvidence requirement={requirement} placement={placement} />
            </article>
          ))}
        </div>
      </details>

      <div className="premed-sources">
        <strong>Planning sources</strong>
        {premed.sources.map((source) => (
          <a
            href={source.url}
            target="_blank"
            rel="noreferrer"
            key={source.url}
          >
            <span>{source.label} ↗</span>
            <small>{source.note}</small>
          </a>
        ))}
      </div>
    </section>
  );
}
