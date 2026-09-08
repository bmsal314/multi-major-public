import {
  DragEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type {
  AdvisoryNote,
  PlanResult,
  PlanState,
  PlannedCourse,
  Requirement,
  SemesterPlan,
} from "../lib/api";
import { registerPendingSave } from "../lib/saveQueue";
import {
  MAX_TERM_CREDITS,
  OVERLOAD_TERM_CREDITS,
  academicYear,
  classSearchUrl,
  normalizeCode,
} from "../lib/terms";
import PrintablePlan from "./PrintablePlan";

interface PlanViewProps {
  plan: PlanResult;
  initialState?: PlanState;
  /** Every parsed requirement, used to offer approved courses for a placeholder. */
  requirements?: Requirement[];
  /** Major-map rules to reproduce on the printed plan. */
  advisories?: AdvisoryNote[];
  /** Programs, in a stable order, so a colour always means the same program. */
  programs?: string[];
  /** Persist the whole editable map. Absent means nothing can be saved. */
  onSave?: (state: PlanState) => Promise<void> | void;
  /** Why saving is unavailable, shown instead of a save state. */
  unsavedHint?: string;
  /**
   * The terms as they currently stand in the editor.
   *
   * Panels outside the map — the pre-med checklist most of all — say where a
   * course sits. Reading that from the plan the server last built means they go
   * on naming the old term the moment anything is dragged.
   */
  onLayoutChange?: (semesters: SemesterPlan[]) => void;
}

const COURSE_CODE = /^[A-Z]{2,4}\s?\d{3}[A-Z]?$/i;

/** One connector between a prerequisite and the class that depends on it. */
interface Connector {
  key: string;
  path: string;
  kind: "prerequisite" | "corequisite";
  satisfied: boolean;
  from: string;
  to: string;
}

function cloneSemesters(semesters: SemesterPlan[]): SemesterPlan[] {
  return semesters.map((semester) => ({
    ...semester,
    courses: semester.courses.map((course) => ({ ...course })),
  }));
}

function retotal(semester: SemesterPlan): SemesterPlan {
  return {
    ...semester,
    total_credits: Number(
      semester.courses
        .reduce((total, course) => total + course.credits, 0)
        .toFixed(2),
    ),
  };
}

function tidy(value: number): string {
  return value.toFixed(2).replace(/\.?0+$/, "");
}

/** A stable, collision-free id for a class the student typed in themselves. */
function customCourseId(
  term: string,
  label: string,
  semesters: SemesterPlan[],
): string {
  const base = `custom:${term}:${label}`.replace(/\s+/g, "-").toLowerCase();
  const taken = new Set(
    semesters.flatMap((semester) => semester.courses.map((c) => c.id)),
  );
  if (!taken.has(base)) return base;
  let suffix = 2;
  while (taken.has(`${base}-${suffix}`)) suffix += 1;
  return `${base}-${suffix}`;
}

function courseMarker(course: PlannedCourse): string {
  if (course.status === "in_progress") return "NOW";
  if (course.status === "milestone") return "GATE";
  if (course.is_placeholder && course.status !== "personal") return "PICK";
  return course.catalog_number || course.code.slice(0, 4) || "ADD";
}

export default function PlanView({
  plan,
  initialState,
  requirements = [],
  advisories = [],
  programs = [],
  onSave,
  unsavedHint = "",
  onLayoutChange,
}: PlanViewProps) {
  const [semesters, setSemesters] = useState(() =>
    cloneSemesters(plan.semesters),
  );
  const [resolved, setResolved] = useState<
    Record<string, { code: string; requirementId: string }>
  >({});
  const [removed, setRemoved] = useState<string[]>([]);
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [editingSlot, setEditingSlot] = useState<string | null>(null);
  const [slotDraft, setSlotDraft] = useState("");
  const [addingTo, setAddingTo] = useState<string | null>(null);
  const [addDraft, setAddDraft] = useState({ label: "", credits: 3 });
  const [focusTerm, setFocusTerm] = useState(plan.semesters[0]?.term ?? "");
  const [activeCourse, setActiveCourse] = useState<string | null>(null);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string>("");
  const [dirty, setDirty] = useState(false);
  const editVersion = useRef(0);
  const failedVersion = useRef<number | null>(null);
  const inFlight = useRef<Promise<void> | null>(null);

  const trackRef = useRef<HTMLDivElement | null>(null);
  const cardRefs = useRef(new Map<string, HTMLElement>());
  const courseRefs = useRef(new Map<string, HTMLElement>());
  const autoScrollRef = useRef<number | null>(null);

  useEffect(() => {
    setSemesters(cloneSemesters(plan.semesters));
    setResolved(
      Object.fromEntries(
        (initialState?.placeholders ?? []).map((p) => [
          p.slot_id,
          { code: p.course_code, requirementId: p.requirement_id },
        ]),
      ),
    );
    setRemoved(initialState?.removed_course_ids ?? []);
    setEditingSlot(null);
    setDirty(false);
    setFocusTerm(plan.semesters[0]?.term ?? "");
  }, [plan]);

  const requirementsById = useMemo(() => {
    const index = new Map<string, Requirement>();
    requirements.forEach((requirement) =>
      index.set(requirement.id, requirement),
    );
    return index;
  }, [requirements]);

  const overCapTerms = useMemo(
    () =>
      semesters.filter(
        (semester) =>
          !semester.is_unplaced &&
          semester.total_credits > semester.credit_limit + 0.01,
      ),
    [semesters],
  );
  const underFloorTerms = useMemo(
    () =>
      semesters.filter(
        (semester) =>
          !semester.is_unplaced &&
          semester.courses.length > 0 &&
          !semester.is_in_progress &&
          semester.total_credits < plan.min_credits,
      ),
    [semesters, plan.min_credits],
  );
  const holding = useMemo(
    () => semesters.find((semester) => semester.is_unplaced) ?? null,
    [semesters],
  );

  // ------------------------------------------------------------------ editing

  const mutate = (next: SemesterPlan[], message: string) => {
    editVersion.current += 1;
    setSemesters(next.map(retotal));
    setNotice(message);
    setDirty(true);
  };

  const moveCourse = (courseId: string, destinationTerm: string) => {
    const sourceIndex = semesters.findIndex((semester) =>
      semester.courses.some((course) => course.id === courseId),
    );
    const destinationIndex = semesters.findIndex(
      (semester) => semester.term === destinationTerm,
    );
    if (
      sourceIndex < 0 ||
      destinationIndex < 0 ||
      sourceIndex === destinationIndex
    )
      return;

    const course = semesters[sourceIndex].courses.find(
      (candidate) => candidate.id === courseId,
    );
    if (!course) return;
    if (!course.movable) {
      setNotice(
        `${course.label} is already registered for ${semesters[sourceIndex].term}.`,
      );
      return;
    }

    // Anything may go anywhere. A destination that breaks a credit ceiling or a
    // prerequisite is shown in red rather than refused, because the student is
    // the one who knows whether the rule really binds.
    const next = cloneSemesters(semesters);
    next[sourceIndex].courses = next[sourceIndex].courses.filter(
      (candidate) => candidate.id !== courseId,
    );
    next[destinationIndex].courses.push(course);

    const destination = next[destinationIndex];
    if (destination.is_unplaced) {
      mutate(next, `${course.label} parked until you pick a term for it.`);
      return;
    }
    if (destination.is_in_progress) {
      // Not refused — but registration for this term has closed, so a class
      // cannot actually be added to it. Saying "raise the ceiling" here would be
      // wrong advice: there is no ceiling to raise on a term already under way.
      mutate(
        next,
        `${course.label} moved to ${destinationTerm}, but you are already registered for that term — it cannot take another class. Move it to a later term before saving.`,
      );
      return;
    }
    const projected = destination.courses.reduce(
      (total, item) => total + item.credits,
      0,
    );
    const overBy = projected - destination.credit_limit;
    mutate(
      next,
      overBy > 0.01
        ? `${course.label} moved to ${destinationTerm}, which is now ${tidy(overBy)} credits over its ${destination.credit_limit}-credit ceiling. Raise the ceiling on the card or move something out before saving.`
        : `${course.label} moved to ${destinationTerm}.`,
    );
  };

  const removeCourse = (courseId: string) => {
    const course = semesters
      .flatMap((semester) => semester.courses)
      .find((item) => item.id === courseId);
    if (!course) return;
    const next = semesters.map((semester) => ({
      ...semester,
      courses: semester.courses.filter((item) => item.id !== courseId),
    }));
    // A planner-suggested class has to be remembered as removed; one the student
    // added themselves simply stops existing.
    if (!courseId.startsWith("custom:")) {
      setRemoved((current) => [...new Set([...current, courseId])]);
    }
    mutate(next, `${course.label} taken off the map.`);
  };

  /**
   * Throw away every edit and go back to the planner's own arrangement.
   *
   * This is the only control here that destroys work rather than changing it,
   * and autosave writes the result a second later, so it asks first.
   */
  const restoreRemoved = () => {
    const edits =
      removed.length + Object.keys(resolved).length + (dirty ? 1 : 0);
    if (
      edits > 0 &&
      !window.confirm(
        "Reset the map back to the planner's arrangement? Every move, added class, removed class and course choice on this map is discarded.",
      )
    )
      return;
    setRemoved([]);
    setSemesters(cloneSemesters(plan.semesters));
    setResolved({});
    setNotice(
      "Every removed class is back, and the original arrangement is restored.",
    );
    editVersion.current += 1;
    setDirty(true);
  };

  const addCourse = (term: string) => {
    const label = addDraft.label.trim();
    if (!label) {
      setNotice("Give the class a name or a course code.");
      return;
    }
    const code = COURSE_CODE.test(label) ? normalizeCode(label) : "";
    const next = semesters.map((semester) =>
      semester.term === term
        ? {
            ...semester,
            courses: [
              ...semester.courses,
              {
                // Two classes with the same name in the same term are a real
                // thing to plan. A term-and-label id would collide, and the
                // second one would replace the first on the next reload.
                id: customCourseId(term, label, semesters),
                code,
                subject: code.split(" ")[0] ?? "",
                catalog_number: code.split(" ")[1] ?? "",
                label: code || label,
                credits: addDraft.credits,
                majors: ["Added by hand"],
                requirement_ids: [],
                is_placeholder: false,
                status: "personal" as const,
                movable: true,
                prerequisites: [],
                corequisites: [],
                alternatives: [],
                attributes: [],
                advisories: [],
                justification: "Added to the map by hand.",
                sequenced_by: "",
                class_search_url: code ? classSearchUrl(code, term) : "",
                resolved_from_placeholder: false,
                note: "",
              },
            ],
          }
        : semester,
    );
    setAddingTo(null);
    setAddDraft({ label: "", credits: 3 });
    mutate(next, `${code || label} added to ${term}.`);
  };

  const setTermLimit = (term: string, limit: number) => {
    const next = semesters.map((semester) =>
      semester.term === term ? { ...semester, credit_limit: limit } : semester,
    );
    mutate(next, `${term} ceiling set to ${limit} credits.`);
  };

  const toggleMcat = (term: string) => {
    const next = semesters.map((semester) =>
      semester.term === term
        ? { ...semester, is_mcat_term: !semester.is_mcat_term }
        : semester,
    );
    const nowOn = next.find((semester) => semester.term === term)?.is_mcat_term;
    mutate(
      next,
      nowOn
        ? `${term} is now your MCAT term; its ${
            next.find((semester) => semester.term === term)?.credit_limit
          }-credit ceiling is the study protection.`
        : `${term} is no longer marked as an MCAT term.`,
    );
  };

  const setCourseCredits = (courseId: string, credits: number) => {
    const next = semesters.map((semester) => ({
      ...semester,
      courses: semester.courses.map((course) =>
        course.id === courseId ? { ...course, credits } : course,
      ),
    }));
    mutate(next, "Credit hours updated.");
  };

  // ------------------------------------------------------------- placeholders

  const plannedCodes = useMemo(
    () =>
      new Set(
        semesters.flatMap((semester) =>
          semester.courses.map((item) => item.code),
        ),
      ),
    [semesters],
  );

  /**
   * Courses this slot can be filled with.
   *
   * A course already on the map is left out. Using one class for two
   * requirements is the double-count this app will not assume on a student's
   * behalf, and the server's replay refuses it for the same reason — so
   * offering it here would only lead to a refusal.
   */
  const optionsForSlot = (course: PlannedCourse): string[] => {
    const fromRequirement = course.requirement_ids.flatMap(
      (id) => requirementsById.get(id)?.course_options ?? [],
    );
    return [...new Set([...course.alternatives, ...fromRequirement])].filter(
      (code) => !plannedCodes.has(code),
    );
  };

  const criteriaForSlot = (course: PlannedCourse): string[] => [
    ...new Set(
      course.requirement_ids.flatMap(
        (id) => requirementsById.get(id)?.criteria ?? [],
      ),
    ),
  ];

  const resolveSlot = (course: PlannedCourse, rawCode: string) => {
    const code = normalizeCode(rawCode);
    if (!COURSE_CODE.test(code)) {
      setNotice("Enter a course code such as SOS 111.");
      return;
    }
    const alreadyPlanned = semesters.find((semester) =>
      semester.courses.some(
        (item) => item.id !== course.id && item.code === code,
      ),
    );
    if (alreadyPlanned) {
      setNotice(
        `${code} is already on the map. Double-counting has not been verified; choose another course or review this requirement with an advisor.`,
      );
      return;
    }
    // The saved map is rebuilt from the audit on every load, and that rebuild
    // only honours a choice the requirement itself lists. Accepting anything
    // else here would show the class on screen and then quietly drop it the next
    // time the map was opened.
    if (course.alternatives.length > 0 && !course.alternatives.includes(code)) {
      setNotice(
        `${code} is not one of the courses this requirement lists. Choose from the approved list, or ask your advisor to record a substitution in DARS first.`,
      );
      return;
    }

    const next = semesters.map((semester) => ({
      ...semester,
      courses: semester.courses.map((item) =>
        item.id === course.id
          ? {
              ...item,
              code,
              subject: code.split(" ")[0],
              catalog_number: code.split(" ")[1],
              label: code,
              is_placeholder: false,
              resolved_from_placeholder: true,
              class_search_url: classSearchUrl(code, semester.term),
            }
          : item,
      ),
    }));
    setResolved((current) => ({
      ...current,
      [course.id]: { code, requirementId: course.requirement_ids[0] ?? "" },
    }));
    setEditingSlot(null);
    setSlotDraft("");
    mutate(next, `${code} fills ${course.label}.`);
  };

  const clearSlot = (courseId: string) => {
    const original = plan.semesters
      .flatMap((semester) => semester.courses)
      .find((item) => item.id === courseId);
    if (!original) return;
    const next = semesters.map((semester) => ({
      ...semester,
      courses: semester.courses.map((item) =>
        item.id === courseId ? { ...original } : item,
      ),
    }));
    setResolved((current) => {
      const copy = { ...current };
      delete copy[courseId];
      return copy;
    });
    mutate(next, `${original.label} is unset again.`);
  };

  const placeholderCount = semesters
    .flatMap((semester) => semester.courses)
    .filter(
      (course) => course.is_placeholder && course.status !== "personal",
    ).length;

  // ------------------------------------------------------------------- saving

  const buildState = useCallback((): PlanState => {
    const custom = semesters.flatMap((semester) =>
      semester.courses
        .filter((course) => course.id.startsWith("custom:"))
        .map((course) => ({
          course_id: course.id,
          code: course.code,
          label: course.label,
          credits: course.credits,
          term: semester.term,
          majors: course.majors,
          note: course.note,
        })),
    );
    return {
      placements: semesters.flatMap((semester) =>
        semester.courses
          .filter(
            (course) => course.movable && !course.id.startsWith("custom:"),
          )
          .map((course) => ({
            course_id: course.id,
            course_code: course.code,
            locked: false,
            term: semester.term,
            credits: course.credits,
          })),
      ),
      placeholders: Object.entries(resolved).map(([slotId, choice]) => ({
        slot_id: slotId,
        course_code: choice.code,
        requirement_id: choice.requirementId,
        note: "",
      })),
      term_settings: semesters
        .filter((semester) => !semester.is_unplaced)
        .map((semester) => ({
          term: semester.term,
          credit_limit: semester.credit_limit,
          is_mcat_term: semester.is_mcat_term,
          note: semester.note,
        })),
      custom_courses: custom,
      removed_course_ids: removed,
    };
  }, [removed, resolved, semesters]);

  const save = useCallback(async () => {
    if (!onSave) return;
    if (inFlight.current) {
      await inFlight.current;
      if (dirtyRef.current) await saveRef.current();
      return;
    }
    const version = editVersion.current;
    if (overCapTerms.length > 0) {
      const blocked = `${overCapTerms
        .map((semester) => semester.term)
        .join(
          ", ",
        )} sits over its credit ceiling, so the map cannot be saved yet.`;
      setNotice(blocked);
      // Thrown, not swallowed: a caller flushing before shutdown has to learn
      // that the map did not save rather than proceed and lose it.
      throw new Error(blocked);
    }
    setSaving(true);
    try {
      const pending = Promise.resolve(onSave(buildState()));
      inFlight.current = pending;
      await pending;
      if (editVersion.current === version) {
        dirtyRef.current = false;
        setDirty(false);
      }
      setSavedAt(new Date().toLocaleTimeString());
      setNotice("Semester map saved to your account.");
    } catch (caught) {
      failedVersion.current = version;
      setNotice(
        caught instanceof Error ? caught.message : "Could not save this plan.",
      );
      throw caught;
    } finally {
      inFlight.current = null;
      setSaving(false);
    }
  }, [buildState, onSave, overCapTerms]);

  // Autosave, because a plan you have to remember to save is a plan you lose.
  useEffect(() => {
    if (
      !dirty ||
      saving ||
      !onSave ||
      overCapTerms.length > 0 ||
      failedVersion.current === editVersion.current
    )
      return;
    const timer = setTimeout(() => {
      void save().catch(() => {
        // The notice already says what went wrong; autosave simply retries on
        // the next edit rather than nagging.
      });
    }, 900);
    return () => clearTimeout(timer);
  }, [dirty, saving, onSave, overCapTerms.length, save]);

  // Autosave is debounced, so between an edit and the write there is a window
  // where the map exists only in this tab. Anything that ends the session —
  // stopping the server, closing the tab — has to know about that window.
  const dirtyRef = useRef(dirty);
  const saveRef = useRef(save);
  dirtyRef.current = dirty;
  saveRef.current = save;

  useEffect(
    () =>
      registerPendingSave({
        isDirty: () => dirtyRef.current,
        flush: () => saveRef.current(),
      }),
    [],
  );

  useEffect(() => {
    onLayoutChange?.(semesters);
  }, [semesters, onLayoutChange]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // --------------------------------------------------------------- connectors

  const codeToCourseId = useMemo(() => {
    const index = new Map<string, { id: string; termIndex: number }>();
    semesters.forEach((semester, termIndex) => {
      semester.courses.forEach((course) => {
        if (course.code) index.set(course.code, { id: course.id, termIndex });
      });
    });
    return index;
  }, [semesters]);

  const drawConnectors = useCallback(() => {
    const track = trackRef.current;
    if (!track) return;
    const trackBox = track.getBoundingClientRect();
    const edges: Connector[] = [];

    const anchor = (element: HTMLElement) => {
      const box = element.getBoundingClientRect();
      return {
        left: box.left - trackBox.left + track.scrollLeft,
        right: box.right - trackBox.left + track.scrollLeft,
        middle: box.top - trackBox.top + track.scrollTop + box.height / 2,
      };
    };

    semesters.forEach((semester, termIndex) => {
      semester.courses.forEach((course) => {
        const target = courseRefs.current.get(course.id);
        if (!target) return;
        const links: Array<[string, Connector["kind"]]> = [
          ...course.prerequisites.map(
            (code) => [code, "prerequisite"] as [string, Connector["kind"]],
          ),
          ...course.corequisites.map(
            (code) => [code, "corequisite"] as [string, Connector["kind"]],
          ),
        ];
        links.forEach(([code, kind]) => {
          const source = codeToCourseId.get(code);
          if (!source) return;
          const sourceElement = courseRefs.current.get(source.id);
          if (!sourceElement) return;

          const from = anchor(sourceElement);
          const to = anchor(target);
          const satisfied =
            kind === "prerequisite"
              ? source.termIndex < termIndex
              : source.termIndex <= termIndex;
          const span = Math.max(36, (to.left - from.right) / 2);
          edges.push({
            key: `${source.id}->${course.id}:${kind}`,
            kind,
            satisfied,
            from: source.id,
            to: course.id,
            path: `M ${from.right} ${from.middle} C ${from.right + span} ${from.middle}, ${
              to.left - span
            } ${to.middle}, ${to.left} ${to.middle}`,
          });
        });
      });
    });

    setConnectors(edges);
  }, [codeToCourseId, semesters]);

  useLayoutEffect(() => {
    drawConnectors();
    const track = trackRef.current;
    if (!track) return;
    const observer = new ResizeObserver(() => drawConnectors());
    observer.observe(track);
    window.addEventListener("resize", drawConnectors);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", drawConnectors);
    };
  }, [drawConnectors]);

  const chainFor = (courseId: string | null): Set<string> => {
    if (!courseId) return new Set();
    const chain = new Set<string>([courseId]);
    let grew = true;
    while (grew) {
      grew = false;
      connectors.forEach((edge) => {
        if (chain.has(edge.to) && !chain.has(edge.from)) {
          chain.add(edge.from);
          grew = true;
        }
        if (chain.has(edge.from) && !chain.has(edge.to)) {
          chain.add(edge.to);
          grew = true;
        }
      });
    }
    return chain;
  };
  const highlighted = chainFor(activeCourse);

  // ----------------------------------------------------------------- carousel

  const scrollToTerm = (term: string) => {
    setFocusTerm(term);
    cardRefs.current.get(term)?.scrollIntoView({
      behavior: "smooth",
      inline: "start",
      block: "nearest",
    });
  };

  const step = (direction: -1 | 1) => {
    const index = semesters.findIndex(
      (semester) => semester.term === focusTerm,
    );
    const next = Math.min(semesters.length - 1, Math.max(0, index + direction));
    scrollToTerm(semesters[next].term);
  };

  /**
   * Scroll the carousel while a class is held near either edge.
   *
   * The runway is wider than the screen and the holding area sits at the far
   * right, so without this a class can only be dragged as far as the visible
   * terms — the one destination you are most likely to want is off-screen.
   */
  const stopAutoScroll = () => {
    if (autoScrollRef.current !== null) {
      cancelAnimationFrame(autoScrollRef.current);
      autoScrollRef.current = null;
    }
  };

  const autoScroll = (clientX: number) => {
    const track = trackRef.current;
    if (!track) return;
    const box = track.getBoundingClientRect();
    const edge = Math.min(140, box.width / 4);
    const past =
      clientX < box.left + edge
        ? clientX - (box.left + edge)
        : clientX > box.right - edge
          ? clientX - (box.right - edge)
          : 0;
    if (past === 0) {
      stopAutoScroll();
      return;
    }
    if (autoScrollRef.current !== null) return;
    const step = () => {
      const current = trackRef.current;
      if (!current) return;
      current.scrollLeft += Math.max(-24, Math.min(24, past / 4));
      drawConnectors();
      autoScrollRef.current = requestAnimationFrame(step);
    };
    autoScrollRef.current = requestAnimationFrame(step);
  };

  useEffect(() => stopAutoScroll, []);

  const onDrop = (event: DragEvent<HTMLElement>, term: string) => {
    event.preventDefault();
    stopAutoScroll();
    const courseId = event.dataTransfer.getData("text/plain") || draggedId;
    if (courseId) moveCourse(courseId, term);
    setDraggedId(null);
    setDropTarget(null);
  };

  const programColour = (course: PlannedCourse): string => {
    if (course.majors.length > 1) return "shared";
    const index = programs.indexOf(course.majors[0]);
    if (index >= 0) return `program-${index % 4}`;
    if (course.status === "premed") return "premed";
    if (course.status === "personal") return "personal";
    return "other";
  };

  const futureCredits = semesters
    .filter((semester) => !semester.is_unplaced)
    .flatMap((semester) => semester.courses)
    .filter((course) => course.status !== "in_progress")
    .reduce((total, course) => total + course.credits, 0);

  return (
    <section className="content-section plan-section" id="plan">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Editable academic runway</p>
          <h2>Graduating {plan.graduation_term}</h2>
          {/*
            The target is the student's answer, so the useful statement is what
            it costs per term — and whether the ceiling they set gets them
            there. They will edit these limits, and this has to keep up.
          */}
          {plan.pace.open_terms > 0 && (
            <p
              className={`plan-pace${plan.pace.feasible ? "" : " plan-pace-short"}`}
              role="status"
            >
              {plan.pace.feasible ? (
                <>
                  {tidy(plan.pace.outstanding_credits)} credits left across{" "}
                  {plan.pace.open_terms} semester
                  {plan.pace.open_terms === 1 ? "" : "s"} —{" "}
                  <strong>
                    about {tidy(plan.pace.required_per_term)} a term
                  </strong>{" "}
                  to finish on time.
                </>
              ) : (
                <>
                  <strong>
                    {tidy(plan.pace.unplaced_credits)} credits will not fit
                  </strong>{" "}
                  by {plan.graduation_term}. Hitting it needs about{" "}
                  {tidy(plan.pace.required_per_term)} credits a term, not{" "}
                  {plan.pace.credit_ceiling}. Raise a term&rsquo;s ceiling
                  below, add summers, or graduate later.
                </>
              )}
            </p>
          )}
        </div>
        <div className="plan-heading-actions">
          <span>{tidy(futureCredits)} future credits placed</span>
          {placeholderCount > 0 ? (
            <span className="plan-todo">{placeholderCount} to choose</span>
          ) : (
            <span className="plan-done">every class named</span>
          )}
          <button type="button" onClick={restoreRemoved}>
            Reset map
          </button>
          <button type="button" onClick={() => window.print()}>
            Print / save PDF
          </button>
          {onSave ? (
            <button
              type="button"
              className="button-primary"
              onClick={() => void save().catch(() => undefined)}
              disabled={saving || overCapTerms.length > 0}
            >
              {saving ? "Saving…" : dirty ? "Save map" : "Saved"}
            </button>
          ) : null}
        </div>
      </div>

      <p className="section-intro">
        Drag any class into any term — nothing is refused. A term over its
        ceiling turns red and blocks saving until you either move a class out or
        raise that term&rsquo;s ceiling on the card itself. Prerequisite lines
        are drawn between the classes that depend on each other, and turn red
        when an order is broken. Everything you change here is saved to your
        account automatically.
      </p>

      <div className="plan-status-row">
        <p className="plan-live-notice" aria-live="polite">
          {notice}
        </p>
        <span
          className={`plan-save-state${!onSave && unsavedHint ? " is-warning" : ""}`}
        >
          {!onSave && unsavedHint
            ? unsavedHint
            : saving
              ? "Saving…"
              : dirty
                ? overCapTerms.length > 0
                  ? "Not saved — a term is over its ceiling"
                  : "Unsaved changes"
                : savedAt
                  ? `Saved at ${savedAt}`
                  : plan.applied_decisions > 0
                    ? `${plan.applied_decisions} saved decision${plan.applied_decisions === 1 ? "" : "s"} restored`
                    : "Nothing to save yet"}
        </span>
      </div>

      {overCapTerms.length > 0 && (
        <div className="cap-breach" role="alert">
          <strong>
            {overCapTerms.length} term{overCapTerms.length === 1 ? "" : "s"}{" "}
            over the ceiling
          </strong>
          <ul>
            {overCapTerms.map((semester) => (
              <li key={semester.term}>
                <span>
                  {semester.term} holds <b>{tidy(semester.total_credits)}</b> of{" "}
                  {semester.credit_limit} credits
                  {semester.is_in_progress
                    ? " — and is already registered"
                    : ""}
                </span>
                {semester.is_in_progress ? (
                  <em>Move the extra class to a later term</em>
                ) : (
                  <button
                    type="button"
                    onClick={() =>
                      setTermLimit(
                        semester.term,
                        Math.ceil(semester.total_credits),
                      )
                    }
                  >
                    Raise {semester.term} to {Math.ceil(semester.total_credits)}{" "}
                    credits
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {holding && holding.courses.length > 0 && (
        <div className="holding-breach" role="alert">
          <strong>
            {holding.courses.length} class
            {holding.courses.length === 1 ? "" : "es"} still need a term
          </strong>
          <span>
            {holding.courses.map((course) => course.label).join(", ")} — these
            fit no term at its current ceiling. They are waiting at the end of
            the map: drag one into a term and raise that term&rsquo;s ceiling,
            turn on summer terms, or move graduation later. Nothing is dropped.
          </span>
        </div>
      )}

      {underFloorTerms.length > 0 && (
        <div className="floor-breach">
          <strong>Below your {plan.min_credits}-credit minimum</strong>
          <span>
            {underFloorTerms
              .map(
                (semester) =>
                  `${semester.term} (${tidy(semester.total_credits)})`,
              )
              .join(", ")}{" "}
            — this is below your chosen minimum. Confirm any enrollment or
            scholarship conditions with your advisor. Move a class in, or drop
            the floor on the setup screen if that is deliberate.
          </span>
        </div>
      )}

      <div className="carousel-shell">
        <div className="carousel-controls">
          <button
            type="button"
            aria-label="Previous term"
            onClick={() => step(-1)}
            disabled={semesters[0]?.term === focusTerm}
          >
            ‹
          </button>
          <div className="term-rail" role="tablist" aria-label="Jump to a term">
            {semesters.map((semester) => (
              <button
                key={semester.term}
                type="button"
                role="tab"
                aria-selected={semester.term === focusTerm}
                className={[
                  semester.term === focusTerm ? "is-focus" : "",
                  !semester.is_unplaced &&
                  semester.total_credits > semester.credit_limit + 0.01
                    ? "is-over"
                    : "",
                  semester.is_mcat_term ? "is-mcat" : "",
                  semester.is_unplaced ? "is-holding" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                onClick={() => scrollToTerm(semester.term)}
              >
                {semester.is_unplaced ? (
                  <>
                    <b>!</b>
                    <small>WAIT</small>
                    <i>{semester.courses.length}</i>
                  </>
                ) : (
                  <>
                    <b>{semester.term.split(" ")[0].slice(0, 2)}</b>
                    <small>{semester.term.split(" ")[1].slice(-2)}</small>
                    <i>{tidy(semester.total_credits)}</i>
                  </>
                )}
              </button>
            ))}
          </div>
          <button
            type="button"
            aria-label="Next term"
            onClick={() => step(1)}
            disabled={semesters[semesters.length - 1]?.term === focusTerm}
          >
            ›
          </button>
        </div>

        <div
          className={`carousel-track${draggedId ? " is-dragging-within" : ""}`}
          ref={trackRef}
          onScroll={drawConnectors}
          onDragOver={(event) => autoScroll(event.clientX)}
          onDragLeave={stopAutoScroll}
          onDrop={stopAutoScroll}
        >
          <svg className="connector-layer" aria-hidden="true">
            {connectors.map((edge) => (
              <path
                key={edge.key}
                d={edge.path}
                className={[
                  "connector",
                  edge.kind === "corequisite" ? "is-coreq" : "",
                  edge.satisfied ? "is-ok" : "is-broken",
                  highlighted.has(edge.from) || highlighted.has(edge.to)
                    ? "is-lit"
                    : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
              />
            ))}
          </svg>

          {semesters.map((semester) => {
            const over =
              !semester.is_unplaced &&
              semester.total_credits > semester.credit_limit + 0.01;
            const under =
              !semester.is_unplaced &&
              semester.courses.length > 0 &&
              !semester.is_in_progress &&
              semester.total_credits < plan.min_credits;
            return (
              <article
                key={semester.term}
                ref={(element) => {
                  if (element) cardRefs.current.set(semester.term, element);
                  else cardRefs.current.delete(semester.term);
                }}
                className={[
                  "semester-card",
                  semester.is_unplaced ? "is-holding" : "",
                  semester.is_in_progress ? "is-current-term" : "",
                  semester.is_mcat_term ? "is-mcat-term" : "",
                  over ? "is-over-cap" : "",
                  under ? "is-under-floor" : "",
                  dropTarget === semester.term ? "is-drop-target" : "",
                  semester.term === focusTerm ? "is-focus" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDropTarget(semester.term);
                }}
                onDragLeave={() =>
                  setDropTarget((current) =>
                    current === semester.term ? null : current,
                  )
                }
                onDrop={(event) => onDrop(event, semester.term)}
              >
                <header>
                  {semester.is_unplaced ? (
                    <>
                      <div className="term-badges">
                        <span className="badge-holding">Needs a term</span>
                      </div>
                      <h3>{semester.term}</h3>
                      <p className="credit-count is-holding">
                        <b>{semester.courses.length}</b> class
                        {semester.courses.length === 1 ? "" : "es"} ·{" "}
                        {tidy(semester.total_credits)} credits with nowhere to
                        go
                      </p>
                    </>
                  ) : (
                    <>
                      <div className="term-badges">
                        <span className="term-year">
                          {academicYear(semester.term)}
                        </span>
                        {semester.is_in_progress && (
                          <span className="badge-now">Registered</span>
                        )}
                        {semester.is_mcat_term && (
                          <span className="badge-mcat">MCAT</span>
                        )}
                        {!semester.is_in_progress &&
                          semester.credit_limit > OVERLOAD_TERM_CREDITS && (
                            <span className="badge-overload">High load</span>
                          )}
                      </div>
                      <h3>{semester.term}</h3>
                      <p
                        className={
                          over
                            ? "credit-count is-over"
                            : under
                              ? "credit-count is-under"
                              : "credit-count"
                        }
                      >
                        <b>{tidy(semester.total_credits)}</b> /{" "}
                        {semester.credit_limit} credits
                        {over ? (
                          <em>
                            {" "}
                            ·{" "}
                            {tidy(
                              semester.total_credits - semester.credit_limit,
                            )}{" "}
                            over
                          </em>
                        ) : null}
                      </p>
                    </>
                  )}
                  {!semester.is_in_progress && !semester.is_unplaced && (
                    <div className="term-tuning">
                      <label>
                        <span className="sr-only">
                          Credit ceiling for {semester.term}
                        </span>
                        <input
                          type="range"
                          min={plan.min_credits}
                          max={MAX_TERM_CREDITS}
                          step={1}
                          value={semester.credit_limit}
                          onChange={(event) =>
                            setTermLimit(
                              semester.term,
                              Number(event.target.value),
                            )
                          }
                        />
                      </label>
                      <label className="mcat-toggle">
                        <input
                          type="checkbox"
                          checked={semester.is_mcat_term}
                          onChange={() => toggleMcat(semester.term)}
                        />
                        <span>MCAT term</span>
                      </label>
                    </div>
                  )}
                </header>

                <ul>
                  {semester.courses.map((course) => (
                    <li
                      key={course.id}
                      ref={(element) => {
                        if (element) courseRefs.current.set(course.id, element);
                        else courseRefs.current.delete(course.id);
                      }}
                      className={[
                        `course-status-${course.status}`,
                        `tint-${programColour(course)}`,
                        draggedId === course.id ? "is-dragging" : "",
                        highlighted.has(course.id) ? "is-lit" : "",
                        course.sequenced_by ? "is-sequenced" : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                      draggable={course.movable}
                      onDragStart={(event) => {
                        event.dataTransfer.setData("text/plain", course.id);
                        event.dataTransfer.effectAllowed = "move";
                        setDraggedId(course.id);
                      }}
                      onDragEnd={() => {
                        setDraggedId(null);
                        stopAutoScroll();
                      }}
                      onMouseEnter={() => setActiveCourse(course.id)}
                      onMouseLeave={() => setActiveCourse(null)}
                      onFocus={() => setActiveCourse(course.id)}
                      onBlur={() => setActiveCourse(null)}
                    >
                      <span
                        className={
                          course.is_placeholder
                            ? "course-mark placeholder-course"
                            : "course-mark"
                        }
                      >
                        {courseMarker(course)}
                      </span>

                      <div className="course-body">
                        <strong>
                          {course.subject ? (
                            <>
                              {course.subject}{" "}
                              <b className="catalog-number">
                                {course.catalog_number}
                              </b>
                            </>
                          ) : (
                            course.label
                          )}
                        </strong>
                        <small className="course-programs">
                          {course.majors.join(" + ")}
                        </small>

                        {course.attributes.length > 0 && (
                          <small className="course-attributes">
                            also clears {course.attributes.join(", ")}
                          </small>
                        )}
                        {course.sequenced_by && (
                          <small className="course-sequenced">
                            {course.sequenced_by}
                          </small>
                        )}
                        {course.prerequisites.length > 0 && (
                          <small className="course-rule">
                            After {course.prerequisites.join(" or ")}
                          </small>
                        )}
                        {course.corequisites.length > 0 && (
                          <small className="course-rule">
                            With {course.corequisites.join(", ")}
                          </small>
                        )}
                        {course.advisories.length > 0 && (
                          <small className="course-advisory">
                            {course.advisories.length} advisor note
                            {course.advisories.length === 1 ? "" : "s"} — see
                            Rules to confirm
                          </small>
                        )}
                        {resolved[course.id] && (
                          <small className="slot-resolved">
                            you chose this ·{" "}
                            <button
                              type="button"
                              className="button-text"
                              onClick={() => clearSlot(course.id)}
                            >
                              undo
                            </button>
                          </small>
                        )}

                        {course.is_placeholder &&
                        course.status !== "personal" ? (
                          editingSlot === course.id ? (
                            <div className="slot-picker">
                              {optionsForSlot(course).length > 0 && (
                                <select
                                  aria-label={`Approved courses for ${course.label}`}
                                  value=""
                                  onChange={(event) =>
                                    resolveSlot(course, event.target.value)
                                  }
                                >
                                  <option value="">
                                    Approved courses (
                                    {optionsForSlot(course).length})…
                                  </option>
                                  {optionsForSlot(course).map((code) => (
                                    <option key={code} value={code}>
                                      {code}
                                    </option>
                                  ))}
                                </select>
                              )}
                              <input
                                aria-label={`Course code for ${course.label}`}
                                placeholder={
                                  course.alternatives.length > 0
                                    ? "A course from the approved list"
                                    : "e.g. SOS 111"
                                }
                                value={slotDraft}
                                onChange={(event) =>
                                  setSlotDraft(event.target.value)
                                }
                                onKeyDown={(event) => {
                                  if (event.key === "Enter")
                                    resolveSlot(course, slotDraft);
                                  if (event.key === "Escape")
                                    setEditingSlot(null);
                                }}
                              />
                              <button
                                type="button"
                                onClick={() => resolveSlot(course, slotDraft)}
                              >
                                Set
                              </button>
                              <button
                                type="button"
                                className="button-text"
                                onClick={() => setEditingSlot(null)}
                              >
                                Cancel
                              </button>
                              {criteriaForSlot(course).length > 0 && (
                                <small>
                                  Must satisfy:{" "}
                                  {criteriaForSlot(course).join(", ")}.{" "}
                                  <a
                                    href={classSearchUrl(
                                      normalizeCode(slotDraft),
                                      semester.term,
                                    )}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    Check Class Search ↗
                                  </a>
                                </small>
                              )}
                            </div>
                          ) : (
                            <button
                              type="button"
                              className="button-text slot-open"
                              onClick={() => {
                                setEditingSlot(course.id);
                                setSlotDraft("");
                              }}
                            >
                              Choose a course
                            </button>
                          )
                        ) : null}

                        {course.class_search_url && (
                          <a
                            className="course-search-link"
                            href={course.class_search_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {course.subject} {course.catalog_number} in Class
                            Search ↗
                          </a>
                        )}
                      </div>

                      <div className="course-controls">
                        {course.id.startsWith("custom:") ? (
                          <label className="credit-edit">
                            <span className="sr-only">
                              Credit hours for {course.label}
                            </span>
                            <input
                              type="number"
                              min={0}
                              max={12}
                              step={0.25}
                              value={course.credits}
                              onChange={(event) =>
                                setCourseCredits(
                                  course.id,
                                  Number(event.target.value),
                                )
                              }
                            />
                          </label>
                        ) : (
                          <b>{tidy(course.credits)}</b>
                        )}
                        {course.movable ? (
                          <>
                            <label>
                              <span className="sr-only">
                                Move {course.label} to
                              </span>
                              <select
                                value={semester.term}
                                onKeyDown={(event) => {
                                  if (
                                    event.altKey ||
                                    event.metaKey ||
                                    event.ctrlKey ||
                                    !["ArrowDown", "ArrowUp"].includes(
                                      event.key,
                                    )
                                  )
                                    return;
                                  event.preventDefault();
                                  const index = semesters.findIndex(
                                    (s) => s.term === semester.term,
                                  );
                                  const next =
                                    semesters[
                                      index +
                                        (event.key === "ArrowDown" ? 1 : -1)
                                    ];
                                  if (next) moveCourse(course.id, next.term);
                                }}
                                onChange={(event) =>
                                  moveCourse(course.id, event.target.value)
                                }
                              >
                                {semesters.map((target) => (
                                  <option key={target.term} value={target.term}>
                                    {target.term}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <button
                              type="button"
                              className="course-remove"
                              aria-label={`Take ${course.label} off the map`}
                              onClick={() => removeCourse(course.id)}
                            >
                              ×
                            </button>
                          </>
                        ) : (
                          <small>pinned</small>
                        )}
                      </div>
                    </li>
                  ))}

                  {semester.courses.length === 0 && (
                    <li className="empty-term">
                      <span className="course-mark">
                        {semester.is_unplaced ? "DONE" : "OPEN"}
                      </span>
                      <div className="course-body">
                        <strong>
                          {semester.is_unplaced
                            ? "Everything has a term"
                            : "No classes placed"}
                        </strong>
                        <small>
                          {semester.is_unplaced
                            ? "Nothing is waiting to be scheduled"
                            : "Drop a class here"}
                        </small>
                      </div>
                    </li>
                  )}
                </ul>

                {semester.is_unplaced ? null : (
                  <footer className="term-footer">
                    {addingTo === semester.term ? (
                      <div className="add-course">
                        <input
                          aria-label={`Class to add to ${semester.term}`}
                          placeholder="Course code or name"
                          value={addDraft.label}
                          onChange={(event) =>
                            setAddDraft((draft) => ({
                              ...draft,
                              label: event.target.value,
                            }))
                          }
                          onKeyDown={(event) => {
                            if (event.key === "Enter") addCourse(semester.term);
                            if (event.key === "Escape") setAddingTo(null);
                          }}
                        />
                        <label>
                          <span className="sr-only">Credit hours</span>
                          <input
                            type="number"
                            min={0}
                            max={12}
                            step={0.25}
                            value={addDraft.credits}
                            onChange={(event) =>
                              setAddDraft((draft) => ({
                                ...draft,
                                credits: Number(event.target.value),
                              }))
                            }
                          />
                        </label>
                        <button
                          type="button"
                          onClick={() => addCourse(semester.term)}
                        >
                          Add
                        </button>
                        <button
                          type="button"
                          className="button-text"
                          onClick={() => setAddingTo(null)}
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className="button-text"
                        onClick={() => {
                          setAddingTo(semester.term);
                          setAddDraft({ label: "", credits: 3 });
                        }}
                      >
                        + Add a class
                      </button>
                    )}
                  </footer>
                )}
              </article>
            );
          })}
        </div>

        <div className="connector-legend">
          <span>
            <i className="swatch-ok" /> prerequisite met in an earlier term
          </span>
          <span>
            <i className="swatch-broken" /> order broken — move one of the two
          </span>
          <span>
            <i className="swatch-coreq" /> corequisite, same term is fine
          </span>
        </div>
      </div>

      {removed.length > 0 && (
        <p className="removed-note">
          {removed.length} planner suggestion{removed.length === 1 ? "" : "s"}{" "}
          taken off the map. They stay off across restarts until you reset.
        </p>
      )}

      {(plan.warnings.length > 0 || plan.unplanned_requirements.length > 0) && (
        <div className="plan-notes">
          {plan.warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
          {plan.unplanned_requirements.length > 0 && (
            <details>
              <summary>
                {plan.unplanned_requirements.length} items need another term or
                advisor selection
              </summary>
              <ul>
                {plan.unplanned_requirements.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      <PrintablePlan
        semesters={semesters}
        graduationTerm={plan.graduation_term}
        minCredits={plan.min_credits}
        advisories={advisories}
        programs={programs}
      />
    </section>
  );
}
