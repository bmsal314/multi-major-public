import { useMemo, useState } from "react";
import type { MajorAudit, RequirementStatus } from "../lib/api";
import { programColour } from "../lib/programs";

interface RequirementExplorerProps {
  audit: MajorAudit;
  /** Audit order, so this program's colour matches the map. */
  programs?: string[];
}

/**
 * Outstanding work first, then in progress, then done.
 *
 * The list was in whatever order the parser produced, which buried the only
 * rows a student can act on underneath dozens of satisfied ones.
 */
const STATUS_RANK: Record<RequirementStatus, number> = {
  remaining: 0,
  in_progress: 1,
  complete: 2,
};

/** The subject a requirement is about, for grouping: "FIN 361" -> "FIN". */
function subjectOf(name: string, options: string[]): string {
  const fromOption = options[0]?.match(/^([A-Z]{2,4})\s/);
  if (fromOption) return fromOption[1];
  const fromName = name.match(/\b([A-Z]{2,4})\s+\d{3}/);
  return fromName ? fromName[1] : "—";
}

const statusLabels: Record<RequirementStatus, string> = {
  complete: "Complete",
  in_progress: "In progress",
  remaining: "Remaining",
};

export default function RequirementExplorer({
  audit,
  programs = [],
}: RequirementExplorerProps) {
  const [status, setStatus] = useState<RequirementStatus | "all">("remaining");
  const [query, setQuery] = useState("");
  const requirements = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return audit.requirements
      .filter(
        (requirement) =>
          (status === "all" || requirement.status === status) &&
          (!needle ||
            requirement.name.toLowerCase().includes(needle) ||
            requirement.section.toLowerCase().includes(needle) ||
            requirement.course_options.some((course) =>
              course.toLowerCase().includes(needle),
            )),
      )
      // What is still owed, then by section, then by subject — so a reader
      // scanning for "what do I still need in FIN" finds it together.
      .sort(
        (a, b) =>
          STATUS_RANK[a.status] - STATUS_RANK[b.status] ||
          a.section.localeCompare(b.section) ||
          subjectOf(a.name, a.course_options).localeCompare(
            subjectOf(b.name, b.course_options),
          ) ||
          a.name.localeCompare(b.name),
      );
  }, [audit.requirements, query, status]);

  return (
    <section className="content-section" id="requirements">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Parsed line by line</p>
          <h2>
            <span
              className="program-dot"
              style={{ background: programColour(programs, audit.name) }}
              aria-hidden="true"
            />
            {audit.name} requirements
          </h2>
        </div>
        <span>{requirements.length} shown</span>
      </div>
      <div className="requirement-toolbar">
        <div
          className="segmented-control"
          role="group"
          aria-label="Filter requirements by status"
        >
          {(["remaining", "in_progress", "complete", "all"] as const).map(
            (value) => (
              <button
                type="button"
                className={status === value ? "is-active" : ""}
                onClick={() => setStatus(value)}
                key={value}
              >
                {value === "all" ? "All" : statusLabels[value]}
              </button>
            ),
          )}
        </div>
        <label className="search-field">
          <span className="sr-only">Search requirements</span>
          <input
            type="search"
            placeholder="Search requirement or course"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </div>

      <div className="requirement-list">
        {requirements.map((requirement) => (
          <details
            className={`requirement-row${requirement.satisfied_by ? " is-equivalent" : ""}`}
            key={requirement.id}
          >
            <summary>
              <span
                className={`status-dot status-${requirement.status}`}
                aria-hidden="true"
              />
              <span className="requirement-main">
                <small>{requirement.section}</small>
                <strong>{requirement.name}</strong>
                <span className="course-pills">
                  {requirement.satisfied_by && (
                    <i className="equivalence-pill">
                      covered by an equivalence
                    </i>
                  )}
                  {requirement.course_options.slice(0, 5).map((course) => (
                    <i key={course}>{course}</i>
                  ))}
                  {requirement.criteria.map((criterion) => (
                    <i className="criterion-pill" key={criterion}>
                      {criterion}
                    </i>
                  ))}
                  {requirement.course_options.length > 5 && (
                    <i>+{requirement.course_options.length - 5} options</i>
                  )}
                </span>
              </span>
              <span className="requirement-hours">
                <strong>
                  {requirement.status === "complete"
                    ? requirement.credits_earned
                    : requirement.credits_remaining}
                </strong>
                <small>
                  {requirement.status === "complete"
                    ? "earned"
                    : "credits left"}
                </small>
              </span>
              <span className="disclosure" aria-hidden="true">
                ⌄
              </span>
            </summary>
            <div className="requirement-detail">
              <div>
                <span>Status</span>
                <strong>{statusLabels[requirement.status]}</strong>
              </div>
              <div>
                <span>Parser confidence</span>
                <strong>{Math.round(requirement.confidence * 100)}%</strong>
              </div>
              {requirement.satisfied_by && (
                <div className="source-evidence is-equivalence">
                  <span>Covered without scheduling it</span>
                  <p>
                    {requirement.satisfied_by}. DARS still lists this as
                    remaining and will until an advisor records the
                    substitution.
                  </p>
                </div>
              )}
              <div className="source-evidence">
                <span>DARS evidence</span>
                <p>{requirement.source_text}</p>
                <p>
                  Source pages:{" "}
                  {requirement.source_pages.length
                    ? requirement.source_pages.join(", ")
                    : "not identified"}
                  {requirement.minimum_grade
                    ? ` · Minimum grade ${requirement.minimum_grade}`
                    : ""}
                </p>
                {requirement.needs_review && (
                  <strong>Interpretation requires review.</strong>
                )}
              </div>
            </div>
          </details>
        ))}
        {!requirements.length && (
          <div className="empty-state">
            <strong>No matching requirements.</strong>
            <span>Try another status or clear the search.</span>
          </div>
        )}
      </div>
    </section>
  );
}
