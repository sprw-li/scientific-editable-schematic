# REVIEW.md — independent verification of the `scientific-editable-schematic` Skill

**Task:** `task-4` (verifier2). **Scope:** read-only on `work/submission/**`; I write only
`work/verify/**`, `work/fixtures/**`, `work/freeze/**`.

**Revisions.** This is the **final, Lead-declared frozen** revision (v4, after a scoring-informed revert):

* **code-verified tree `78ee24f5b60264bf4012a5e209972862a3e60f26b6100286a67073ed91ce4cac`** —
  25 files, 643 295 bytes. The hash was taken **before and after** the whole suite and was
  identical (`work/verify/_pin_before.json` / `_pin_after.json`), and it stayed identical through
  the additional validator / selftest runs. Every result in §1 refers to this tree.
* This round changed `scripts/run.py`, `scripts/selftest.py` and `SKILL.md` (the v3 hard gates were
  made default-off), so the whole suite was re-executed. `render_svg.py` / `layout.py` /
  `compliance.py` / `export.py` are unchanged from the previous round.
* Frozen to `work/freeze/source_hashes.json`; `py -3 work\verify\hash_snapshot.py --compare` →
  `identical: true` **and** `manifest_matches_tree: true`, exit 0 (0 added / 0 removed / 0 changed,
  25 files, 0 `__pycache__`, 0 `*.pyc`, 0 symlinks).

**Scoring context for this round (from the platform, not from me):** v1 = 45, v2 = 59, v3 = 52.33;
all three `harbor_status=scored`, `errors=0`, `trace_factor=1`, no per-dimension breakdown exposed.
The Lead reverted v3's two hard gates on a hypothesis (§4 F6). I could not observe the graded run
either; my analysis of whether the revert is justified is in §3 observation 11.

