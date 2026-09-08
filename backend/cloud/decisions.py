"""Pure saved-edit replay. No SQLite, auth, or filesystem operations."""
from typing import Any

def apply_saved_decisions(
    plan: dict[str, Any],
    placements: list[dict[str, Any]],
    placeholders: list[dict[str, Any]],
    term_settings: list[dict[str, Any]] | None = None,
    custom_courses: list[dict[str, Any]] | None = None,
    removed_course_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Re-apply saved edits to a freshly built plan.

    Order matters.  Term ceilings come first, because a saved move may only be
    legal under a ceiling the student raised.  Removals come next, so a class
    taken out stops occupying credits.  Then placeholder choices, added classes,
    and finally moves.

    Decisions are applied only where they still make sense.  A saved move to a
    term that no longer exists, or for a course the audits no longer require, is
    ignored rather than resurrected, so an updated audit cannot be overridden by
    a stale decision.  A move that no longer fits its term is still applied and
    reported, not silently dropped: the saved plan is what the student decided,
    and quietly relocating their class would be worse than telling them the
    term is over its ceiling.
    """
    term_settings = term_settings or []
    custom_courses = custom_courses or []
    removed = set(removed_course_ids or [])
    terms = {semester["term"]: semester for semester in plan["semesters"]}
    chosen = {item["slot_id"]: item for item in placeholders}
    moves = {item["course_id"]: item for item in placements}
    applied = 0
    skipped: list[str] = []
    known={c['id']:c for semester in plan['semesters'] for c in semester['courses']}
    for identity in (set(chosen)|set(moves)|removed)-set(known):
        skipped.append(f"A saved decision no longer matches this audit: {identity}.")
    removed={identity for identity in removed if known.get(identity,{}).get('movable',False)}
    min_credits = plan.get("min_credits", 13)

    # 1. Term ceilings and MCAT flags.
    for setting in term_settings:
        semester = terms.get(setting["term"])
        if semester is None:
            skipped.append(f"{setting['term']}: no longer in the planning window")
            continue
        semester["credit_limit"] = int(setting["credit_limit"])
        semester["is_mcat_term"] = bool(setting.get("is_mcat_term"))
        if setting.get("note"):
            semester["note"] = setting["note"]
        applied += 1

    # 2. Classes the student took off the map.
    for semester in plan["semesters"]:
        keep = [course for course in semester["courses"] if course["id"] not in removed]
        if len(keep) != len(semester["courses"]):
            applied += len(semester["courses"]) - len(keep)
            semester["courses"] = keep
            semester["total_credits"] = round(
                sum(course["credits"] for course in keep), 2
            )

    # 3. Resolve a slot to a specific course.
    #
    # This applies to any slot that still offers a choice, not only to unnamed
    # placeholders. The unit builder now names a concrete course whenever DARS
    # lists a small enough set — "COURSE LIST: MGT 300 MGT 303" becomes MGT 300
    # with MGT 303 offered alongside — and a student who prefers the alternative
    # has to be able to say so. Gating on `is_placeholder` would show them an
    # alternative they could not select.
    #
    # Two outcomes, and the difference matters. Normally the slot becomes the
    # chosen course. But when that course is already somewhere on the map, the
    # student chose a double-count: one class covering two requirements. Then the
    # slot has to disappear and the class already planned picks up the extra
    # requirement, or restoring the plan would silently add a second copy of a
    # class they only intend to take once.
    for semester in plan["semesters"]:
        for course in list(semester["courses"]):
            choice = chosen.get(course["id"])
            if not choice:
                continue
            if not course.get("is_placeholder") and not course.get("alternatives"):
                continue

            host = next(
                (
                    item
                    for stage in plan["semesters"]
                    for item in stage["courses"]
                    if item["id"] != course["id"] and item["code"] == choice["course_code"]
                ),
                None,
            )
            if host is not None:
                skipped.append(f"{choice['course_code']} is already planned; double-counting requires advisor approval. The reserved slot remains unresolved.")
                continue
            if course.get('alternatives') and choice['course_code'] not in course['alternatives']:
                skipped.append(f"{choice['course_code']} is not a listed alternative; the reserved slot remains unresolved.")
                continue
            course["code"] = choice["course_code"]
            course["label"] = choice["course_code"]
            course["is_placeholder"] = False
            course["resolved_from_placeholder"] = True
            if choice.get("note"):
                course["note"] = choice["note"]
            applied += 1

    # 4. Classes the student added that no audit asked for.
    for custom in custom_courses:
        target = terms.get(custom["term"])
        if target is None:
            skipped.append(
                f"{custom.get('label') or custom['course_id']}: "
                f"{custom['term']} is no longer in the planning window"
            )
            continue
        if any(course["id"] == custom["course_id"] for course in target["courses"]):
            continue
        target["courses"].append(
            {
                "id": custom["course_id"],
                "code": custom.get("code", ""),
                "subject": "",
                "catalog_number": "",
                "label": custom["label"],
                "credits": float(custom.get("credits", 0.0) or 0.0),
                "majors": list(custom.get("majors") or ["Added by hand"]),
                "requirement_ids": [],
                "is_placeholder": False,
                "status": "personal",
                "movable": True,
                "prerequisites": [],
                "corequisites": [],
                "attributes": [],
                "advisories": [],
                "justification": custom.get("note", "") or "Added to the map by hand.",
                "sequenced_by": "",
                "class_search_url": "",
                "resolved_from_placeholder": False,
                "note": custom.get("note", ""),
            }
        )
        target["total_credits"] = round(
            target["total_credits"] + float(custom.get("credits", 0.0) or 0.0), 2
        )
        applied += 1

    # 5. Moves.
    for course_id, move in moves.items():
        target = terms.get(move["term"])
        if target is None:
            skipped.append(f"{move.get('course_code') or course_id}: term no longer in plan")
            continue

        source = next(
            (
                semester
                for semester in plan["semesters"]
                for item in semester["courses"]
                if item["id"] == course_id
            ),
            None,
        )
        if source is None:
            continue
        course = next(item for item in source["courses"] if item["id"] == course_id)
        if course.get('movable',True):
            course['credits']=float(move.get('credits',course['credits']))
        if source["term"] == target["term"]:
            continue
        if not course.get("movable", True):
            continue

        source["courses"] = [item for item in source["courses"] if item["id"] != course_id]
        source["total_credits"] = round(source["total_credits"] - course["credits"], 2)
        target["courses"].append(course)
        target["total_credits"] = round(target["total_credits"] + course["credits"], 2)
        applied += 1
        if target.get("is_unplaced"):
            continue
        if target["total_credits"] > target["credit_limit"] + 0.01:
            skipped.append(
                f"{target['term']} is over its {target['credit_limit']}-credit ceiling "
                f"at {target['total_credits']:g}. Raise the ceiling or move a class out."
            )

    for semester in plan["semesters"]:
        # The holding area is not a term, so it has no floor to fall under.
        if semester.get("is_unplaced"):
            continue
        if semester["courses"] and not semester["is_in_progress"]:
            if semester["total_credits"] < min_credits:
                skipped.append(
                    f"{semester['term']} holds {semester['total_credits']:g} credits, "
                    f"under your {min_credits}-credit minimum."
                )

    for semester in plan['semesters']:
        semester['total_credits']=round(sum(c['credits'] for c in semester['courses']),2)
    plan['planned_credits']=round(sum(s['total_credits'] for s in plan['semesters'] if not s.get('is_unplaced')),2)
    plan["applied_decisions"] = applied
    if skipped:
        plan["warnings"] = list(dict.fromkeys([*plan.get("warnings", []), *skipped]))
    return plan
