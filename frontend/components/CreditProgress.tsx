import { AnalysisResponse, Requirement } from "../lib/api";

interface Track {
  key: string;
  label: string;
  /** Every program that states this same check. Shared checks are shown once. */
  programs: string[];
  required: number;
  earned: number;
  inProgress: number;
}

/**
 * Hour minimums come from the audits themselves, not hardcoded ASU policy.
 *
 * Two programs can state the same degree-wide check — both a Finance and a
 * Neuroscience audit carry "TOTAL HOURS: 120 hours minimum". That is one bar to
 * clear, not two, so it is shown once. Crediting it to whichever audit happened
 * to be parsed first would make a program silently vanish from this panel, so a
 * shared check names every program it belongs to.
 */
function hourTracks(result: AnalysisResponse): Track[] {
  const byCheck = new Map<string, Track>();

  result.audits.forEach((audit) => {
    audit.requirements.forEach((requirement: Requirement) => {
      if (requirement.kind !== "milestone" && requirement.kind !== "elective")
        return;
      if (requirement.credits_required <= 0) return;
      // Only degree-wide hour checks belong here, not individual electives.
      if (
        !/hours?\s+(?:minimum|required)|hour check|honors credits/i.test(
          `${requirement.name} ${requirement.section}`,
        )
      ) {
        return;
      }
      const key = `${requirement.name.toLowerCase()}|${requirement.credits_required}`;
      const existing = byCheck.get(key);
      if (existing) {
        if (!existing.programs.includes(audit.name))
          existing.programs.push(audit.name);
        // Keep the most advanced reading; the underlying transcript is shared.
        existing.earned = Math.max(existing.earned, requirement.credits_earned);
        existing.inProgress = Math.max(
          existing.inProgress,
          requirement.credits_in_progress,
        );
        return;
      }
      byCheck.set(key, {
        key: `${audit.name}-${requirement.id}`,
        label: requirement.name.replace(/:\s*$/, ""),
        programs: [audit.name],
        required: requirement.credits_required,
        earned: requirement.credits_earned,
        inProgress: requirement.credits_in_progress,
      });
    });
  });

  return [...byCheck.values()].sort((a, b) => b.required - a.required);
}

function Meter({ track, planned }: { track: Track; planned: number }) {
  const secured = track.earned + track.inProgress;
  const shortfall = Math.max(0, track.required - secured);
  // Planned credits can only close the gap up to what is actually left.
  const covered = Math.min(shortfall, planned);
  const pct = (value: number) =>
    `${Math.min(100, (value / track.required) * 100)}%`;
  const met = shortfall <= 0;

  return (
    <li className={met ? "credit-track met" : "credit-track"}>
      <div className="credit-track-head">
        <strong>{track.label}</strong>
        <small>
          {track.programs.join(" · ")}
          {track.programs.length > 1 ? " (one shared check)" : ""}
        </small>
      </div>
      <div
        className="credit-bar"
        role="img"
        aria-label={`${secured} of ${track.required} hours secured`}
      >
        <i className="bar-earned" style={{ width: pct(track.earned) }} />
        <i className="bar-progress" style={{ width: pct(track.inProgress) }} />
        {!met ? (
          <i className="bar-planned" style={{ width: pct(covered) }} />
        ) : null}
      </div>
      <div className="credit-track-foot">
        <span>
          <b>{secured.toFixed(2).replace(/\.00$/, "")}</b> of {track.required}{" "}
          hours
        </span>
        {met ? (
          <span className="credit-met">met</span>
        ) : (
          <span className="credit-short">
            {shortfall.toFixed(2).replace(/\.00$/, "")} to go
          </span>
        )}
      </div>
    </li>
  );
}

export default function CreditProgress({
  result,
}: {
  result: AnalysisResponse;
}) {
  const tracks = hourTracks(result);
  const planned = result.plan.planned_credits;

  // Earned/in-progress hours are transcript-wide, so any audit reports the same
  // figures; take the highest to be safe rather than trusting audit order.
  const earned = Math.max(
    0,
    ...result.audits.map((audit) => audit.summary.earned_hours ?? 0),
  );
  const inProgress = Math.max(
    0,
    ...result.audits.map((audit) => audit.summary.in_progress_hours),
  );
  const projected = earned + inProgress + planned;

  return (
    <section
      className="credit-progress"
      id="credits"
      aria-label="Credits toward graduation"
    >
      <header>
        <div>
          <p className="eyebrow">Credits toward graduation</p>
          <h2>
            {projected.toFixed(2).replace(/\.00$/, "")} projected hours by{" "}
            <em>{result.plan.graduation_term}</em>
          </h2>
        </div>
        <ul className="credit-legend">
          <li>
            <i className="bar-earned" /> earned{" "}
            {earned.toFixed(2).replace(/\.00$/, "")}
          </li>
          <li>
            <i className="bar-progress" /> in progress{" "}
            {inProgress.toFixed(2).replace(/\.00$/, "")}
          </li>
          <li>
            <i className="bar-planned" /> planned{" "}
            {planned.toFixed(2).replace(/\.00$/, "")}
          </li>
        </ul>
      </header>

      {tracks.length > 0 ? (
        <ul className="credit-tracks">
          {tracks.map((track) => (
            <Meter key={track.key} track={track} planned={planned} />
          ))}
        </ul>
      ) : (
        <p className="muted">
          No degree-wide hour minimums were found in these audits.
        </p>
      )}
    </section>
  );
}
