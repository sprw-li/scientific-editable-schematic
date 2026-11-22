# Verified revision

The verification documents in this folder describe the **hash-pinned frozen revision**

`tree_sha256 = 6ebab3c237a0d9986a92ea122baa333d79fe0eda87d11bc69c6953cf4b31b84d`
(25 files / 636,757 B; `validate_skill_submission.py` -> status ok, errors=[]).

They go **stale on any change** to the skill tree; the independent verifier's
`hash_snapshot.py --compare` is the gate that detects drift (it also checks that
`manifest.json`'s file list matches the real tree: `manifest_matches_tree: true`).

Submitted bundle: `sha256 606a85f04df32c2e4f2db5da56b18b888e368890beef44b33d1a73670f183d7f`
(89 entries, 1,364,683 B native trace / 486 records, attempt `99138`).

A previous revision (tree `28535a1f...`, attempt `99110`) was submitted first; this repository
root reflects the **current** revision. The two bundles differ (they are not duplicate submissions):
this one fixes a false path in `manifest.json` and documents the `preview/` mapping and the
gate-vs-judgement split.

`EXTERNAL_LANDSCAPE.md` is a repo-only note (dated, scoped search) that grounds the
innovation-boundary claim; it changes no code and is not part of the verified tree.

`runs/` and `negative/` raw evidence directories are deliberately **not** published here;
they are only meaningful together with the matching bundle.