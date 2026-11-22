# REVIEW.md — independent verification of the `scientific-editable-schematic` Skill

**Task:** `task-4` (verifier2). **Scope:** read-only on `work/submission/**`; I write only
`work/verify/**`, `work/fixtures/**`, `work/freeze/**`.

**Revisions.** The workspace is written concurrently by other agents, so I pinned two hashes:

* **code-verified revision `9527198453fd791d61dd216fd15785dbffc91e52464a386dbf0e64de1f1e0e8b`** —
  every suite below was executed against this tree, and the hash was identical before and after the
  run (`work/verify/_pin_before.json` / `_pin_after.json`).
* **final frozen tree `d60fb267252a48b1b4f24407df57da0f515f6480eaace1a22bb565aeb7ab5de8`**
  (24 files, 620 415 bytes, no `__pycache__`, no symlink, no author-machine absolute path) —
  written to `work/freeze/source_hashes.json`. The only post-verification change is
  `references/layout_and_svg.md` (documentation; it is not executed by any check and is covered by
  C14 = UNVERIFIED). Any further write to `work/submission/**` invalidates the correspondence and
  is detected by `py -3 work\verify\hash_snapshot.py --compare` (exit 0 = identical, exit 1 =
  added/removed/changed printed). **That gate already fired twice during this task** (layout.py
  at 03:12, `references/layout_and_svg.md` at 03:17), which is how the drift was caught; before
  submission the Lead must get exit 0 or re-run the suites.

Three states are used strictly. `PASS` = I executed the check and it passed. `FAIL` = I executed
it and it failed. `UNVERIFIED` = I did **not** execute it (or cannot execute it here) — it is never
written as PASS. `N/A` = the property does not apply to this deliverable.

Every PASS is backed by a reproducible command or a real `file:line`. No PASS rests on the
candidate's own checker: the positive path is checked by parsers written in
`work/verify/harness.py` (stdlib `xml.etree`/`struct`/`hashlib` + `pypdf`/`Pillow`), and the
candidate's gates appear only where they are the object under test (the negative list).

## 1. Result summary

| suite | command | result |
|---|---|---|
| positive end-to-end (3 fixtures, real CLI) | `py -3 work\verify\harness.py run` | **70 PASS / 0 FAIL / 0 UNVERIFIED**, exit 0 (case-a 26, case-b 29, case-c 15) |
| adversarial negatives | `py -3 work\verify\harness.py negative` | **20 injected, 20 detected, 0 vacuous skips, 20 injections independently proven real**, exit 0 |
| freeze / anti-drift | `py -3 work\verify\hash_snapshot.py --compare` | `identical: true`, exit 0 |
| candidate selftest (re-run by me) | `py -3 work\submission\scripts\selftest.py` | `PASS (65 passed, 0 failed, 0 unavailable, 0 vacuous skips)`, exit 0, 84.8 s |
| skill-submission validator (re-run by me) | `py -3 D:\Borium_Contest\_shared\tools\validate_skill_submission.py work\submission` | `status: ok`, 24 files, 620 415 bytes, exit 0 |
| bundled example chain (re-run by me) | `run.py prepare→render→export(--journal nature --dpi 300)→finish --strict` | exit 0/0/0/0, `status=ok`, `missing_required_fields=[]`, 16/16 checks, `result.json` self digest recomputable, artifacts re-hash OK (`work/verify/runs/examples3/`) |
| fair baseline comparison | `py -3 work\verify\baseline_run.py --cases case-a,case-b` | Skill 7/7 directed edges typed, 24/24 and 7/7 provenance, **0 manual repairs**; naive baseline 4/7 endpoints, 0/7 typed, 0 provenance, 7 repairs |

**Overall gate verdict: CONDITIONAL.** Every check I could execute locally passes and no defect
found during this task remains unfixed, so there is no blocker-level FAIL. ACCEPT is not
available to me because several platform-level properties are UNVERIFIED (§5) and no human
visual judgement was applied (`INDEPENDENT_LIMITS.md` §3).

## 2. Claim-by-claim verdicts

### 2.1 Interface and process contract

