/**
 * One colour per program, meaning the same thing everywhere.
 *
 * The semester map already tinted courses by program. Every other panel —
 * the transcript snapshot, the planning checks, the requirement list — showed
 * the same programs in plain text, so a reader had to re-orient at each
 * section. The mapping lives here so a colour identifies a program on screen
 * and on the printed plan alike.
 *
 * The palette carries four programs. Beyond that colours repeat, which is a
 * deliberate limit: more than four simultaneous hues stop being a legend and
 * start being decoration.
 */

export const PROGRAM_COLOURS = ["#8c1d40", "#26766f", "#3d5a99", "#8a6d1f"];

/** Stable index for a program, or -1 when it is not one of the audits. */
export function programIndex(programs: string[], name: string): number {
  const index = programs.indexOf(name);
  return index >= 0 ? index % PROGRAM_COLOURS.length : -1;
}

/** The tint class for a program: `tint-program-2`, or "" when unknown. */
export function programClass(programs: string[], name: string): string {
  const index = programIndex(programs, name);
  return index >= 0 ? `tint-program-${index}` : "";
}

/** The literal colour, for a swatch or an inline style. */
export function programColour(programs: string[], name: string): string {
  const index = programIndex(programs, name);
  return index >= 0 ? PROGRAM_COLOURS[index] : "var(--muted, #6b6459)";
}

/**
 * How much a planning check matters, most severe first.
 *
 * A student scanning this needs the things that stop them graduating above the
 * things they merely have to confirm — the previous order was whatever the
 * checks happened to be generated in.
 */
export const CHECK_ORDER: Record<string, number> = { gap: 0, note: 1, pass: 2 };

export function bySeverity<T extends { status: string }>(a: T, b: T): number {
  return (CHECK_ORDER[a.status] ?? 9) - (CHECK_ORDER[b.status] ?? 9);
}

/**
 * The program a check belongs to, read from its label.
 *
 * Checks are generated as "Finance: every remaining requirement is scheduled",
 * so the program is the part before the colon. Returns "" for the checks that
 * apply to the whole plan.
 */
export function checkProgram(programs: string[], label: string): string {
  const head = label.split(":")[0]?.trim() ?? "";
  return programs.includes(head) ? head : "";
}
