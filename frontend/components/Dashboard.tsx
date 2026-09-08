import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import type {
  AnalysisResponse,
  PlanState,
  PlanResult,
  SemesterPlan,
} from "../lib/api";
import AdvisoryPanel from "./AdvisoryPanel";
import CreditProgress from "./CreditProgress";
import PlanView from "./PlanView";
import ReadinessPanel from "./ReadinessPanel";
import PremedView from "./PremedView";
import ProgressRail from "./ProgressRail";
import { programColour } from "../lib/programs";
import RequirementExplorer from "./RequirementExplorer";

interface DashboardProps {
  result: AnalysisResponse;
  editorPlan?: PlanResult;
  initialState?: PlanState;
  onReset: () => void;
  /** Persist the whole editable semester map. */
  onSavePlan?: (state: PlanState) => Promise<void> | void;
  /** Why saving is unavailable, when it is. */
  unsavedHint?: string;
  /** Rendered after the results and before the closing disclaimer. */
  children?: ReactNode;
}

export default function Dashboard({
  result,
  editorPlan,
  initialState,
  onReset,
  onSavePlan,
  unsavedHint = "",
  children,
}: DashboardProps) {
  const [activeMajor, setActiveMajor] = useState(result.audits[0]?.name ?? "");
  const activeAudit = useMemo(
    () =>
      result.audits.find((audit) => audit.name === activeMajor) ??
      result.audits[0],
    [activeMajor, result.audits],
  );
  // Earned hours, in-progress hours, and GPA are transcript-wide, so they are
  // the same in every audit.  Taking the maximum avoids depending on audit
  // order and on which program happens to be selected.
  const transcript = useMemo(
    () => ({
      earned: result.audits.reduce<number | null>(
        (best, audit) =>
          audit.summary.earned_hours === null
            ? best
            : Math.max(best ?? 0, audit.summary.earned_hours),
        null,
      ),
      inProgress: Math.max(
        0,
        ...result.audits.map((audit) => audit.summary.in_progress_hours),
      ),
      gpa: result.audits.reduce<number | null>(
        (best, audit) =>
          audit.summary.gpa === null
            ? best
            : Math.max(best ?? 0, audit.summary.gpa),
        null,
      ),
    }),
    [result.audits],
  );

  const parserWarnings = useMemo(
    () => [
      ...new Set([
        ...result.warnings,
        ...result.audits.flatMap((audit) => audit.warnings),
      ]),
    ],
    [result.audits, result.warnings],
  );

  const allRequirements = useMemo(
    () => result.audits.flatMap((audit) => audit.requirements),
    [result.audits],
  );

  // A stable program order keeps a colour meaning the same program everywhere,
  // on screen and on the printed plan.
  const programs = useMemo(
    () => result.audits.map((audit) => audit.name),
    [result.audits],
  );

  // Where every course sits on the map, so the pre-med checklist and the map
  // cannot tell the reader two different things. It has to read the plan the
  // editor is actually showing: after a move, the freshly parsed plan still has
  // the course in its original term.
  const shownPlan = editorPlan ?? result.plan;
  const [liveSemesters, setLiveSemesters] = useState<SemesterPlan[] | null>(
    null,
  );
  const placement = useMemo(() => {
    const index: Record<string, { term: string; unplaced: boolean }> = {};
    (liveSemesters ?? shownPlan.semesters).forEach((semester) => {
      semester.courses.forEach((course) => {
        if (course.code) {
          index[course.code] = {
            term: semester.term,
            unplaced: semester.is_unplaced,
          };
        }
      });
    });
    return index;
  }, [liveSemesters, shownPlan.semesters]);

  return (
    <div className="results-shell">
      <header className="results-header">
        <div>
          <p className="eyebrow">
            Analysis complete in {(result.processing_ms / 1000).toFixed(2)}{" "}
            seconds
          </p>
          <h1>Your degrees, on one map.</h1>
          <p>
            {result.audits.length} programs · {result.completed_courses.length}{" "}
            completed courses · {result.in_progress_courses.length} in progress
          </p>
        </div>
        <div className="results-actions">
          <button
            className="button button-secondary"
            type="button"
            onClick={onReset}
          >
            Back to my plans
          </button>
        </div>
      </header>

      <nav className="section-nav" aria-label="Analysis sections">
        <a href="#plan">Semester map</a>
        <a href="#readiness">Planning checks</a>
        <a href="#credits">Credits</a>
        {result.advisories.length > 0 ? <a href="#rules">Rules</a> : null}
        <a href="#opportunities">Overlaps</a>
        <a href="#requirements">Requirements</a>
        {result.premed.requirements.length > 0 && <a href="#premed">Pre-med</a>}
      </nav>

      <p className="draft-map-notice">
        Planning draft · {result.readiness.gap_count} unresolved checks ·{" "}
        {result.readiness.note_count} items to confirm.{" "}
        <a href="#readiness">Review the evidence before registration.</a>
      </p>
      <PlanView
        plan={editorPlan ?? result.plan}
        requirements={allRequirements}
        advisories={result.advisories}
        programs={programs}
        initialState={initialState}
        onSave={onSavePlan}
        unsavedHint={unsavedHint}
        onLayoutChange={setLiveSemesters}
      />

      {children}

      <ReadinessPanel readiness={result.readiness} programs={programs} />
      <section className="snapshot-grid" aria-label="Degree audit snapshot">
        <div className="snapshot-primary">
          <small>Transcript snapshot</small>
          <strong>{transcript.earned?.toFixed(2) ?? "—"}</strong>
          <span>earned hours</span>
        </div>
        <div>
          <small>Current work</small>
          <strong>{transcript.inProgress.toFixed(0)}</strong>
          <span>hours in progress</span>
        </div>
        <div>
          <small>ASU GPA</small>
          <strong>{transcript.gpa?.toFixed(2) ?? "—"}</strong>
          <span>reported by DARS</span>
        </div>
        <div>
          <small>Shared openings</small>
          <strong>{result.overlaps.length}</strong>
          <span>conservative matches</span>
        </div>
        {/* The programs this snapshot covers, in the colours used on the map. */}
        <ul className="snapshot-programs" aria-label="Programs in this plan">
          {programs.map((name) => (
            <li key={name}>
              <span
                className="program-dot"
                style={{ background: programColour(programs, name) }}
                aria-hidden="true"
              />
              {name}
            </li>
          ))}
        </ul>
      </section>

      <ProgressRail
        audits={result.audits}
        activeMajor={activeMajor}
        onSelect={setActiveMajor}
      />

      <CreditProgress result={result} />

      <AdvisoryPanel advisories={result.advisories} />

      {parserWarnings.length > 0 && (
        <details className="interpretation-notes">
          <summary>
            <strong>How your audits were read</strong>
            <span>
              {parserWarnings.length} note
              {parserWarnings.length === 1 ? "" : "s"}
            </span>
          </summary>
          <p className="small">
            Rules this planner applied while reading your DARS — substitutions,
            reserved credit, wording it could not resolve on its own. They are
            recorded so you can check the reasoning, not because something went
            wrong.
          </p>
          <ul>
            {parserWarnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </details>
      )}

      <section className="content-section" id="opportunities">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Double-count carefully</p>
            <h2>Overlap opportunities</h2>
          </div>
          <span>{result.overlaps.length} evidence-backed</span>
        </div>
        {result.overlaps.length ? (
          <div className="overlap-grid">
            {result.overlaps.map((overlap) => (
              <article
                key={`${overlap.course_code}:${overlap.majors.join(":")}`}
              >
                <span className="overlap-code">{overlap.course_code}</span>
                <h3>{overlap.majors.join(" + ")}</h3>
                <p>{overlap.reason}</p>
                <footer>
                  <span>Potential</span>
                  <strong>{overlap.potential_credits} shared credits</strong>
                </footer>
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <strong>No explicit overlap found.</strong>
            <span>
              The parser avoids inventing a match when DARS does not provide
              one.
            </span>
          </div>
        )}

      </section>

      {activeAudit && (
        <RequirementExplorer audit={activeAudit} programs={programs} />
      )}
      {result.premed.requirements.length > 0 && (
        <PremedView premed={result.premed} placement={placement} />
      )}

      <footer className="results-footer">
        <span>Multi-Major</span>
        <p>
          Planning aid only. DARS and your academic advisor remain
          authoritative.
        </p>
      </footer>
    </div>
  );
}
