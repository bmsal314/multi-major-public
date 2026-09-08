# How an audit becomes a semester map

The path from an uploaded PDF to a term-by-term plan, and the reasoning behind
the parts that are not obvious. Written for whoever changes this next.

```
PDF bytes
  └─ pdf_parser.extract_text_bytes        pdfplumber, page-ordered text
  └─ pdf_parser.parse_dars_text
       ├─ strip identifying header lines, emails, long digit runs
       ├─ asu_catalog.DesignationVocabulary.learn(lines)   ← layer 1
       ├─ _parse_requirement_blocks → _block_to_requirement
       │    ├─ options, wildcards, exclusions, capped sub-lists
       │    ├─ required_count  ("Complete 2 courses", "- two courses")
       │    └─ asu_catalog.categorize(...)  → category → kind
       └─ coverage_report(...)             every requirement accounted for
  └─ planning_units.build_units            requirements → schedulable slots
  └─ semester_planner.generate_plan        slots → terms
  └─ plan_summary.summarize                one comparable row per permutation
```

## Reading requirements

### Designations are learned, not looked up

ASU has already replaced the legacy General Studies set
(`HU`/`SB`/`SQ`/`MA`/`CS`/`L`) with Gold
(`HUAD`/`SOBE`/`SCIT`/`QTRS`/`MATH`/`AMIT`/`CIVI`/`GCSI`/`SUST`). Audits from
adjacent catalog years carry both at once, and the next revision will land the
same way — silently, inside a student's PDF, before anyone updates this
repository. So `KNOWN_DESIGNATIONS` in `backend/asu_catalog.py` is a *prior*,
never the authority.

Resolution runs in three layers, most trustworthy first:

1. **The document.** DARS states its own vocabulary twice — an all-caps section
   heading, then a numbered requirement repeating the same words with the code
   in parentheses:

   ```
   University General Studies Requirement - Gold
   SOCIAL AND BEHAVIORAL SCIENCES
   1) Social and Behavioral Sciences (SOBE): 3 hours
   ```

   A definition is accepted only when the document says it *both* ways. That
   rule is what stops `JMC 201: News Reporting and Writing (L)` from teaching us
   that `L` means "News Reporting and Writing" — there is a regression test for
   exactly that. A code ASU invents next year is learned on first sight, with
   the real name the report gives it.
2. **The known table**, for a code used only in passing — inside a course list,
   say — that the document never defines.
3. **Shape.** A parenthesised token in a General Studies context that is neither
   learned nor known is still recognised as a designation, kept, and marked
   `discovered`, so it is scheduled and shown rather than dropped.

Codes new to the shipped table are surfaced as a warning on the audit. A
designation revision should announce itself, not quietly degrade every plan
built from that catalog year.

### Categories: structure decides before wording

`categorize()` assigns exactly one of `CATEGORIES` to every requirement, and
**shape is consulted before vocabulary**. A block that lists eight courses and
needs three is a pool the student chooses from, whatever it calls itself. That
is how Dance's *Personal Movement Practice* is recognised as an elective
despite never using the word:

| Signal | Meaning |
|---|---|
| `option_count > required_count` | a choice pool → `elective_constrained` |
| `option_count == required_count` | every listed course is required → `major` |
| wildcards present | a level-and-prefix slot → `elective_constrained` |
| no options at all | fall back to wording, then to the lexicon |

Only when the shape says nothing does phrasing get a vote, and the phrase list
is the growing lexicon rather than a fixed set.

There is **no silent fall-through**. Anything unrecognised becomes
`unclassified`, which is still schedulable and is reported in the audit's
`coverage` block. A slot a student can see and question beats a requirement
that quietly stopped existing — which is precisely the failure this rebuild
exists to correct.

### The lexicon grows; it never overrules

`backend/lexicon.py` accumulates subject prefixes, designation codes and
elective phrasings across audits as an **additive prior**. It cannot override
layers 1 or 2, so the same PDF yields the same requirements whether or not the
lexicon has ever seen its program — parsing stays deterministic and reviewable.

Only vocabulary is retained. A stored phrase must contain an academic token
(`elective`, `capstone`, `practice`, …), which is why `"Jordan Rivera"` and
`"Student ID 1234517910"` are both rejected by `_clean_phrase`. Nothing is
written during a request; growth happens only when `learn_from()` is called
offline over a corpus.

### Things DARS says that are easy to misread

| Written as | Means | Handled by |
|---|---|---|
| `COURSE LIST: MGT 300 MGT 303` | choose one of two named courses | resolved to a concrete course, the other offered as an alternative |
| `AEE OR MAE OR MEE 3** Elective` | any 300-level course from three prefixes | `wildcard_patterns_in`, kept as a first-class pattern |
| `Students may choose no more than one course from the following:` | a **cap** on a sibling list | category `constraint`; never scheduled |
| `Complete 2 courses:` | the same category satisfied twice | `required_count` |
| `-> NOT FROM: DCE 133 …` | exclusions | removed from the option list |
| `FIN 493 FIN 499 COURSE LIST: …` | an exclusion line, *not* "499 courses" | `COURSE_COUNT_RE` caps counts at two digits |

## Building slots

`planning_units.build_units` turns requirements into schedulable units.

