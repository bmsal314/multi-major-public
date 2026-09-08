import type { AdvisoryNote, PlannedCourse, SemesterPlan } from "../lib/api";
import { academicYear } from "../lib/terms";

interface PrintablePlanProps {
  semesters: SemesterPlan[];
  graduationTerm: string;
  minCredits: number;
  advisories: AdvisoryNote[];
  programs: string[];
}

/**
 * The plan as a document someone else can read.
 *
 * This is hidden on screen and revealed by the print stylesheet, so "Print /
 * save PDF" produces a page that mirrors whatever the student has actually
 * arranged — not a separate export that can drift from the live map. Every
 * class carries the reason it is scheduled, because the audience for a printed
 * plan is an advisor or a parent asking exactly that.
 */
export default function PrintablePlan({
  semesters,
  graduationTerm,
  minCredits,
  advisories,
  programs,
}: PrintablePlanProps) {
  const tint = (course: PlannedCourse): string => {
    if (course.majors.length > 1) return "shared";
    const index = programs.indexOf(course.majors[0]);
    if (index >= 0) return `program-${index % 4}`;
    if (course.status === "premed") return "premed";
    if (course.status === "personal") return "personal";
    return "other";
  };

  const scheduled = semesters.filter(
    (semester) => semester.courses.length > 0 && !semester.is_unplaced,
  );
  const waiting =
    semesters.find((semester) => semester.is_unplaced)?.courses ?? [];
  const totalCredits = scheduled
    .flatMap((semester) => semester.courses)
    .filter((course) => course.status !== "in_progress")
    .reduce((total, course) => total + course.credits, 0);
  const generated = new Date().toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <section className="printable-plan" aria-hidden="true">
      <header className="print-header">
        <div>
          <p className="print-eyebrow">Degree plan · draft for advising</p>
          <h1>Path to {graduationTerm}</h1>
          <p className="print-subtitle">
            {programs.join(" · ")} —{" "}
            {totalCredits.toFixed(2).replace(/\.?0+$/, "")} future credits
            across {scheduled.length} terms, no term under {minCredits} credits
            {waiting.length > 0 ? `, ${waiting.length} still to place` : ""}.
          </p>
        </div>
        <p className="print-generated">Generated {generated}</p>
      </header>

      <ul className="print-legend">
        {programs.map((program, index) => (
          <li key={program}>
            <i className={`tint-program-${index % 4}`} />
            {program}
          </li>
        ))}
        <li>
          <i className="tint-shared" />
          Counts for more than one program
        </li>
        <li>
          <i className="tint-premed" />
          Pre-med prerequisite
        </li>
        <li>
          <i className="tint-personal" />
          Personal commitment
        </li>
      </ul>

      {scheduled.map((semester) => (
        <section className="print-term" key={semester.term}>
          <header>
            <h2>
              {semester.term}
              <small>{academicYear(semester.term)}</small>
            </h2>
            <p>
              {semester.total_credits.toFixed(2).replace(/\.?0+$/, "")} credits
              {semester.is_in_progress ? " · already registered" : ""}
              {semester.is_mcat_term
                ? ` · MCAT term, held at ${semester.credit_limit}`
                : ""}
            </p>
          </header>
          <table>
            <thead>
              <tr>
                <th scope="col">Class</th>
                <th scope="col">Cr</th>
                <th scope="col">Counts toward</th>
                <th scope="col">Why this class, this term</th>
              </tr>
            </thead>
            <tbody>
              {semester.courses.map((course) => (
                <tr key={course.id} className={`tint-${tint(course)}`}>
                  <th scope="row">
                    {course.subject
                      ? `${course.subject} ${course.catalog_number}`
                      : course.label}
                    {course.is_placeholder && course.status !== "personal" ? (
                      <em> — not chosen yet</em>
                    ) : null}
                  </th>
                  <td>{course.credits.toFixed(2).replace(/\.?0+$/, "")}</td>
                  <td>{course.majors.join(" + ")}</td>
                  <td>
                    {course.justification}
                    {course.sequenced_by ? (
                      <span className="print-source">
                        {" "}
                        Sequenced by: {course.sequenced_by}.
                      </span>
                    ) : null}
                    {course.prerequisites.length > 0 ? (
                      <span className="print-source">
                        {" "}
                        Must follow {course.prerequisites.join(" or ")}.
                      </span>
                    ) : null}
                    {course.note ? (
                      <span className="print-source"> {course.note}</span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}

      {waiting.length > 0 && (
        <section className="print-term print-waiting">
          <header>
            <h2>
              Still to place<small>no term yet</small>
            </h2>
            <p>
              {waiting
                .reduce((total, course) => total + course.credits, 0)
                .toFixed(2)
                .replace(/\.?0+$/, "")}{" "}
              credits
            </p>
          </header>
          <table>
            <thead>
              <tr>
                <th scope="col">Class</th>
                <th scope="col">Cr</th>
                <th scope="col">Counts toward</th>
                <th scope="col">Why this class</th>
              </tr>
            </thead>
            <tbody>
              {waiting.map((course) => (
                <tr key={course.id} className={`tint-${tint(course)}`}>
                  <th scope="row">
                    {course.subject
                      ? `${course.subject} ${course.catalog_number}`
                      : course.label}
                  </th>
                  <td>{course.credits.toFixed(2).replace(/\.?0+$/, "")}</td>
                  <td>{course.majors.join(" + ")}</td>
                  <td>{course.justification}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="print-waiting-note">
            These do not fit the current per-term credit ceilings before{" "}
            {graduationTerm}. Raising a ceiling, adding summer terms, or moving
            graduation later are the ways to absorb them.
          </p>
        </section>
      )}

      {advisories.length > 0 && (
        <section className="print-advisories">
          <h2>Rules to confirm with an advisor</h2>
          <ol>
            {advisories.map((note) => (
              <li key={note.id}>
                <strong>{note.title}</strong>
                <p>{note.detail}</p>
                <small>
                  {note.program} · source: {note.source}
                </small>
              </li>
            ))}
          </ol>
        </section>
      )}

      <footer className="print-footer">
        This is a planning draft produced from degree audits on a personal
        computer. DARS and an academic advisor remain the authoritative record
        for degree completion.
      </footer>
    </section>
  );
}
