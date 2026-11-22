# INDEPENDENT_LIMITS.md — what this verification cannot prove (task-4, verifier2)

This is the "could not verify" list that REVIEW.md points at. It is written before the
summary so that a reader can discount the right things. Every entry says *what* is not
proven and *why*, not merely "limited time".

## 1. The hidden cases are unknown

The organizer runs three **hidden, fixed** cases; the platform installs the Skill at
`/skills/weekly-skill` and feeds `/input/case.json` plus material files. Nothing in this
workspace contains those cases, their materials, or their expected outputs. My fixtures
(`work/fixtures/case-a-mechanism`, `case-b-chart`, `case-c-edit`) mirror the *workorder*
(relationship schematic from a primary biological source; chart from real source data;
source-preserving edit) but they are **my stand-ins, not the organizer cases**. A defect
that only manifests on PDF-heavy, OCR-bound, multi-table, or much larger inputs will not
have been seen here. Consequently:

* "the Skill passes the three local fixtures" ≠ "the Skill will pass the hidden cases";
* fixture-pass rate cannot be converted into an expected score.

## 2. The platform runtime may differ from this machine

Locally `matplotlib`, `PIL`, `pypdf`, `numpy`, `reportlab`, `pandas`, `svglib` are present
(`runs/case-a/work/environment.json`) and the export matrix produces EPS/PDF/PNG/SVG/TIFF.
The frozen contract (CONTRACT.md §1) allows the platform to lack any of them. I verified
the *honest-degradation path* only indirectly (the code records `status="unavailable"` per
format), not on a machine where the libraries are actually missing; I did not simulate a
stripped runtime. If the official runtime lacks matplotlib, the deliverable set shrinks and
the compliance verdicts here would not transfer.

## 3. No human visual judgement was applied

Every PASS in REVIEW.md is derived from bytes: PNG chunks, the SVG DOM, pypdf-extracted
text and fonts, JSON fields, and a geometric check that a relation's drawn head sits at the
`to` node. **Nobody looked at the rendered figures.** A figure can satisfy all of these and
still be scientifically misleading (misleading axis truncation — see the observation in
REVIEW.md — clashing colours, unreadable label collision that the estimator accepts,
ambiguous grouping). The rubric says the scientific judgement is the LLM Judge's job; this
verification does not substitute for it.

## 4. What "detected" means in the negative harness

For the 13 model/layout defects the detector is the candidate's own gate; my independent
contribution is (a) that the injected defect is real (the mutated JSON provably differs
from the pristine model, the mutated layout is provably overlapping / off-canvas, the
mutated PDF/PNG is provably missing fonts / at 72 dpi) and (b) that the expected code was
**not already firing on the pristine input** (anti-vacuity baseline). It does **not** prove
that the gate would catch a defect I did not think of, and 20 hand-written defects are a
sample, not exhaustive coverage. In particular there is no fuzzing in my harness beyond the
20 seeds; the other owners' fuzz runs (`work/dev/layout-render/fuzz_layout_render.py`) are
their evidence, not mine, and I did not re-execute them.

## 5. Claims about the platform, not the artifact

I cannot verify locally: that the Skill actually loads from `/skills/weekly-skill`, that the
platform's trigger/description matching selects it, that `/input` is mounted as assumed, the
64-request / 900-second / 16384-token budgets, bundle-gate results at submission time
(`bh.py gate`, trace G10 — those need the submission pipeline and a real trace), or the
platform's own scoring. REVIEW.md therefore marks these UNVERIFIED rather than PASS, even
where the local evidence is suggestive.

## 6. Scores and comparisons are single-sample

* The baseline comparison is **one naive implementation per figure kind**, run once, on one
  machine, timed once (`BASELINE.md` §4). Wall-clock deltas smaller than a few tenths of a
  second are noise; the "Skill is 5×–40× slower" statement is well outside that, but the
  exact factor is not a portable number.
* A single fixture pass/fail is not a rate. There is no repetition, no seed sweep, and no
  second independent naive baseline, so no statistical claim is made.
* The workspace is being written concurrently by other agents. My numbers are pinned to the
  submission `tree_sha256` printed in each run (see REVIEW.md "Freeze"), and the freeze
  script (`hash_snapshot.py --compare`) is the gate that would detect a later drift. Any
  claim here is only about that revision.

## 7. Self-reported evidence I did not re-derive

I treated the other owners' files (`work/dev/**`) as leads, not as evidence. Their numbers
(87 assertions, 16 check ids, 250 fuzz models, …) are **their** claims; I did not re-run
their scripts. Where I cite a fact it is because I re-derived it myself, and the command or
`file:line` is in REVIEW.md.

## 8. Things this file deliberately does not inflate

* The provenance gate's ability to stop *invented* content is verified (PASS) — but its
  inability to stop a *verbatim-token junk* draft is also verified (observation in
  REVIEW.md). Both belong in the final report.
* The compliance gate passing 16/16 does **not** mean the figure is publishable; it means
  16 mechanical checks passed. That distinction is the whole reason this file exists.