| # | claim | verdict | evidence |
|---|---|---|---|
| A1 | the real entry point is `scripts/run.py` with `prepare/render/export/edit/finish`, not just importable modules | PASS | every suite drives `py -3 work/submission/scripts/run.py <stage>` as a subprocess (`work/verify/harness.py:cli`, `_run` evidence in `work/verify/_run.out`); no suite imports the stages to run them |
| A2 | stdout of each stage is exactly one JSON object | PASS | `harness.py:parse_single_json` demands the whole stream decode as one object; all 30+ invocations satisfy it (checks `P02_stdout_single_json`) |
| A3 | exit codes follow CONTRACT.md:45-49 (0 ok / 2 config / 3 env-blocked / 4 gate failure) | PASS | 0: `prepare/render/export/`finish on case-a/b/c and on `examples`; 4: all 13 model/gate negatives (`work/verify/_neg.out`, column `exit`); 3: `run.py prepare --input <empty>` → exit 3 with `result.json.status=needs_human`; 2: `render` with no model → exit 2, `edit` with `target: ent:e_nope` → exit 2 (commands in `work/verify/runs/exitcodes/`, raw stdout in `_run.out`) |
| A4 | the declared artifacts of §3 are really produced | PASS | `runs/<case>/out/` contains `figure_model.json`, `figures/{svg,pdf,png,tiff,eps}`, `source_map.json`, `change_log.json` (edit only), `export_report.json`, `checks.json`, `result.json`; formats listed in check `P08_export_formats` |
| A5 | `result.json` keeps every original `output_contract` key and `case_id` | PASS | check `P10_output_contract_filled`: all three fixtures report `missing_required_fields=[]` and non-empty values for every contract key; `case_id` matches the fixture `case.json` |
| A6 | declared artifact digests match the bytes on disk | PASS | check `P11_artifact_hashes_reverified` re-hashes each entry with `hashlib` in `harness.py` (excluding the self-referential `result` entry, which is checked separately) |
| A7 | `result.json`'s self digest is independently recomputable | PASS | I implement the documented basis myself (`harness.py:verify_self_hash`): null `artifacts[key=result].{sha256,bytes}`, canonical JSON, sha256 → equals the recorded value for case-a/b/c and for `examples` (checks `P11b`, `C15`; evidence `work/verify/harness_results.json`) |
| A8 | the unrevised draft is never presented as a finished figure | PASS | `render` with only the draft → `status=partial` (`run.py:441-443`); `finish --strict` with the draft → exit 3, `status=partial`, `limitations=["the model was not revised by an agent; it is the raw draft"]` (`run.py:853`, `run.py:859-860`); measured in `runs/case-a/draft_out/result.json` |
| A9 | `prepare` honestly flags what needs the agent's judgement | PASS | `REVIEW_BATCH.json` has 6 (case-a) / 7 (case-b) `must_decide` entries; draft `uncertainty` non-empty (20 / 3); early `result.json.status=partial` (`runs/case-*/out/result.json`) |

### 2.2 The three checkable points of the workorder

