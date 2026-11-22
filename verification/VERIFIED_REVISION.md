# Verified revision

The verification documents in this folder describe the **hash-pinned frozen revision**

`tree_sha256 = 2ec1a519aa7fad72e4920ff1dd6aa36e2eff186736e9364dea4bd43aee0a30a9`
(25 files / 641,114 B; `validate_skill_submission.py` -> status ok, errors=[]).

They go **stale on any change**; the independent verifier's `hash_snapshot.py --compare` is the
gate that detects drift and also checks `manifest.json`'s list against the real tree
(`manifest_matches_tree: true`).

Submitted bundle: `sha256 b6f115274ce6ecdcecd3e27d74efbc2a5855e708685cc2ef8a71225408c7255f`
(89 entries, 1,469,000 B native trace / 537 records, attempt `99143`).

Three revisions were submitted as the review rounds surfaced defects; the repository root reflects
the **current** one. The bundles differ, so they are not duplicate submissions. This revision adds
two hard gates: `E_MODEL_NOT_REVISED` (an unrevised draft can no longer finish `ok`) and the
escalation of a truncated-bar-baseline warning to `E_BAR_BASELINE_TRUNCATED`.

`EXTERNAL_LANDSCAPE.md` is a repo-only note (dated, scoped search) grounding the
innovation-boundary claim; it changes no code and is not part of the verified tree.
`runs/` and `negative/` raw evidence are deliberately not published here.