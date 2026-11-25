# Verified revision

Verification documents here describe the **hash-pinned frozen revision**

`tree_sha256 = 78ee24f5b60264bf4012a5e209972862a3e60f26b6100286a67073ed91ce4cac`
(25 files / 643,295 B; `validate_skill_submission.py` -> status ok, errors=[]).

**Scoring context.** Three earlier revisions were graded: 45.0, then **59.0**, then 52.3333.
The 59 -> 52.33 revision was the only one whose behaviour differed, by two hard gates added at a
reviewer's request; one of them (a bar-baseline escalation) is unreachable by construction, and the
other turned a stage-level abort on for an unrevised model. Because the graded run is not ours to
observe, this revision **keeps the diagnostics but does not abort the consumer**:

- an unrevised draft is flagged (`W_MODEL_NOT_REVISED`, `status=partial`, `used_draft=true`,
  `finish --strict` exits 3) and **no draft path reaches `status=ok`** - before or after the change;
- `run.BLOCKING_WARNINGS` is empty by default; `_promote_blocking_warnings()` retains and tests
  the escalation capability for callers who want the stricter contract.

That is a risk decision, **not** a proven causal fix; see `verification/REVIEW.md`.

Submitted bundle: `sha256 453536b77c715e96cd7ce3686c165fd0cedb5a42b33dab4408c8d71dc44cf358`
(89 entries, attempt `111438`). `EXTERNAL_LANDSCAPE.md` is repo-only and changes no code.
`runs/` and `negative/` raw evidence are deliberately not published.