* **Name a course whenever DARS names one.** A pool of at most
  `MAX_OPTIONS_TO_RESOLVE` (4) resolves to a concrete course with the rest
  offered as alternatives, so the student gets a course code and a working
  Class Search link. A larger pool stays a labelled slot — choosing two of
  twenty-one advanced-skills courses is the student's decision, and pretending
  otherwise is a worse answer than an honest placeholder.
* **Never drop a slot.** An unnamed elective, an unresolved condition, a block
  that could not be categorized: each still becomes a unit carrying its hours.
* **Every slot gets its own identity.** Splitting a nine-hour block into three
  fragments that shared one code corrupted `placed_at` and made the fragments
  sort adjacently, which is what packed electives into a single term.
* **Merge across programs, never within one.** A double major is not told to
  take Sustainability twice. DARS does not say a course may double-count
  *inside* one program, so that is never assumed.
* Labels are bounded at `MAX_SLOT_LABEL`; a longer area name falls back to its
  bare code, with the full name kept on the slot's criteria.

Substitutions (`course_rules.COURSE_SUBSTITUTIONS`) run last. The W. P. Carey
career-prep rule is the current example: DARS lists WPC 148 and WPC 248 as
separate quarter-credit requirements and offers WPC 347 only as an alternative
to the second, which reads as though a continuing student should take all
three. WPC 347 is the half-credit course covering both, so for any student past
`NON_FRESHMAN_EARNED_HOURS` it replaces them.

## Placing slots in terms

`semester_planner.generate_plan` is deterministic and runs in two stages.

**Placement** puts each unit in the earliest term it actually fits, honouring
prerequisites, corequisites and advisor-named terms. Balancing is deliberately
*not* folded in here: doing so made placement non-monotonic, and a one-credit
lab could leapfrog into a later term whose share of the target was still
unspent, stranding it a semester away from its lecture.

**Rebalancing** (`_rebalance_terms`) then moves work *later* as well as
earlier, out of terms above their share and into terms below it. This is the
direction the old `_top_up_light_terms` could never go — it only pulled work
earlier, reinforcing the very skew it was meant to relieve.

Two guards keep balancing from doing harm:

* `_settled_targets` computes shares only across the **horizon** the work
  actually needs. Spreading two classes evenly over six terms is arithmetically
  even and academically absurd; balance must not delay graduation to flatten a
  graph.
* `_can_move` refuses to break a prerequisite chain, separate a lecture from its
  lab, move an advisor-sequenced course, or drop a term under the full-time
  floor.

### Ceilings

All four are named constants, all four are overridable per user, and none is
tied to a particular program.

| Constant | Default | Preference |
|---|---|---|
| credit ceiling | 15 | `credits_per_term`, `term_credit_limits` |
| `DEFAULT_TERM_COURSE_CEILING` | 6 | `course_ceiling`, `term_course_limits` |
| `DEFAULT_MCAT_CREDIT_CEILING` | 12 | `mcat_credit_ceiling` |
| `DEFAULT_MCAT_COURSE_CEILING` | 4 | `mcat_course_ceiling` |

* **The class ceiling is not redundant with credits.** Only credits were ever
  checked before, so a term could hold fifteen entries totalling six credits.
* It counts **load-bearing** classes (`COUNTED_CLASS_MIN_CREDITS`), so ASU's
  quarter-credit career modules do not crowd out real coursework, and it
  **scales with the credit ceiling the student chose** rather than overruling
  it — someone setting a 30-credit term is asking for more than six classes.
* **Zero-credit gates consume neither ceiling.** A thesis approval is not a
  class you attend, and counting it pushed the very milestone that must stay
  visible off the end of the map.
* **The MCAT term's load is the student's call.** The flag used to be written
  and never read, so the exam term carried the ordinary ceiling and reliably
  came out overloaded. It now sets that term's ceiling, and the student is
  asked for the number when they tick pre-med. It is applied exactly as given,
  in either direction. Precedence: an explicit `term_credit_limits` entry beats
  the MCAT ceiling, which beats the global ceiling.

## Two engines, one of which is live

`backend/analysis.py` (`analyze_documents` → `build_planning_units`) is the
legacy local path, reached only through `backend/legacy_app.py`, which
`backend/main.py` does not mount. **Everything a real user sees comes from
`backend/cloud/engine.py::build_result`**, which now delegates unit building to
`planning_units.build_units`.

Both paths share the parser and `generate_plan`, so parser and planner fixes
reach both. Unit-building does not: a change to `build_planning_units` alone
changes nothing for a real user. Collapsing the two is the obvious follow-up
and is not done here.

## Where things are

| File | Role |
|---|---|
| `backend/asu_catalog.py` | designations, categories, wildcards, caps |
| `backend/lexicon.py` | the growing, privacy-filtered vocabulary |
| `backend/pdf_parser.py` | PDF → requirements + coverage |
| `backend/planning_units.py` | requirements → schedulable slots |
| `backend/semester_planner.py` | slots → terms, ceilings, balancing |
| `backend/plan_summary.py` | one comparable row per permutation |
| `backend/course_rules.py` | advisor tracks, equivalences, substitutions |
| `tests/fixtures/synthetic_dars.py` | fixtures generated from real major maps |
| `tests/reports/phase0_audit_summary.md` | the root-cause audit this rebuild answers |