| # | claim | verdict | evidence |
|---|---|---|---|
| B1 | every drawn element is bound to a source or explicitly marked unsupported | PASS | check `P13_svg_elements_have_provenance`: 35 drawn schematic elements / 0 without `data-prov`+`data-src-kind` (case-a); check `B07`: 3/3 chart marks carry a `derived` binding in the SVG **and** a matching `source_map.json` entry (case-b, `source_map` bound=11 unsupported=0) |
| B2 | invented content is blocked (anti-hallucination) | PASS | negatives `N01 invented_gene` → `E_LABEL_NOT_IN_SOURCE`, `N02 quote_absent` → `E_QUOTE_NOT_FOUND`, `N09 number_not_in_source` → `E_NUMBER_NOT_IN_SOURCE` (13 model defects; see `work/verify/_neg.out`) |
| B3 | activation/inhibition/causation directions match the source verb and are not inverted | PASS | `N03` flipping `MDM2 ⊣ p53` to activation → `E_DIRECTION_UNSUPPORTED`; `N04` reversing the ATM→CHK2 hierarchy → `W_AMBIGUOUS_LEVEL`; `N05` containment drawn as a parallel edge → `E_ORPHAN_RELATION`; on the positive side `A03_relation_head_at_target_node` recomputes, from the SVG geometry alone, that every one of the 9 relation heads sits at its `to` node, and `A04` that inhibition is a tee and activation an arrow |
| B4 | module membership is containment, not an arrow | PASS | `A02_three_containers_drawn` finds `cnt:c_sensor/c_nuclear/c_oncogenic` with members' rects inside the container rects (`layout.py:2859` reports a containment relation that is not visually contained); negatives `N05` (membership drawn as a parallel edge from the container id → `E_ORPHAN_RELATION`) and `N08` (container cycle → `E_CONTAINER_CYCLE`) |
| B5 | legend items == data categories, colours one-to-one | PASS | `B02` (3 legend items, 3 distinct table categories, all three named in the SVG), `B06` (legend swatch colour == series mark colour per taxon, read from the SVG); negatives `N11 legend_count_ne_categories` and `N12 colour_category_mismatch` → `E_LEGEND_DATA_MISMATCH` |
| B6 | units are explicit and taken from the source | PASS | case-a axis/values carry the source palette; case-b `B03_unit_cm_not_mm`: SVG shows `cm`, no bare `mm`, ticks 0–6; negative `N13_missing_unit` → `E_UNIT_MISSING`; case-c rename mm→cm with **no** numeric rescale (`C07`, `C08`) |
| B7 | values are derivable from the source data (mapping independently checkable) | PASS | `B04_plotted_values_recomputed` and `B05_drawn_series_values_match_recompute`: the `data-value` attribute of every drawn bar equals the mean I recompute from the fixture CSV (`1.464 / 4.260 / 5.552`) and from the model's own `data.rows`; `OBS_B08` confirms the axis is zero-based and the bar-height ratio (3.79) equals the data ratio (3.79) |
| B8 | a stale caption is not silently copied | PASS | `B09_stale_caption_conflict_reported`: the model reports the `figure.stale_caption` conflict (mm / missing taxon) as an uncertainty; the figure uses `cm` and three taxa; the naive baseline in `BASELINE.md` falls into the trap, so this is a discriminating test |
| B9 | editable source = layered SVG with real text | PASS | `P12_svg_wellformed_layered_text`: 7 `layer:*` groups, 27 `<text>`, 0 `<image>`, 0 `<use>`, 1 `<metadata>`; `render_svg.py:243` (layers), `:180` (`<text>`), `:718` (metadata); negatives `N19` (text→image) → `svg_editable_text`, `N20` (layers renamed) → `svg_layers` |
| B10 | multi-format compliant export, not just one PNG | PASS | `P08` (svg, pdf, png, tiff, eps), `P15` PNG dpi 299.9994 ≥ 300 (pHYs quantisation), `P16` every PDF font embedded (pypdf), `P17` page size matches the canvas, `P18` text extractable; negative `N16` (72 dpi artifact) → `raster_dpi` |
| B11 | a source-preserving edit keeps untouched content and records before/after | PASS | case-c: `C04` edit exit 0 `post_edit_error_codes=[]`; `C06` change log has one entry per op; `C07`–`C10` the three requested changes are applied (unit mm→cm, colour `#009E73`→`#CC79A7` consistently, row 6.6→6.2 with mean recomputed to 5.544); `C11` SVG/PDF/PNG hashes all change; `C12` every untouched id/label/value/colour/source/canvas/panel is preserved |
| B12 | provenance survives the edit | PASS | `C12` compares each untouched `entity.source` and `legend.source` before/after; `run.py:724-727` records `provenance_preserved` |
| B13 | the gate is honest when it fails | PASS | failures return exit 4 with `figure_issues.json` written and partial artifacts preserved (all 13 model negatives); `result.json` is written early as `partial` (`run.py:242`); a crash was never observed (negative check `NG01_no_tracebacks`, 20/20 runs) |

### 2.3 Reliability, robustness, ecosystem

