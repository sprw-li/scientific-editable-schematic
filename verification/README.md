# Independent verification evidence

These documents were produced by a **separate agent that did not write any file under
`scripts/`** (an independent verifier), against a SHA-256-frozen snapshot of the skill.

| File | What it is |
|---|---|
| `REVIEW.md` | Per-property verdicts (PASS/FAIL/UNVERIFIED/N/A) with reproducible commands, plus an explicit "could not verify" section. Overall gate: **CONDITIONAL** (0 unresolved defects; ACCEPT withheld because platform-side properties are unverifiable locally). |
| `BASELINE.md` | The fair with/without comparison: same case, same canvas, naive baseline vs this skill. Reports the losses as well as the wins (wall-clock). |
| `INDEPENDENT_LIMITS.md` | What this verification cannot prove. |

Environment: local Windows, Python 3.12; the figures the verifier inspected were produced by
the real pipeline, never hand-written. These are the authors' own local fixtures -- they are
**not** the organizer's fixed cases and must not be read as such.