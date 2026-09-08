import type { MajorAudit } from "../lib/api";

interface ProgressRailProps {
  audits: MajorAudit[];
  activeMajor: string;
  onSelect: (major: string) => void;
}

export default function ProgressRail({
  audits,
  activeMajor,
  onSelect,
}: ProgressRailProps) {
  return (
    <div className="progress-rail" role="group" aria-label="Program progress">
      {audits.map((audit, index) => {
        const { summary } = audit;
        const total =
          summary.complete_requirements +
          summary.in_progress_requirements +
          summary.remaining_requirements;
        const complete = total
          ? (summary.complete_requirements / total) * 100
          : 0;
        const inProgress = total
          ? (summary.in_progress_requirements / total) * 100
          : 0;
        return (
          <button
            type="button"
            className={activeMajor === audit.name ? "is-active" : ""}
            onClick={() => onSelect(audit.name)}
            key={audit.name}
          >
            <span className="rail-index">
              {String(index + 1).padStart(2, "0")}
            </span>
            <span className="rail-program">
              <strong>{audit.name}</strong>
              <small>
                {summary.remaining_requirements} requirement
                {summary.remaining_requirements === 1 ? "" : "s"} left ·{" "}
                {summary.remaining_specific_credits.toFixed(1)} mapped credits
              </small>
            </span>
            <span className="rail-meter" aria-hidden="true">
              <i className="meter-complete" style={{ width: `${complete}%` }} />
              <i
                className="meter-progress"
                style={{ left: `${complete}%`, width: `${inProgress}%` }}
              />
            </span>
            <span className="rail-percent">
              {Math.round(complete + inProgress * 0.5)}%
            </span>
          </button>
        );
      })}
    </div>
  );
}