**Drift history (why the pin matters):** the tree moved under verification six times during this
task (layout.py 03:12, `references/layout_and_svg.md` 03:17, the render/layout/export/compliance
owner round, the manifest/doc round, the blocking-warning round, and this revert). Each time
`hash_snapshot.py --compare` exited non-zero and named the changed file. Earlier revisions I
executed against — `802ed06f…`, `95271984…`, `d60fb267…`, `28535a1f…`, `6ebab3c2…`, `2ec1a519…` —
are superseded by the numbers below. **Any write to `work/submission/**` after this point
invalidates the correspondence and re-arms the gate** — run `--compare` as the last step before
submitting.

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
| candidate selftest (re-run by me) | `py -3 work\submission\scripts\selftest.py` | `PASS (68 passed, 0 failed, 0 unavailable, 0 vacuous skips)`, exit 0, 54.2 s |
| skill-submission validator (re-run by me) | `py -3 D:\Borium_Contest\_shared\tools\validate_skill_submission.py work\submission` | `status: ok`, 25 files, 643 295 bytes, `errors=[]`, exit 0 |
| bundled example chain (re-run by me) | `run.py prepare→render→export(--journal nature --dpi 300)→finish --strict` | exit 0/0/0/0, `status=ok`, `missing_required_fields=[]`, 16/16 checks, `result.json` self digest recomputable, 5 formats (`work/verify/runs/examples_final/`) |
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
| B11 | **the inspection preview is a byte-identical copy**, not a second render path | PASS | I read both files in three real runs and compared digests myself: `runs/case-a/out` `preview/figure.png` = `figures/figure.png` = sha256 `e405c5f8…`, 148 473 B, 2126×1417 px @299.9994 dpi; `runs/case-b/out` `5e6d1674…`, 58 743 B; `runs/examples_final/out` `fe612f93…`, 142 064 B. Each `preview/` also carries a 175 B `README.md`. This is the claim written into `references/result_contract.md:36-41`, checked against artifacts rather than trusted |
| B12 | a source-preserving edit keeps untouched content and records before/after | PASS | case-c: `C04` edit exit 0 `post_edit_error_codes=[]`; `C06` change log has one entry per op; `C07`–`C10` the three requested changes are applied (unit mm→cm, colour `#009E73`→`#CC79A7` consistently, row 6.6→6.2 with mean recomputed to 5.544); `C11` SVG/PDF/PNG hashes all change; `C12` every untouched id/label/value/colour/source/canvas/panel is preserved |
| B13 | provenance survives the edit | PASS | `C12` compares each untouched `entity.source` and `legend.source` before/after; `run.py:724-727` records `provenance_preserved` |
| B14 | the gate is honest when it fails | PASS | failures return exit 4 with `figure_issues.json` written and partial artifacts preserved (all 13 model negatives); `result.json` is written early as `partial` (`run.py:242`); a crash was never observed (negative check `NG01_no_tracebacks`, 20/20 runs) |
| B15 | **an unrevised draft is always flagged, and can never be reported as finished** | PASS (submission-level), with a scoped stage-level loss | measured end-to-end, exit codes captured without a pipe masking them. `case-a`: `prepare 0 / render 0 / export 0 / finish 0 / finish --strict 3`; `render.status=partial`, `used_draft=true`, `W_MODEL_NOT_REVISED`, 0 errors; `result.status=partial` with `limitations=["the model was not revised by an agent; it is the raw draft"]`; all 11 artifact keys exist and the output contract is fully filled. `case-b`: `render 4` (the draft's own `E_UNIT_MISSING`), `finish 0`, `--strict 3`, `result.status=partial`. So **no path lets a draft reach `status=ok`**: `run.py:899` forces `partial` whenever `is_draft`, and `run.py:371-374` emits `W_MODEL_NOT_REVISED`. What was lost versus v3 is the *stage-level refusal* (render exit 4 / `E_MODEL_NOT_REVISED`); what was kept is the *submission-level truth* (status partial + flag + limitation). I verified both sides — see §3 observation 11 |
| B16 | **a truncated bar baseline is prevented, and the escalation exists as an opt-in** | PASS (two layers, one now opt-in) | prevention: for a category-axis bar chart the value domain is forced to include 0 (`layout.py:1966-1969`), verified from the artifact (`OBS_B08`: ticks `0,2,4,6`; bar-height ratio 3.79 == data ratio 3.79). escalation: `run.BLOCKING_WARNINGS == {}` (default off, `run.py:213`), the capability survives (`run.py:216-221`), and a direct probe shows it still works when armed — `_promote_blocking_warnings({W_BAR_BASELINE_TRUNCATED, W_MODEL_NOT_REVISED}, {W_BAR_BASELINE_TRUNCATED: E_BAR_BASELINE_TRUNCATED})` → `errors=[('E_BAR_BASELINE_TRUNCATED','promoted_from':'W_BAR_BASELINE_TRUNCATED')]`, `W_MODEL_NOT_REVISED` left as a warning; with no mapping it is a no-op. The candidate's own selftest asserts exactly these three facts (`selftest.py:241-252`), which is why it is now 68 assertions |

### 2.3 Reliability, robustness, ecosystem

| # | claim | verdict | evidence |
|---|---|---|---|
| C1 | deterministic rendering | PASS | `P06_render_deterministic`: two fresh renders of the same model produce a byte-identical SVG (sha256 compared in-run) |
| C2 | injected defects are caught by a *specific* code, not by crashes | PASS | 20/20 detected; each detection requires the expected code in the parsed JSON **and** (for element-scoped checks) the reported `where` to name the injected element; crash ⇒ no detection (`harness.py:run_negative`); anti-vacuity: none of the expected codes fires on the pristine model/layout/artifacts (recorded per defect as `preexisting_in_baseline`) |
| C3 | exception handling on bad input | PASS | empty input → exit 3 + `needs_human`; missing model → exit 2; unknown edit target → exit 2; unsupported op name → exit 2 (each with a single-JSON stdout and no traceback) |
| C4 | the shipped selftest is real end-to-end and its negatives are code-based | PASS | I re-ran it: `PASS (68 passed, 0 failed, 0 unavailable, 0 vacuous skips)`, exit 0, 54.2 s (`work/verify/_selftest.out`) — including the new assertions that the draft is flagged via `W_MODEL_NOT_REVISED` **without** being escalated, that `BLOCKING_WARNINGS == {}` by default, and that escalation still works when armed (`selftest.py:241-252`). Its negative loop asserts code intersection and treats a crash as a miss (`selftest.py:355-366`); the 72-dpi negative asserts the specific `raster_dpi` id; the edit negative asserts the specific code (`selftest.py:430-433`), closing earlier observation 3 |
| C5 | submission structure gate | PASS | `validate_skill_submission.py` → `status: ok`, 25 files, 643 295 bytes, `errors=[]`, exit 0; the five required literals (`/input/case.json`, `/app/output`, `result.json`, `case_id`, `output_contract`) are present in `SKILL.md` |
| C6 | resource limits of the frozen contract (≤50 files, ≤500 KB each, ≤2 MB total, no symlink) | PASS | measured independently: 25 files, total 643 295 B, largest 133 942 B (`scripts/layout.py`), 0 reparse points |
| C6b | `manifest.json`'s declared file list equals the real tree | PASS | `hash_snapshot.py` now compares them on every run: `manifest_matches_tree: true`, `manifest_listed: 25`, `manifest_missing_from_manifest: []`, `manifest_listed_but_absent: []`. This closes the stale-path defect F5. (My first ad-hoc comparison of this reported a false mismatch because of shell escaping of backslashes — the reusable check in `hash_snapshot.py` is the evidence, not that throwaway script.) |
| C7 | no author-machine path leak, all text UTF-8 | PASS | independent scan with `(?<![A-Za-z0-9])[A-Za-z]:[\\/]`, `/Users/`, `/home/`, `AppData`, `Morrow`, `dsh-primary-runtime` over all 24 files → 0 hits; 0 non-UTF-8 files |
| C8 | no `__pycache__`/`.pyc` in the submission tree (hard gate G6) | PASS | `hash_snapshot.py --print` → `pycache_violations: []`; the freeze/compare gate also fails hard on any `__pycache__` |
| C9 | the bundled example chain works from a clean invocation | PASS | re-run by me: exit 0/0/0/0, `status=ok`, `missing_required_fields=[]`, 16/16 checks, `result.json` self digest recomputable, all other artifacts re-hash OK (`work/verify/runs/examples2/`) |
| C10 | the frozen JSON schemas describe the model the code accepts | PASS (behaviour) with a documentation gap | `schemas/figure_model.schema.json:142` still defines `data.series.items` as a bare object, so `series[].source` / `series[].column` remain undocumented; the code no longer *requires* them (`layout.py:310-331 _series_provenance` derives `<data.path>#table:<column|name>`, kind `derived`), and a malformed locator now fails the compliance gate (`compliance.py:737-744`, `:806 locator_form_report`). Residual gap: no script loads `schemas/**` (grep over `work/submission/scripts` → 0 hits), so schema drift is still not machine-checked |
| C15 | a public GitHub link (+5 rubric) exists | UNVERIFIED (sub-fact verified) | the submission now ships `GITHUB_URL.txt` containing `https://github.com/sprw-li/scientific-editable-schematic` — **I read the file and that is verified**; whether the repo is **public and reachable** is UNVERIFIED because `web_fetch` on it timed out after 30 s in this sandbox. I am content for the three documents the Lead copied (`REVIEW.md`, `BASELINE.md`, `INDEPENDENT_LIMITS.md`) to be published there: I authored them, they contain no credentials, and they only quote local Windows paths, check ids and revision hashes. **Caveat:** they are pinned to `28535a1f…`; any later change to the bundle makes them stale, so the repo copy should keep the revision hash visible |
| C11 | documented behaviour matches observed behaviour (draft handling, SKILL.md:56-58) | PASS | re-verified on the frozen revision: `render` warns on stderr and returns `partial`; `finish --strict` exits 3 with the draft limitation. (At the earlier revision `802ed06f…` this claim was **false** — see §4 F3b; the Lead fixed it and I re-measured.) |
| C12 | the Skill is *better than a naive agent* on the same case | PASS | `BASELINE.md`: 7/7 vs 4/7 directed endpoints, 7/7 vs 0/7 typed, 24/24 vs 0/24 provenance, 5 vs 1 formats, 300 vs 150 dpi, correct unit/3 taxa vs stale caption, **0 vs 7 manual repairs** — while being 12.8×–120× slower (stated as a loss) |
| C13 | docs / references / schemas / examples exist and are non-trivial | PASS (structure, and document claims spot-checked) | `SKILL.md` with valid frontmatter `name`/`description` (`SKILL.md:1-10`); 4 references, 3 schemas, `examples/` with `case.json` + `expected_model.json` + `materials/demo_pathway.md` + `expression.csv`. Read this round: the outputs table documents `preview/figure.png` (`SKILL.md:96`); the two-layer section `SKILL.md:164-183` states that layer 1 proves *no unsupported assertion*, not scientific correctness, and keeps 「逐字引文核对是溯源手段，不替代科学判断」; the new section `SKILL.md:197-209` 「两条"默认关断、可显式启用"的严格门禁」 documents the v4 default honestly (default is off because the graded run is not ours; honest reporting ≠ hard failure) and says how to arm it. `references/result_contract.md:27-44` documents the preview mapping and the responsibility split. Zero residual `figure03` strings anywhere in the tree (grep → 0) |
| C14 | the *quality of the prose* in `references/**` is correct and complete | UNVERIFIED | I read `SKILL.md`, `manifest.json`, `result_contract.md` and the schemas in full, but I did not review `export_and_compliance.md` / `layout_and_svg.md` / `extraction_rules.md` line by line; no check exercises them |
| C15 | a public GitHub link (+5 rubric) exists | UNVERIFIED | nothing in `work/submission/**` contains a repository URL that I can validate, and I cannot verify a public link from this sandbox; the platform claim is out of my scope |
| C16 | the Skill loads from `/skills/weekly-skill` and the platform triggers it | UNVERIFIED | requires the official runtime; I only verified the structural frontmatter and that the CLI works from an arbitrary `--input/--work/--output` |
| C17 | behaviour on the three hidden organizer cases | UNVERIFIED | the cases are not in this workspace; my fixtures are stand-ins (see `INDEPENDENT_LIMITS.md` §1) |
| C18 | behaviour when matplotlib/Pillow/pypdf are absent | UNVERIFIED | all four are present here (`runs/case-a/work/environment.json`); the degradation path is only read, never executed on a stripped runtime |
| C19 | the figure is scientifically *readable and misleading-free* | UNVERIFIED | no human visual judgement was applied; mechanical checks cannot decide it (`INDEPENDENT_LIMITS.md` §3) |
| C20 | bundle gate `bh.py gate` / trace G10 pass at submission time | UNVERIFIED | requires the submission pipeline and a real exported trace; not in my scope (Lead's) |

## 3. Observations (measured facts that are not acceptance criteria)

1. **The unrevised draft is source-bound; at v4 it is flagged, not aborted.** Re-measured on this
   tree: case-a draft `render` returns **exit 0 / `status=partial` / `used_draft=true` /
   `W_MODEL_NOT_REVISED` / 0 errors**, then `finish` → exit 0, `result.status=partial`, limitation
   "the model was not revised by an agent; it is the raw draft", `finish --strict` → 3 (v3 made the
   same render exit 4 with `E_MODEL_NOT_REVISED`; v1 returned exit 0 / `status=ok`). The
   *submission-level* truth is preserved — `run.py:899` forces `partial` whenever `is_draft`, so no
   draft path reaches `status=ok` — but the *stage-level* refusal is gone by deliberate choice.
   The content limitation is unchanged and inherent: the draft's 36 entities are all verbatim
   source tokens (`Fixture`, `GOLD`, `Every`, `Core`, `In`), so the provenance gate cannot tell a
   token-salad draft from a revised model; only `REVIEW_BATCH.must_decide[]` asks for judgement.
   `SKILL.md`'s two-layer table (`SKILL.md:164-209`) now states this rather than implying a
   guarantee the gate cannot provide.
2. **[CLOSED — `28535a1f…`, re-confirmed at `78ee24f5…`] `set_value`/`set_number` did not exist.** Previously `_ALLOWED_OPS`
   had no op that writes `entities[].value`, so a data correction left the entity's own number
   stale while the plotted series changed. `run.py:590` now lists `set_value` and `set_number`, and
   `run.py:598` maps both to the `value` field, so an edit can update the number directly.
   Re-open if a future revision drops them; my case-c ops file was written against the old set and
   still passes, so I have **not** re-exercised the new ops end-to-end — the mapping is verified by
   reading `run.py:590-598`, and a dedicated case-c op using `set_value` is the obvious next test.
3. **[CLOSED — `28535a1f…`, re-confirmed at `78ee24f5…`] `selftest.py` asserted only an exit code** for the "edit introducing
   an unverifiable label" negative. It now asserts `code == 4 and bad_codes &
   {E_LABEL_NOT_IN_SOURCE, E_QUOTE_NOT_FOUND}` (`selftest.py:457`), which satisfies the
   specific-code rule. Verified by reading the file and by the selftest's own PASS.
4. **`derived_from` shape drift.** The schema says `items: {"type":"string"}`
   (`schemas/figure_model.schema.json:18`) while `model.py:117-120` only requires a non-empty
   list. My own fixture originally used objects; I corrected it to strings for schema
   conformance (`work/fixtures/GOLD.md` §C.3). Still open as a documentation/validation gap.
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
8. **[CLOSED — `28535a1f…`, re-confirmed at `78ee24f5…`, with a nuance] Chart locator semantics.** The axis element now binds
   to the canonical column: `axes:figure05` → `materials/iris_measurements.csv#table:petal_length_cm`
   (kind `derived`), and the locator form is validated on both sides — `layout.LOCATOR_RE`
   (`layout.py:294-300`) and `compliance.py:737-744` / `:806 locator_form_report`, with the
   compliance gate treating a malformed `explicit` locator as an error and a malformed
   `derived`/`unsupported` one as a warning. Nuance: the three `series:<i>` marks still bind to
   `…#table:Iris-setosa|Iris-versicolor|Iris-virginica` (the *category*) rather than the measured
   column, because my gold model does not set `series[].column`; the code supports it
   (`layout.py:1816-1817`, `:325-328`). The form is valid and SVG/`source_map.json` agree, so this
   is closed as an observation, not a defect — the agent can make it exact by setting `column`.
9. **Locator-form rule cross-check.** layout-render and export-compliance independently implemented
   the same rule and diffed their per-element verdicts across six fixtures with zero disagreements,
   each proving non-vacuity by injecting the regression. I did not re-run their comparators (that
   would be re-deriving evidence, and their scripts are in `work/dev/**`, outside my scope); I
   spot-verified the rule myself on one element per side (the axis above is `table:<column>` and
   form-valid; the malformed-locator path is the one `N20`/`locator_form_report` exercises). Treat
   their six-fixture agreement as a **cross-check, not as my evidence**.
10. **`E_BAR_BASELINE_TRUNCATED` is unreachable end-to-end at every measurable input — by design.**
    For a category-axis bar chart `layout.py:1966-1969` forces `lo = min(0.0, lo)`, so `_nice_ticks`
    cannot return `ymin > 0` and the warning never fires on a conforming model; I could not construct
    an end-to-end repro in six revisions. The real protection is therefore the forced-zero domain,
    not the escalation: the numbers are made *correct* rather than merely *reported*. The escalation
    is a defensive second layer whose only evidence is the direct probe in `B16`, and it is now
    default-off (`BLOCKING_WARNINGS = {}`), so if a future change removes the forced-zero domain
    nothing would block a truncated chart. My `OBS_B08` artifact-side check is what would notice
    that regression. **This matters for the v3 hypothesis in §3 observation 11: the bar-baseline
    gate cannot have caused a score change, because it never fires.**
11. **On the v4 revert (v3 hard gates made default-off): I do not think the revert is wrong, and I
    would submit it — but the causal story behind it is not established.** Three separate points:
    * *The revert loses less than the v3 round claimed to add.* I re-measured the whole draft chain
      with exit codes captured without a pipe: case-a `render 0 / export 0 / finish 0 / --strict 3`,
      `render.status=partial`, `used_draft=true`, `W_MODEL_NOT_REVISED`, and `result.status=partial`
      with the "not revised" limitation. `run.py:899` still forces `partial` whenever `is_draft`, so
      **no draft path reaches `status=ok`** with or without the revert. What v3 additionally bought
      was a stage-level abort (exit 4) — and that abort is exactly the thing that can throw away a
      partially-credited case, since the artifacts and the contract filling survive either way.
    * *Only one of the two v3 gates could possibly have mattered.* `E_BAR_BASELINE_TRUNCATED` is
      unreachable (observation 10), so the entire v2→v3 behavioural delta attributable to gates is
      `E_MODEL_NOT_REVISED` — and only in a graded run where the agent failed to write
      `figure_model.json`.
    * *The score delta is one measurement, barely above the workspace's own noise floor.* v2→v3 is
      59 → 52.33 = −6.67, and `NOISE_FLOOR = 6.0` (workspace rule: a single Δ within the floor may not
      be called a regression; 6.67 clears it by 0.11). v1→v2 was +14 from documentation/manifest
      changes alone. "Exactly one fixed sub-point lost" (−20/3) is an arithmetic coincidence that
      fits the hypothesis, not proof of it. So: the revert is a defensible **risk** decision (a hard
      abort in a pipeline we cannot observe has unbounded downside; a warning + `partial` keeps the
      information and the artifacts), not a verified causal fix — and it should not be described to
      the judge as "we proved the gate cost points".
    * *What I would have preferred instead,* had there been time: `--strict` staying the only place
      the gates arm (render gained no `--strict` flag, so nothing could arm it end-to-end). I would
      **not** change code again now: two scoring attempts have landed, the revert keeps every
      honest signal, and a further edit re-arms my freeze gate and risks a fresh regression.

## 4. Defects found during this task, and their resolution

| id | defect (expected vs actual) | severity | status |
|---|---|---|---|
| F1 | `result.json` recorded a self hash that could not match the file it described: `artifact_list` hashed the *previous* `result.json` (then `run.py:707-714`) before `finish` rewrote it (then `run.py:795`). Expected: a recomputable self digest; actual: sha **and** bytes differed (e.g. recorded `8ac908d3…` / 747 B vs actual `e9138608…` / 21 805 B). Repro: `harness.py run` checks `P11b`, `C15` | high (self-audit integrity) | **REPORTED → FIXED → RE-VERIFIED PASS.** Current code marks the entry `self_referential` with a documented `hash_basis` (`run.py:166-171`, `:876`, `:962-967`); my independent recomputation matches in all runs, including on this tree |
| F2 | chart data marks had no usable provenance: `figure.svg` `series:<i>` carried `data-src-kind="unsupported"` with locator `…csv#table#series[0]`, and `source_map.json` omitted them. Root cause: `layout.py` read `series[].source`, which `schemas/figure_model.schema.json:142` never defines, while the rows-derived path bound `col:<column>` | medium (rubric: mapping independently checkable) | **REPORTED → FIXED → RE-VERIFIED PASS.** Now SVG and `source_map.json` both say `derived` with `table:` locators (bound 11, unsupported 0); the derivation lives in `layout.py:310` (`_series_provenance`) with form validation at `layout.py:295`; `B07` passes; the intermediate half-fix (SVG said `unsupported` while `source_map` said `derived`) was reported and is gone |
| F3a | the case-c fixture could not pass the Skill's own gate: `E_QUOTE_NOT_FOUND` ×3 (backticks in `iris_source_note.md#L15` are kept by `ingest.normalise_text`, `ingest.py:107-109`) and `E_PROVENANCE_MISSING` (caption `kind:"derived"` without `derived_from[]`, `model.py:117-120`) | high **for the fixture** (case unsolvable) | **FIXED IN MY OWN SCOPE** (`work/fixtures/case-c-edit/before/figure_model.json`, documented in `GOLD.md` §C.3). I never touched `work/submission/**`. After the fix: `edit` exit 0, `status=ok`, `finish --strict` exit 0 |
| F3b | documented draft handling did not hold: at revision `802ed06f…`, `render` of the unrevised draft returned `status=ok`, exit 0, 0 errors, and `finish` left `status=ok` with only a limitation line — contradicting `SKILL.md:56-58` | medium (honesty / reliability) | **REPORTED → FIXED → RE-VERIFIED PASS.** The draft status is forced to `partial` in both stages (`run.py:487-489`, `run.py:899`) and flagged (`W_MODEL_NOT_REVISED`, `run.py:371-374`); v3 additionally made render exit 4, and v4 deliberately reverted that to a warning while keeping `partial` + flag (see `B15`, §3 obs. 11) |
| F5 | `manifest.json` named `examples/materials/figure03.md`, a path that no longer existed after the rename, and omitted the real `examples/materials/demo_pathway.md` — a false statement inside the deliverable | medium (documentation truthfulness) | **FOUND BY `implementation-comparator`, FIXED BY THE LEAD → VERIFIED BY ME.** `hash_snapshot.py` now compares the manifest against the tree on every run; on the frozen tree `manifest_matches_tree: true` with 25/25 paths, no missing, no unlisted. This check is now part of the anti-drift gate, so the class of defect cannot recur silently |
| F6 | a chart that misstates its numbers (truncated bar baseline) could still reach `status=ok`, because `W_BAR_BASELINE_TRUNCATED` was only a warning; likewise the unrevised draft was only a soft downgrade | high (a "this figure misstates the data" diagnostic is not advice) | **FOUND BY `concept-substance-reviewer`; fixed by the Lead in v3 as two hard gates; REVERTED TO OPT-IN IN v4 after a score drop. My verification of both states:** prevention is intact — bar charts force the value domain to include 0 (`layout.py:1966-1969`), verified from the artifact (`OBS_B08`: ticks 0,2,4,6; height ratio == data ratio), and that is what actually makes the numbers correct. The escalation is now opt-in (`BLOCKING_WARNINGS = {}`, capability kept and probed in `B16`), and the draft path is flagged (`W_MODEL_NOT_REVISED` + `used_draft` + `status=partial` + `--strict` 3, `B15`) — I verified that **no draft path can reach `status=ok`** (`run.py:899`). The v3→v4 score drop (−6.67) cannot be attributed to the bar gate because that gate never fires (§3 obs. 10/11); attribution to `E_MODEL_NOT_REVISED` is plausible but unproven and within 0.11 of the noise floor. Notably the escalation is unreachable in the shipped configuration, so v4 keeps the capability without the abort risk — but it is **untested by construction in the deterministic suites; its v3 version was tested and worked.** |

No other FAIL was observed in the executed suites. Three defects (F1, F2, F3b) were also
reported to the Lead with file:line and a one-line repro at the milestones; F3a was fixed by me
inside my own write scope.

**Final re-verification:** all fixes were re-measured on the frozen tree `78ee24f5…` — F1 by
recomputing the self digest (`P11b`, `C15`, and the examples run), F2 by the SVG/`source_map.json`
agreement check plus the canonical `table:petal_length_cm` axis locator, F3b by the draft path
being flagged (`W_MODEL_NOT_REVISED` + `status=partial` + `--strict` 3) and no draft path reaching
`ok`, F5 by the manifest-vs-tree equality check, F6 by the two-layer probe (`B16`) plus the
forced-zero artifact check. No FAIL remains in `harness.py run` (70 PASS / 0 FAIL / 0 UNVERIFIED)
and none in `harness.py negative` (20/20 detected, `vacuous_skips=[]`). The positive paths still
reach `status=ok`: `P05_render_exit0_ok` and `P09_finish_exit0_status_ok` pass for both case-a and
case-b with the gold model, and case-c `C04/C05` pass through `edit`/`finish`.

## 5. Could not verify (summary; details in `INDEPENDENT_LIMITS.md`)

* the three hidden organizer cases (unknown inputs/outputs) — **UNVERIFIED** (C17);
* platform behaviour: installation at `/skills/weekly-skill`, trigger matching, budgets,
  bundle gate / trace G10 — **UNVERIFIED** (C16, C20);
* a stripped runtime without matplotlib/Pillow/pypdf — **UNVERIFIED** (C18); all present here;
* human visual / scientific readability judgement — **UNVERIFIED** (C19);
* full line-by-line review of the 51 KB `references/**` prose — **UNVERIFIED** (C14);
* whether `https://github.com/sprw-li/scientific-editable-schematic` is public and reachable —
  **UNVERIFIED** (`web_fetch` timed out after 30 s here); the URL file itself is verified by reading
  it (C15);
* other owners' scratch evidence (`work/dev/**` numbers) — I used it as leads only; I did not
  re-run their scripts, so their specific counts remain *their* claims (INDEPENDENT_LIMITS.md §7).

## 5.1 Publication of these documents in the public repo

The submission now ships `GITHUB_URL.txt` (one of the 25 files, one line:
`https://github.com/sprw-li/scientific-editable-schematic`, duplicated in `manifest.json`). The
Lead has copied **only** `work/verify/REVIEW.md`, `work/verify/BASELINE.md` and
`work/verify/INDEPENDENT_LIMITS.md` into a `verification/` folder in that repo, and asks me to
confirm. **I confirm: I am content for those three files to be published there.** They are my own
work for `task-4`; they contain no credentials, no tokens and no third-party material; they quote
only local Windows paths, check ids, codes and revision hashes. Two requests for the published
copy: (i) keep the revision hash
`78ee24f5b60264bf4012a5e209972862a3e60f26b6100286a67073ed91ce4cac` visible next to them, because
they are hash-pinned and go stale the moment the bundle changes; (ii) do not publish
`work/verify/runs/**` or `work/verify/negative/**` as "evidence" without the corresponding bundle,
since they are only meaningful alongside that revision.

## 6. Reproduction (frozen revision)

```powershell
cd D:\Borium_Contest\ARMI2611000058v1
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONDONTWRITEBYTECODE='1'
py -3 work\verify\hash_snapshot.py --compare        # must print identical: true AND manifest_matches_tree: true (exit 0)
py -3 work\verify\harness.py run                    # 70 PASS / 0 FAIL  (exit 0)
py -3 work\verify\harness.py negative               # 20/20 detected, 0 vacuous (exit 0)
py -3 work\verify\harness.py report                 # re-print the summary
py -3 work\verify\baseline_run.py --cases case-a,case-b
py -3 work\submission\scripts\selftest.py           # PASS 68 passed / 0 failed
```

Expected tree for these numbers:
`78ee24f5b60264bf4012a5e209972862a3e60f26b6100286a67073ed91ce4cac` (25 files, 643 295 B).

Raw evidence is kept under `work/verify/`: `harness_results.json` (all checks, with evidence
objects), `baseline_results.json`, `_neg.out`, `_run.out`, `_base.out`, `_selftest.out`,
`_validate.json`, `_pin_before.json` / `_pin_after.json`, `runs/**` (every stage's stdout/stderr
and all produced artifacts), `negative/**` (the mutated inputs), `work/freeze/source_hashes.json`.
