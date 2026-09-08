"""A small, comparable description of one saved semester map.

The permutations dashboard lists every map a student has saved and has to show
what actually differs between them.  Loading each saved ``result`` to do that is
not an option — they run to megabytes apiece — so this reduces a result to the
handful of numbers and decisions a person compares plans on, and that summary is
stored beside the plan.

Everything here is derived, never authored: recomputing it from a result must
always give the same answer, so a summary can be rebuilt if the shape changes.
"""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 1


def summarize(result: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any]:
    """Reduce a full analysis result to its decision metadata."""
    plan = result.get("plan") or {}
    semesters = [s for s in plan.get("semesters", []) if not s.get("is_unplaced")]
    unplaced = [s for s in plan.get("semesters", []) if s.get("is_unplaced")]
    courses = [c for s in semesters for c in s.get("courses", [])]
    placeholders = [c for c in courses if c.get("is_placeholder")]
    loads = [s.get("total_credits", 0.0) for s in semesters if not s.get("is_in_progress")]

    return {
        "schema_version": SCHEMA_VERSION,
        "graduation_term": plan.get("graduation_term", ""),
        "start_term": plan.get("start_term", ""),
        "term_count": len(semesters),
        "planned_credits": plan.get("planned_credits", 0.0),
        "course_count": len(courses),
        "placeholder_count": len(placeholders),
        "unplaced_count": sum(len(s.get("courses", [])) for s in unplaced),
        # The spread is what tells two permutations apart at a glance: a plan
        # that runs 15/15/15 and one that runs 18/12/15 total the same credits.
        "heaviest_term_credits": max(loads, default=0.0),
        "lightest_term_credits": min(loads, default=0.0),
        "programs": [audit.get("name", "") for audit in result.get("audits", [])],
        "readiness_status": (result.get("readiness") or {}).get("status", ""),
        "gap_count": (result.get("readiness") or {}).get("gap_count", 0),
        "warning_count": len(plan.get("warnings", [])),
        # Decisions the student made, echoed so the dashboard need not re-derive.
        "premed": bool(preferences.get("premed")),
        "mcat_terms": list(preferences.get("mcat_terms") or []),
        "mcat_credit_ceiling": preferences.get("mcat_credit_ceiling", 0),
        "mcat_course_ceiling": preferences.get("mcat_course_ceiling", 0),
        "credits_per_term": preferences.get("credits_per_term", 0),
        "min_credits": preferences.get("min_credits", 0),
        "include_summer": bool(preferences.get("include_summer")),
        "personal_rules": dict(preferences.get("personal_rules") or {}),
    }
