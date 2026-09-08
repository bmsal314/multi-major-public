/** Every term the planner can address, oldest first. */
export const TERM_OPTIONS = Array.from(
  { length: 13 },
  (_, offset) => new Date().getFullYear() - 1 + offset,
).flatMap((year) =>
  ["Spring", "Summer", "Fall"].map((season) => `${season} ${year}`),
);

/**
 * No universal credit floor. Each student chooses their own minimum.
 */
export const MIN_TERM_CREDITS = 0;
export const MAX_TERM_CREDITS = 30;

/** Workload warning threshold; actual college overload rules must be verified. */
export const OVERLOAD_TERM_CREDITS = 18;

export function termsInWindow(
  startTerm: string,
  graduationTerm: string,
  includeSummer: boolean,
): string[] {
  const startIndex = TERM_OPTIONS.indexOf(startTerm);
  const graduationIndex = TERM_OPTIONS.indexOf(graduationTerm);
  if (startIndex < 0 || graduationIndex < startIndex) return [];
  return TERM_OPTIONS.slice(startIndex, graduationIndex + 1).filter(
    (term) => includeSummer || !term.startsWith("Summer"),
  );
}

/** "Fall 2026" -> "2026–27". Fall opens an academic year; Spring closes one. */
export function academicYear(term: string): string {
  const [season, yearText] = term.split(" ");
  const year = Number(yearText);
  const start = season === "Fall" ? year : year - 1;
  return `${start}–${String(start + 1).slice(-2)}`;
}

/** The university's four-digit term code: 2 + year + 1 Spring / 4 Summer / 7 Fall. */
export function termCode(term: string): string {
  const [season, yearText] = term.split(" ");
  const suffix = season === "Spring" ? 1 : season === "Summer" ? 4 : 7;
  return `2${String(Number(yearText) % 100).padStart(2, "0")}${suffix}`;
}

/**
 * Deep-link the class-search catalog at one subject *and* catalog number.
 *
 * Class Search reads `subject` and `catalogNbr` separately, so the three-digit
 * number has to be sent on its own — one "FIN 361" keyword lands on every FIN
 * course instead of the one.
 *
 * `term` is deliberately not forwarded. Class Search only accepts a term it has
 * already opened for registration, and handed a future one it discards the
 * whole query and shows a blank form. A plan is almost all future terms, so
 * omitting it is what keeps the link working: the page prefills subject and
 * number on the newest published term. The argument is accepted so callers can
 * pass the planned term without caring.
 */
export function classSearchUrl(code: string, term = ""): string {
  void term; // See the comment above: forwarding it breaks the link.
  const base = "https://catalog.apps.asu.edu/catalog/classes/classlist";
  const match = /^([A-Z]{2,4})\s*(\d{3}[A-Z]?)$/.exec(
    code.trim().toUpperCase(),
  );
  if (!match) return base;
  const query = new URLSearchParams({
    searchType: "all",
    subject: match[1],
    catalogNbr: match[2],
    collapse: "Y",
  });
  // Class Search is a single-page app and needs the fragment on a cold load.
  return `${base}?${query.toString()}#!`;
}

/** "FIN361" -> "FIN 361"; leaves anything that is not a course code alone. */
export function normalizeCode(value: string): string {
  const trimmed = value.trim().toUpperCase().replace(/\s+/g, " ");
  return trimmed.includes(" ")
    ? trimmed
    : trimmed.replace(/^([A-Z]{2,4})(\d{3}[A-Z]?)$/, "$1 $2");
}

/** "a", "a and b", "a, b and c" — for prose that lists selected terms. */
export function joinList(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}
