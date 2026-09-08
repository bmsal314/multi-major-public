"""Conservative cross-program overlap detection."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _criterion_key(requirement: dict[str, Any]) -> str | None:
    for criterion in requirement.get("criteria", []):
        if criterion.startswith("ASU General Studies "):
            return criterion
        if criterion in {"Approved Science and Society course", "Honors credit"}:
            return criterion
    return None


def compute_overlaps(audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only overlaps supported by an explicit course or shared criterion."""
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for audit in audits:
        for requirement in audit["requirements"]:
            if requirement["status"] != "remaining":
                continue
            for code in requirement.get("course_options", []):
                candidates[code].append(requirement)
            criterion = _criterion_key(requirement)
            if criterion:
                candidates[criterion].append(requirement)

    overlaps: list[dict[str, Any]] = []
    for candidate, requirements in candidates.items():
        majors = sorted({requirement["major"] for requirement in requirements})
        if len(majors) < 2:
            continue
        unique_requirements = {
            requirement["id"]: requirement
            for requirement in requirements
        }
        requirements = list(unique_requirements.values())
        explicit_course = bool(
            __import__("re").fullmatch(r"[A-Z]{2,4}\s+\d{3}[A-Z]?", candidate)
        )
        credits = min(
            (
                requirement["credits_remaining"] or requirement["credits_required"] or 3.0
                for requirement in requirements
            ),
            default=3.0,
        )
        overlaps.append(
            {
                "course_code": candidate,
                "majors": majors,
                "requirement_ids": [requirement["id"] for requirement in requirements],
                "requirement_names": [requirement["name"] for requirement in requirements],
                "potential_credits": round(credits, 2),
                "reason": (
                    f"{candidate} appears in the remaining course options for "
                    f"{' and '.join(majors)}."
                    if explicit_course
                    else f"One approved {candidate.removeprefix('ASU General Studies ')} "
                    f"course may satisfy the same remaining area for {' and '.join(majors)}."
                ),
            }
        )

    return sorted(
        overlaps,
        key=lambda overlap: (-len(overlap["majors"]), -overlap["potential_credits"], overlap["course_code"]),
    )


# Backward-compatible name for code that imported the original function.
def compute_overlap(majors_requirements: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    audits = [
        {"name": major, "requirements": requirements}
        for major, requirements in majors_requirements.items()
    ]
    overlaps = compute_overlaps(audits)
    return {"overlaps": overlaps, "optimized_plan": overlaps}
