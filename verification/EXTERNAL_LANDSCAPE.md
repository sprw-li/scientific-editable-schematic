# External landscape — what already exists, and what this skill adds

An independent reviewer (opt member `github-reproduction-scout`) correctly flagged that the
skill's own claims about existing tools were **ungrounded absence claims**: we asserted that
"existing drawing tools do not do X" without a dated search record. This document fixes that.

Two things to be clear about up front:

1. This is a **bounded scan, not a systematic review.** It records the queries, the date, and
   what the results did and did not support. "We did not find it in this scope" is *not* the
   same as "it does not exist", and the claims below are written accordingly.
2. The scan changes **no code**. It exists to make the innovation boundary honest and checkable.

- **Scan date:** 2026-11-23 (Asia/Shanghai)
- **Method:** web search over four query families (figure tools + provenance; entity/relation
  extraction bound to source evidence; diagram tooling + provenance metadata; automated
  journal-figure compliance checking), then reading the returned sources.
- **Scope limits:** English-language web sources reachable from this machine; not a code-level
  survey of every plotting library; no vendor product evaluation (no paid accounts used).

## Claim-by-claim

### I1 — each drawn element is bound to a verbatim source quote

| Category | Found | Gap relative to this skill |
|---|---|---|
| Illustrated pathway authoring tools (e.g. BioRender) | Widely used for pathway diagrams | Described as a **visual design** tool, "primarily for visual design rather than strict data provenance or source citation" |
| LLM extraction libraries (e.g. Google **LangExtract**) | Extracts entities/relations and **binds them to source text evidence** — genuinely close to half of I1 | Produces extracted structures; it does **not** drive a drawn figure, lay it out, or carry the binding into an exported artifact and its gate |
| Figure-data tracing (e.g. FigTrace) | Traces extracted values back to their **exact pixel origin** — a real provenance mechanism | Different object: pixel provenance for values read out of literature figures, not *drawn element → verbatim quote in the source material* |
| Diagram tooling (Mermaid, Graphviz) | Text-driven diagram generation, SVG output | The sources returned **no** coverage of provenance binding or binding a node to a source quote |

**Narrowed claim.** No searched general-purpose diagram/plotting tool binds each *drawn element*
to a verbatim quote in the source material and enforces it at export time. The nearest
comparable capability is LLM extraction with source spans (LangExtract-style); this skill's
specific contribution is to carry that binding **through layout, rendering, the editable master
and the export gate**, with the enforcement expressed as a check id (`svg_provenance`, plus
locator-form validation where a malformed locator on an `explicit` claim is an error).

### I2 — interaction direction (inhibition vs activation) validated against the source wording

Not found in any returned source. The nearest thing in practice is curated pathway databases
(WikiPathways/PathVisio, Reactome), where direction is **authored by curators** rather than
validated against free text. This skill's `E_DIRECTION_UNSUPPORTED` checks the asserted relation
type against the verb actually present in the quoted source sentence — and there is a negative
test for the exact inversion (dashed negative-feedback edge broken the wrong way, which drew
`p53 ↔ MDM2` backwards until it was found by rendering the gold model).

### I3 — legend colour ↔ drawn colour checked mechanically

Not found. Charting libraries typically derive the legend from the same series objects, which
makes divergence less likely but **unverified**; we found no tool that *checks* that the legend
swatch and the drawn mark agree. Here the legend is the colour authority and a check id
(`svg_legend_color_map`, advisory) plus a two-sided per-element diff covers it. This was a real
defect class in our own code, found by that check rather than by inspection.

### I4 — pre-export journal compliance gate

Journal requirements themselves are published and unambiguous (the Nature submission guidance
returned by the scan specifies ~300 dpi, consistent Arial/Helvetica, and editable vector formats
preferred). The scan found that researchers "typically rely on professional graphic software or
publisher-specific preflight tools for automated checks", and that these are **not generally
open or scriptable**. So the *requirement* is not novel; what is missing in the open tooling is a
scriptable checker that emits per-check evidence. This skill implements one (16 check ids:
embedded fonts, DPI, minimum stroke width, colour-space declaration, parseability, PDF text
extractability, edge direction, provenance form), and every relaxation carries a negative test
(image-only PDF, tip-at-source arrow, 72 dpi raster, non-embedded fonts, truncated PNG, renamed
file, unknown format, no-geometry layout).

## What would upgrade these claims

- a versioned capability matrix with per-tool `file:line`/permalink evidence and same-fixture runs;
- explicit no-independent-reproduction vs no-comparable-method distinction;
- dependency/licence alignment for anything external (this skill pulls in **no third-party code**;
  matplotlib/Pillow/pypdf are probed at runtime and their absence is reported, never faked).

Until then the honest statement is: **as of 2026-11-23, within the scope above, no tool was found
that does these four things end-to-end; the nearest comparable capabilities are named above with
their specific gaps.**

## Sources consulted

- BioRender / pathway illustration and provenance discussion — search summary returned for "biorender pathway figure tool provenance traceability source citation"
- [Google LangExtract](https://github.com/google/langextract) — LLM entity/relation extraction bound to source text evidence
- [Mermaid](https://github.com/mermaid-js/mermaid) — text-driven diagrams, SVG output
- [Nature Communications submission guidance (PDF)](https://www.nature.com/documents/ncomms-submission-guide.pdf) — figure resolution, fonts, vector formats
- MetOrigin 2.0 (metabolite origin tracing) — domain-specific tracing platform returned by the scan