| # | claim | verdict | evidence |
|---|---|---|---|
| C1 | deterministic rendering | PASS | `P06_render_deterministic`: two fresh renders of the same model produce a byte-identical SVG (sha256 compared in-run) |
| C2 | injected defects are caught by a *specific* code, not by crashes | PASS | 20/20 detected; each detection requires the expected code in the parsed JSON **and** (for element-scoped checks) the reported `where` to name the injected element; crash ⇒ no detection (`harness.py:run_negative`); anti-vacuity: none of the expected codes fires on the pristine model/layout/artifacts (recorded per defect as `preexisting_in_baseline`) |
| C3 | exception handling on bad input | PASS | empty input → exit 3 + `needs_human`; missing model → exit 2; unknown edit target → exit 2; unsupported op name → exit 2 (each with a single-JSON stdout and no traceback) |
| C4 | the shipped selftest is real end-to-end and its negatives are code-based | PASS | I re-ran it: `PASS (65 passed, 0 failed, 0 unavailable, 0 vacuous skips)`, exit 0, 84.8 s (`work/verify/_selftest.out`). Its negative loop asserts code intersection and treats a crash as a miss (`selftest.py:355-366`); the 72-dpi negative asserts the specific `raster_dpi` id (`selftest.py:380-382`). One weaker assertion noted in §3 |
| C5 | submission structure gate | PASS | `validate_skill_submission.py` → `status: ok`, 24 files, 620 415 bytes, exit 0; the five required literals (`/input/case.json`, `/app/output`, `result.json`, `case_id`, `output_contract`) are present in `SKILL.md` |
| C6 | resource limits of the frozen contract (≤50 files, ≤500 KB each, ≤2 MB total, no symlink) | PASS | measured independently: 24 files, total 620 415 B, largest 133 942 B (`scripts/layout.py`), 0 reparse points |
| C7 | no author-machine path leak, all text UTF-8 | PASS | independent scan with `(?<![A-Za-z0-9])[A-Za-z]:[\\/]`, `/Users/`, `/home/`, `AppData`, `Morrow`, `dsh-primary-runtime` over all 24 files → 0 hits; 0 non-UTF-8 files |
| C8 | no `__pycache__`/`.pyc` in the submission tree (hard gate G6) | PASS | `hash_snapshot.py --print` → `pycache_violations: []`; the freeze/compare gate also fails hard on any `__pycache__` |
| C9 | the bundled example chain works from a clean invocation | PASS | re-run by me: exit 0/0/0/0, `status=ok`, `missing_required_fields=[]`, 16/16 checks, `result.json` self digest recomputable, all other artifacts re-hash OK (`work/verify/runs/examples2/`) |
| C10 | the frozen JSON schemas describe the model the code accepts | PASS (behaviour) with a documentation gap | `schemas/figure_model.schema.json:142` defines `data.series.items` as a bare object, so a schema-conforming chart model carries no `series[].source`; this used to force `data-src-kind="unsupported"` (F2). The code now derives the binding itself (`layout.py:310-331 _series_provenance` → `<data.path>#table:<column|name>`, kind `derived`), so a schema-conforming model is accepted and properly bound. Residual: the optional `series[].source`/`series[].column` fields the code reads are still undocumented, and no script loads `schemas/**` (grep over `work/submission/scripts` → 0 hits), so schema drift is not machine-checked |
| C11 | documented behaviour matches observed behaviour (draft handling, SKILL.md:56-58) | PASS | re-verified on the frozen revision: `render` warns on stderr and returns `partial`; `finish --strict` exits 3 with the draft limitation. (At the earlier revision `802ed06f…` this claim was **false** — see §4 F3b; the Lead fixed it and I re-measured.) |
| C12 | the Skill is *better than a naive agent* on the same case | PASS | `BASELINE.md`: 7/7 vs 4/7 directed endpoints, 7/7 vs 0/7 typed, 24/24 vs 0/24 provenance, 5 vs 1 formats, 300 vs 150 dpi, correct unit/3 taxa vs stale caption, **0 vs 7 manual repairs** — while being 12.8×–120× slower (stated as a loss) |
| C13 | docs / references / schemas / examples exist and are non-trivial | PASS (structure) | `SKILL.md` 9.4 KB with valid frontmatter `name`/`description` (`SKILL.md:1-10`); 4 references (12–22 KB), 3 schemas, `examples/` with `case.json` + `expected_model.json` + materials; README 7.6 KB |
| C14 | the *quality of the prose* in `references/**` is correct and complete | UNVERIFIED | I read `SKILL.md` and the schemas in full, but I did not review all 51 KB of `references/**` line by line; no check exercises it |
| C15 | a public GitHub link (+5 rubric) exists | UNVERIFIED | nothing in `work/submission/**` contains a repository URL that I can validate, and I cannot verify a public link from this sandbox; the platform claim is out of my scope |
| C16 | the Skill loads from `/skills/weekly-skill` and the platform triggers it | UNVERIFIED | requires the official runtime; I only verified the structural frontmatter and that the CLI works from an arbitrary `--input/--work/--output` |
| C17 | behaviour on the three hidden organizer cases | UNVERIFIED | the cases are not in this workspace; my fixtures are stand-ins (see `INDEPENDENT_LIMITS.md` §1) |
| C18 | behaviour when matplotlib/Pillow/pypdf are absent | UNVERIFIED | all four are present here (`runs/case-a/work/environment.json`); the degradation path is only read, never executed on a stripped runtime |
| C19 | the figure is scientifically *readable and misleading-free* | UNVERIFIED | no human visual judgement was applied; mechanical checks cannot decide it (`INDEPENDENT_LIMITS.md` §3) |
| C20 | bundle gate `bh.py gate` / trace G10 pass at submission time | UNVERIFIED | requires the submission pipeline and a real exported trace; not in my scope (Lead's) |

## 3. Observations (measured facts that are not acceptance criteria)

1. **The unrevised draft is source-bound, not rejected.** On the draft, case-a `render`
   historically returned exit 0 / `status=ok` / 0 errors with all 36 draft entities bound
   (46/46 elements, 0 unsupported) — the provenance gate cannot distinguish a verbatim-token
   draft (entities named `Fixture`, `GOLD`, `Every`, `Core`, `In`) from a revised model, because
   every token really is in the markdown source. The revision *requirement* is now enforced at
   the stage boundary (`status=partial`, `strict` exit 3), but the *content* of the revision is
   still unverifiable by the gate. This is inherent to a provenance-only check and worth stating
   in the final report rather than hiding.
2. **No `set_value`/`set_number` edit op.** `run.py:_ALLOWED_OPS` offers
   `set_label/set_color/set_unit/set_attribute/...` but nothing that writes `entities[].value`;
   `_FIELD_FOR_OP` has no `value` entry. A data correction therefore updates `data.series` and
   (via `set_attribute`) `attributes`, while the entity's own `value` stays at the old number.
   My case-c ops hit exactly this: `e_virginica.value` remains 5.552 while the plotted series is
   5.544. Low impact for chart rendering (the chart reads `data.series`), but the delivered model
   can contain two different numbers for one quantity.
3. **`selftest.py:390-391` asserts only `code == 4`** for the "edit introducing an unverifiable
   label" negative; the specific `post_edit_error_codes` are printed but not asserted. Its 10
   model injections are correctly code-asserted and crash-proof, so this is a small weakening of
   one negative, not a vacuous suite.
4. **`derived_from` shape drift.** The schema says `items: {"type":"string"}`
   (`schemas/figure_model.schema.json:18`) while `model.py:117-120` only requires a non-empty
   list. My own fixture originally used objects; I corrected it to strings for schema
   conformance (`work/fixtures/GOLD.md` §C.3).
5. **Compliance-gate coverage.** `check_artifacts` (16 ids) verifies formats, fonts, dpi, page
   size, extractable text, layer count, line width, colour space and provenance *presence*. It
   does not verify that a `data-src-kind` is meaningful or that SVG and `source_map.json` agree —
   the disagreement I found (F2) was invisible to the gate and only showed up under my
   independent cross-check.
6. **`lead-e2e` snapshot is stale.** The Lead's own evidence dir `work/dev/lead-e2e/out/result.json`
   reports `missing_required_fields=["result_json"]`; a fresh run of the same chain by me passes
   with `missing=[]` (C9). The claim "CLI chain is green" is **correct**, but that particular file
   was produced by an earlier revision and should not be cited as current evidence.
7. **`P07`/`P06`-style checks measure the drawn artifact, not the model.** For example the chart's
   bar heights are checked from the SVG rects, and the relation heads from the SVG polylines, so
   a model/rendering mismatch would be caught; conversely a defect that exists only in the model
   JSON and is never drawn (e.g. a stale `entities[].value`) is outside these checks — which is
   why observation 2 is reported as an observation.
8. **Chart locator semantics.** After the F2 fix the chart marks bind to
   `materials/iris_measurements.csv#table:Iris-setosa` — `table:` now carries a *category value*,
   not the measured column (`materials/iris_measurements.csv#table:petal_length_cm` would be the
   canonical `table:col` form of CONTRACT.md §4.7). The binding is consistent between SVG and
   `source_map.json` and the category is recoverable, so I do not score it as a defect; the
   `column` field exists in the code (`layout.py:1816-1817`, `:325-328`) and would fix it if the
   agent/model set it.

## 4. Defects found during this task, and their resolution

| id | defect (expected vs actual) | severity | status |
|---|---|---|---|
| F1 | `result.json` recorded a self hash that could not match the file it described: `artifact_list` hashed the *previous* `result.json` (then `run.py:707-714`) before `finish` rewrote it (then `run.py:795`). Expected: a recomputable self digest; actual: sha **and** bytes differed (e.g. recorded `8ac908d3…` / 747 B vs actual `e9138608…` / 21 805 B). Repro: `harness.py run` checks `P11b`, `C15` | high (self-audit integrity) | **REPORTED → FIXED → RE-VERIFIED PASS.** Current code marks the entry `self_referential` with a documented `hash_basis` (`run.py:820-835`, `run.py:918-921`, `run.py:166-185`); my independent recomputation matches for all 4 runs |
| F2 | chart data marks had no usable provenance: `figure.svg` `series:<i>` carried `data-src-kind="unsupported"` with locator `…csv#table#series[0]`, and `source_map.json` omitted them. Root cause: `layout.py:1774` reads `series[].source`, which `schemas/figure_model.schema.json:142` never defines, while the rows-derived path (`layout.py:1835-1838`) does bind `col:<column>` | medium (rubric: mapping independently checkable) | **REPORTED → FIXED → RE-VERIFIED PASS.** Now SVG and `source_map.json` both say `derived` with `table:<category>` locators (bound 11, unsupported 0); `B07` passes; the intermediate half-fix (SVG said `unsupported` while `source_map` said `derived`) was reported and is gone |
| F3a | the case-c fixture could not pass the Skill's own gate: `E_QUOTE_NOT_FOUND` ×3 (backticks in `iris_source_note.md#L15` are kept by `ingest.normalise_text`, `ingest.py:107-109`) and `E_PROVENANCE_MISSING` (caption `kind:"derived"` without `derived_from[]`, `model.py:117-120`) | high **for the fixture** (case unsolvable) | **FIXED IN MY OWN SCOPE** (`work/fixtures/case-c-edit/before/figure_model.json`, documented in `GOLD.md` §C.3). I never touched `work/submission/**`. After the fix: `edit` exit 0, `status=ok`, `finish --strict` exit 0 |
| F3b | documented draft handling did not hold: at revision `802ed06f…`, `render` of the unrevised draft returned `status=ok`, exit 0, 0 errors, and `finish` left `status=ok` with only a limitation line — contradicting `SKILL.md:56-58` | medium (honesty / reliability) | **REPORTED → FIXED → RE-VERIFIED PASS** (`run.py:441-443`, `run.py:853`, `run.py:859-860`) |

No other FAIL was observed in the executed suites. Three defects (F1, F2, F3b) were also
reported to the Lead with file:line and a one-line repro at the milestones; F3a was fixed by me
inside my own write scope.

## 5. Could not verify (summary; details in `INDEPENDENT_LIMITS.md`)

* the three hidden organizer cases (unknown inputs/outputs) — **UNVERIFIED** (C17);
* platform behaviour: installation at `/skills/weekly-skill`, trigger matching, budgets,
  bundle gate / trace G10 — **UNVERIFIED** (C16, C20);
* a stripped runtime without matplotlib/Pillow/pypdf — **UNVERIFIED** (C18); all present here;
* human visual / scientific readability judgement — **UNVERIFIED** (C19);
* full line-by-line review of the 51 KB `references/**` prose — **UNVERIFIED** (C14);
* existence/validity of a public GitHub link — **UNVERIFIED** (C15);
* other owners' scratch evidence (`work/dev/**` numbers) — I used it as leads only; I did not
  re-run their scripts, so their specific counts remain *their* claims (INDEPENDENT_LIMITS.md §7).

## 6. Reproduction (frozen revision)

```powershell
cd D:\Borium_Contest\ARMI2611000058v1
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONDONTWRITEBYTECODE='1'
py -3 work\verify\hash_snapshot.py --compare        # must print identical: true (exit 0)
py -3 work\verify\harness.py run                    # 70 PASS / 0 FAIL  (exit 0)
py -3 work\verify\harness.py negative               # 20/20 detected, 0 vacuous (exit 0)
py -3 work\verify\harness.py report                 # re-print the summary
py -3 work\verify\baseline_run.py --cases case-a,case-b
py -3 work\submission\scripts\selftest.py           # PASS 65 passed / 0 failed
```

Raw evidence is kept under `work/verify/`: `harness_results.json` (all checks, with evidence
objects), `baseline_results.json`, `_neg.out`, `_run.out`, `_base.out`, `_selftest.out`,
`_validate.json`, `_pin_before.json` / `_pin_after.json`, `runs/**` (every stage's stdout/stderr
and all produced artifacts), `negative/**` (the mutated inputs), `work/freeze/source_hashes.json`.
