# Academic coverage and intentional corrections

The original Finance, Neuroscience and Barrett private fixtures remain on the machine and all original regression tests are retained locally. They are not copied into the published repository. The public test suite uses generated synthetic PDFs/text spanning majors, minors, certificates, honors, catalogs and unfamiliar programs.

The hosted engine is separate from the legacy orchestration. It does not inherit pre-med, MCAT dates, a credit floor, dance or Finance decisions. Personal decisions require explicit preferences. Catalog-specific prerequisite knowledge is limited to the catalogs represented in the existing sources. Unknown prerequisites and course offerings are not invented. Overlap is an opportunity to review, not automatic permission to double-count.

Program identity uses report metadata; catalog and campus are part of deduplication. Newer equivalent reports use their prepared timestamp. Requirement identifiers do not depend on filenames or report timestamps. Compatible saved decisions are replayed only from the same owner's matching program/catalog set; unmatched IDs are reported. Title-only requirements can still change identity when wording changes. The tool cannot reliably reconcile arbitrary semantic changes in DARS.

Numbered nested requirements retain parent IDs and source evidence. Parent aggregates are not scheduled again on top of their children. Partial requirements retain remaining credits. Single named courses preserve explicit credit amounts; labs use known credit values; unknown elective pools remain estimated credit allocations. Uninterpreted unmet conditions remain visible and block unqualified readiness. Some unusual non-course sections, boolean alternatives, transfer articulation, minimum-grade rules and repeat-credit policies still need human interpretation. Do not treat synthetic coverage as university-wide validation.

Intentional corrections in the hosted flow:

- No unqualified `on_track`: every result states that advisor review is required.
- Placeholder choices cannot silently merge with an already-planned course. Previously the local editor treated that choice as a double-count.
- A reserved slot can only be filled from the courses its requirement lists. The editor and the server's replay now apply that one rule, so a typed-in substitution is refused with a reason instead of appearing to work and vanishing on the next load. An advisor-approved substitution has to be recorded in DARS before the tool will schedule it.
- Per-term credit edits persist through replay; conflict detection prevents a stale tab from replacing newer edits.
- The pre-health majors chemistry route includes CHM 111 and CHM 112 labs with CHM 117/118.
- Statistics is marked recommended, not a universal medical-school prerequisite.
- Writing uses the documented ENG 101/102 or ENG 105 plus HON 171/ENG 301 pathways. HON 272 is no longer assumed interchangeable without school/advisor evidence.
- Credit overload alerts are workload prompts, not a universal claim about every college's approval threshold.

Sources checked August 28, 2026: [pre-health curriculum](https://prehealth.asu.edu/future-students/curriculum) and the repository's attributed catalog/advisor rules. Medical schools set their own admission prerequisites, including treatment of AP, transfer and online credit. This curriculum is not a blanket guarantee of acceptance by a target school.

Before expanding the pilot, build a consented and deidentified audit corpus across colleges/catalogs, have advisors label expected requirements and schedules, record false omissions and false completion claims, and gate each newly supported format. Graduate programs and OCR are outside this pilot.
