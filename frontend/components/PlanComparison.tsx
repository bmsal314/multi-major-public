import { useMemo } from "react";
import type { AnalysisResponse, PlanSummary } from "../lib/api";
import type { SavedPlan } from "../lib/cloud";

/** One row of the metadata table: what each permutation decided. */
const METRICS: {
  label: string;
  read: (s: PlanSummary) => string;
  /** Lower is better, higher is better, or neither. */
  better?: "low" | "high";
  value?: (s: PlanSummary) => number;
}[] = [
  { label: "Graduates", read: (s) => s.graduation_term || "—" },
  { label: "Semesters", read: (s) => String(s.term_count), value: (s) => s.term_count, better: "low" },
  { label: "Credits planned", read: (s) => s.planned_credits.toFixed(1) },
  { label: "Heaviest term", read: (s) => `${s.heaviest_term_credits} cr`, value: (s) => s.heaviest_term_credits, better: "low" },
  { label: "Lightest term", read: (s) => `${s.lightest_term_credits} cr`, value: (s) => s.lightest_term_credits, better: "high" },
  { label: "Classes", read: (s) => String(s.course_count) },
  { label: "Slots still to choose", read: (s) => String(s.placeholder_count), value: (s) => s.placeholder_count, better: "low" },
  { label: "Not yet placed", read: (s) => String(s.unplaced_count), value: (s) => s.unplaced_count, better: "low" },
  { label: "Unresolved checks", read: (s) => String(s.gap_count), value: (s) => s.gap_count, better: "low" },
  { label: "Credit ceiling", read: (s) => `${s.credits_per_term} cr` },
  { label: "Pre-med", read: (s) => (s.premed ? "Yes" : "No") },
  {
    label: "MCAT semester",
    read: (s) =>
      s.mcat_terms.length
        ? `${s.mcat_terms[0]} · ${s.mcat_course_ceiling} classes / ${s.mcat_credit_ceiling} cr`
        : "—",
  },
  { label: "Summer terms", read: (s) => (s.include_summer ? "Included" : "Not used") },
];

function placement(result: AnalysisResponse) {
  const where: Record<string, string> = {};
  result.plan.semesters.forEach((semester) =>
    semester.courses.forEach((course) => {
      where[course.code] = semester.is_unplaced ? "Not yet placed" : semester.term;
    }),
  );
  return where;
}

export default function PlanComparison({
  left,
  right,
  leftResult,
  rightResult,
  onClose,
}: {
  left: SavedPlan;
  right: SavedPlan;
  leftResult: AnalysisResponse | null;
  rightResult: AnalysisResponse | null;
  onClose: () => void;
}) {
  // Course-level differences need the full results, which are fetched only when
  // a comparison is actually opened.
  const moves = useMemo(() => {
    if (!leftResult || !rightResult) return [];
    const a = placement(leftResult);
    const b = placement(rightResult);
    return [...new Set([...Object.keys(a), ...Object.keys(b)])]
      .filter((code) => a[code] !== b[code])
      .sort()
      .map((code) => ({ code, from: a[code] ?? "Not in this plan", to: b[code] ?? "Not in this plan" }));
  }, [leftResult, rightResult]);

  return (
    <section className="plan-comparison" aria-label="Compare two semester maps">
      <header>
        <h2>
          {left.name} <span aria-hidden="true">vs</span> {right.name}
        </h2>
        <button className="button button-secondary" onClick={onClose}>
          Close comparison
        </button>
      </header>

      <table className="comparison-table">
        <caption className="small">
          Decision metadata for each permutation. A highlighted cell is the
          better of the two on that measure; measures with no better answer are
          left plain.
        </caption>
        <thead>
          <tr>
            <th scope="col">Measure</th>
            <th scope="col">{left.name}</th>
            <th scope="col">{right.name}</th>
          </tr>
        </thead>
        <tbody>
          {METRICS.map((metric) => {
            const l = metric.read(left.summary);
            const r = metric.read(right.summary);
            let leftWins = false;
            let rightWins = false;
            if (metric.value && metric.better) {
              const lv = metric.value(left.summary);
              const rv = metric.value(right.summary);
              if (lv !== rv) {
                leftWins = metric.better === "low" ? lv < rv : lv > rv;
                rightWins = !leftWins;
              }
            }
            return (
              <tr key={metric.label} className={l === r ? "" : "differs"}>
                <th scope="row">{metric.label}</th>
                <td className={leftWins ? "better" : ""}>{l}</td>
                <td className={rightWins ? "better" : ""}>{r}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h3>Where courses moved</h3>
      {!leftResult || !rightResult ? (
        <p role="status">Loading both maps…</p>
      ) : moves.length === 0 ? (
        <p className="empty-state">
          <strong>Every course sits in the same semester.</strong>
          <span>These permutations differ only in their settings.</span>
        </p>
      ) : (
        <table className="comparison-table">
          <thead>
            <tr>
              <th scope="col">Course</th>
              <th scope="col">{left.name}</th>
              <th scope="col">{right.name}</th>
            </tr>
          </thead>
          <tbody>
            {moves.map((move) => (
              <tr key={move.code} className="differs">
                <th scope="row">{move.code}</th>
                <td>{move.from}</td>
                <td>{move.to}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
