# Layout and SVG reference (`layout.py` / `render_svg.py`)

Owner: **layout-render**. Frozen API: `CONTRACT.md` §4.4 / §4.5.
Everything below is what the code actually does; the constants named here are
the ones in `scripts/layout.py` (`BASE_GAPS`, `COMPACTION_SCALES`,
`UNIT_PER_MM`, `LINE_FACTOR`, `LATIN_FACTOR`, `CJK_FACTOR`) and
`scripts/render_svg.py` (`LAYER_IDS`, `MIN_STROKE_PT`, `HEAD_*`, `TEE_HALF_UU`).

## 1. Unit scale

| quantity | rule |
|---|---|
| layout coordinates | **millimetres** (`x_mm`, `y_mm`, `w_mm`, `h_mm`) |
| SVG user unit | 1 uu = 1 px @ 96 dpi → `uu = mm * 96/25.4` (`UNIT_PER_MM = 3.779527559…`) |
| font size | points → uu: `uu = pt * 96/72` (never px fonts) |
| canvas | `<svg width="180mm" height="120mm" viewBox="0 0 680.315 453.543">`; `viewBox` = canvas in uu, so a 1:1 mm import is exact |

`layout.metrics` records the scale constants actually used, and the SVG embeds
them again in `<metadata>` so a reviewer can convert any number back to mm/pt
without reading this file.

## 2. Level assignment (hierarchy, upstream vs downstream)

1. **Directional edges** = `activation | inhibition | sequence | causation`
   with `direction == "forward"`. `containment`/`membership` **never** create a
   level edge; `association` and `direction == "none"/"bidirectional"` do not
   either.
2. **Cycles are broken deterministically.** A candidate is any kept edge that
   lies on a cycle (its head can reach its tail). Candidates are removed one at
   a time, best first, by this key - all criteria come from the model or the
   trial layering, never from a guess about biology:
   1. a `dashed` edge (the model's own "indirect / feedback arc" marker) is
      broken before a solid one, so the main solid chain survives;
   2. fewest skip-level edges, then smallest total level span (tightest layering);
   3. the most negative level jump in the trial layering: break the edge whose
      source stays **deep** and whose target stays **shallow** - that is a real
      backward arc. (Breaking `p53 → MDM2` instead of `MDM2 ⊣ p53` would invert
      the whole axis, which is the fatal direction error this rule prevents);
   4. most redundant endpoints (highest in+out degree), then id order.
   Removed edges become **feedback edges**: they keep their endpoints and are
   routed around the figure (`data-feedback="true"`).
   * Example: `ATM → CHK2 → p53 → CDKN1A ⊣ cyclin E-CDK2 ⇒ G1 arrest` with
     `p53 → MDM2 ⊣ p53` keeps `p53 → MDM2` forward (levels 2 → 3) and draws
     `MDM2 ⊣ p53` as the routed dashed feedback edge, never as a reversed chain.
   * Example: `SIRT1 ⊣ TRPM7` plus a hypothetical `CASP3 ⊣ TRPM7` yields
     `SIRT1(0) → TRPM7(1) → CAMK2(2) → CREB(3) → BCL2(4) → CASP3(5)`, and the
     CASP3→TRPM7 edge is the routed feedback edge.
3. **Levels** = longest path over the kept DAG, processed in deterministic
   topological order (min-heap on id). `entity.layout.level` is a **lower
   bound** only: it can never contradict a forward edge, so a bad hint degrades
   to a warning-free no-op instead of producing a contradiction.
4. **Columns** = levels. A level is one column, so "upstream" is always left of
   "downstream". Two exceptions keep dense models inside the requested canvas:
   * if a level's per-band stack would be taller than the drawing area, that
     level is split into several **side-by-side physical columns** (its
     sub-columns); the split is global per level, so every band stays aligned on
     the same grid. `layout.stats.columns` reports the *physical* column count,
     `stats.levels` the logical one, and `layout.metrics.level_cols` /
     `nodes[id].column` show the mapping (an edge from level *l* to *l+1* is
     still left-to-right because physical columns follow the level order);
   * if a model has **no** directional edge at all, columns are synthesised as
     an aspect-aware grid (`ceil(sqrt(n * w/h))`, at least
     `ceil(n / rows_capacity)`) instead of one 30-row column.

## 3. Bands = containers (containment is an enclosure)

`containers[]`, entities used as containment parents by a
`containment`/`membership` relation, and nested containers become **bands**:

* membership precedence: `entity.container` > containment relation >
  `containers[].members`; a conflict is reported (`W_CONTAINER_CONFLICT`), never
  silently dropped;
* a band is a rectangle drawn **behind** its members (`layer:containers`), so
  containment is an enclosure and never a line;
* sibling bands are packed in 2-D (`_pack`): a band goes to the lowest y whose
  x-interval is free. Side-by-side compartments therefore share a row, and
  containers never overlap by construction;
* an entity that is a containment parent is drawn **only** as an enclosure
  (id `ent:<id>`, dashed border, `data-role="entity"`) — never twice;
* container cycles (explicit or via nesting) are broken by dropping one
  membership link (`W_CONTAINER_CYCLE`) and reported as
  `E_LEVEL_REGRESSION` by `check_layout`.

## 4. Ordering inside a column (crossing reduction)

Initial order = `entity.layout.order`, then id. Then three barycentre sweeps:
each `(band, level)` stack is sorted by the mean y of its graph neighbours from
the previous placement, ties broken by `layout.order` and then id. The final
crossing count is measured geometrically (`edge_crossings_est` = proper
intersections between polylines of different edges), not estimated from level
indices.

## 5. Spacing, text fit and the compaction ladder

* text width estimate: `sum(char_factor) * font_pt * 25.4/72`, `char_factor` =
  **0.58** for Latin, **1.0** for CJK/fullwidth (ranges listed in
  `_WIDE_RANGES`); line height = `font_pt * 25.4/72 * 1.35`.
* labels are **wrapped, never truncated** (greedy at spaces, CJK-safe
  character breaks). A node box is `max(min_node_w, text + 2*pad_x)` wide and
  `max(min_node_h, lines*line_h + 2*pad_y)` high, and is additionally capped by
  the column width so boxes never overlap.
* base gaps: margin 6 mm, column gap 7 mm, row gap 3.6 mm, band gap 3.6 mm,
  container padding 2.6 mm, node padding 2.2 × 1.7 mm, minimum node 15 × 7.2 mm.
* if the content is taller than the schematic region, a **compaction ladder**
  shrinks all spacing (gaps, padding and the minimum node size) through
  ×1.0 → 0.85 → 0.7 → 0.55 → 0.42 with floors, and re-runs the geometry;
  `stats.compaction_scale` records the rung used. Sub-columns (above) usually
  absorb density before this ladder is needed;
* if it still does not fit, the canvas **grows in height only** (never wider
  than `figure.canvas`, never more than ×2) and the change is recorded in
  `stats.canvas_adjusted` + `W_CANVAS_GROWN`. Horizontal overflow is never
  hidden: `check_layout` reports `E_OUT_OF_CANVAS`.
  Exports must therefore take the size from `layout.canvas` (the layout is what
  the SVG was rendered at); `model.figure.canvas` is the *requested* size.
* when the content is smaller than the available area it is **centred
  vertically** (the band tree keeps a single `content_offset_y`), so a small
  model does not stick to the top edge of an A4-ish canvas.

## 6. Edge routing

Orthogonal polylines through free channels (inter-column gaps, band gaps, two
outer lanes); no splines, so the geometry stays hand-editable in the SVG.

| case | route |
|---|---|
| adjacent columns | exit right → gap → enter left (vertical in the column gap) |
| skip forward (span ≥ 2) | exit right → gap → nearest free horizontal lane → target gap → enter left |
| same column, adjacent rows | exit top/bottom → row gap → enter the neighbour |
| same column, far apart | side channel (gap right, or left for the last column) |
| backward (feedback / association) | exit right → gap → nearest **internal** band-gap lane (outer top/bottom lane as fallback) → target gap → enter from the right |

Heads are **explicit geometry, not `<marker>`** (a filled triangle, or a bar for
the tee), so PDF/EPS/PNG converters that ignore markers still draw the arrow
direction correctly:

| relation | head | `data-head-end` |
|---|---|---|
| activation / sequence / causation | filled arrow | `arrow` |
| inhibition | tee bar, no arrow | `tee` |
| `direction="none"` + association | none | `none` |
| `direction="bidirectional"` | both ends | `arrow`/`tee` at both |
| containment / membership | none, **grey dashed link** (the relation itself is the enclosure) | `none` |

`style.stroke == "dashed"` → `stroke-dasharray="2.6 1.8"`.

Two extra readability rules:

* **parallel edges**: relations that share the same node pair are offset
  perpendicular to their route by `(index - (n-1)/2) * 1.2 mm` in sorted-id
  order (`PARALLEL_EDGE_OFFSET_MM`), so an activation and an inhibition on the
  same pair are both visible instead of one hiding the other;
* **labels** sit on the inner side of their segment (above normally, below when
  the segment is in the upper half of the content area), so a label never runs
  into the figure title.

## 7. Chart layout (`model.figure.kind == "chart"` or `data.series`)

* pure chart figure: the whole content region is the plot (`kind == "chart"`
  does not draw entity boxes, it says so with `W_CHART_IGNORES_SCHEMATIC`);
* schematic + series (`mixed`): the schematic keeps the top, the chart gets the
  bottom 38 % (clamped 30–48 mm);
* y ticks use a 1/2/5 × 10ᵏ nice-number ladder (4–6 ticks); numeric x uses the
  same ladder, categorical x uses evenly spaced categories;
* `series[]` is used verbatim; if only `rows`/`columns` exist the series are
  **derived**: `y` = numeric column, `x` = the remaining column with the most
  distinct values, group = the remaining column with the fewest
  (`W_CHART_SERIES_DERIVED`);
* categories → grouped bars, numeric x → line + point markers;
* **legend ↔ data mapping**: if the model legend already has an entry whose
  label/value equals a series name, that entry is kept (and receives the
  series colour) instead of being duplicated; series without a legend entry get
  one derived (`lg_series_<index>_<slug>`, `data-src-kind` from the series).
  So the legend always lists exactly the series actually drawn;
* **chart figures have no entity boxes**, so each `series:<index>` group carries
  `data-legend="lg_…"` (the legend item it answers for), `data-entity="e_…"`
  (the model entity it answers for, when the names match) and `data-color`, which
  is what lets a reviewer map a legend swatch onto a chart mark. The layout keys
  are `chart.series[i].legend_id` / `.entity_id`;
* **data-mark provenance** (chart): each series and each bar/point mark carries
  `data-prov="<model.data.path>#table:<column>"` with `data-src-kind="derived"`,
  where `<column>` is `series.column` | `series.x_column` | `series.name` - the
  same binding `run.py` writes for `series:<i>` in `source_map.json`, so the map
  and the SVG agree. `data-src-kind="unsupported"` and `data-prov="(none)#(none)"`
  are used **only** when the model gives no `data.path` at all. Axis chrome uses
  the same form, named after the column its ticks come from (matched against
  `data.rows` when the model's `data.units` does not name it). Locators are
  validated against the frozen CONTRACT §4.7 set `L12|L12-L18|p3|table:col|fig:1`
  (`layout.LOCATOR_RE`), so `series[0]` / `col:x` style locators are never emitted;
* **a source with a file but no usable locator cannot be verified**, so such an
  element is normalised to the accepted placeholder `data-prov="(none)#(none)"`
  with `data-src-kind="unsupported"` instead of shipping a malformed claim. The
  only src-kinds ever emitted are `explicit`, `derived` and `unsupported`;
* **decorative chrome carries no provenance at all**: the seven `layer:*` groups
  and the legend frame (`<g id="legend:frame" data-role="legend-frame">`) have no
  `data-prov`, because they are not quoted elements. Everything that *is* quoted
  is bound, and the legend ITEMS (`lg:*`) carry the legend's provenance;
* **axis labels carry the unit**: y title = `<unit column> (<unit>)` from
  `data.units` (or the series unit), x title = the data column the category
  labels actually come from (best value match), never a guessed column;
* **a bar always includes 0 in its value domain.** A bar encodes its value by
  length, so a truncated baseline misstates the ratios between bars; the value
  axis is therefore widened to `min(0, min(y)) … max(0, max(y))` whenever any
  series is drawn as bars, and each bar rectangle is measured from the `0` line
  (`data-baseline` on the rect; negative values grow downwards). Point/line
  charts keep their natural domain, where a non-zero baseline is legitimate.
  If a hand-edited layout ever pairs bar geometry with a non-zero baseline,
  `check_layout` reports `W_BAR_BASELINE_TRUNCATED` rather than letting it ship.

## 8. SVG structure and element contract

Exactly **seven** top-level `<g id="layer:…">` groups, in this z-order, each
with a `<title>`: `layer:background`, `layer:containers`, `layer:edges`,
`layer:nodes`, `layer:labels`, `layer:legend`, `layer:annotations`.

| element | `id` | extra data attributes |
|---|---|---|
| entity box + its label text | `ent:<entity-id>` | `data-node-kind`, `data-level`, `data-container` |
| relation (line + head + label) | `rel:<relation-id>` | `data-rel-type`, `data-direction`, `data-head-start`, `data-head-end`, `data-feedback` |
| legend item | `lg:<legend-id>` | `data-legend-kind`, `data-marker`, `data-origin` (`legend`/`series`) |
| container enclosure | `cnt:<container-id>` (entity-as-container: `ent:<id>`) | `data-role`, `data-level-span` |
| figure title | `fig:title` | — |
| panel letter | `pnl:<panel-id>` | — |
| panel caption | `cap:<panel-id>` | — |
| chart axes chrome | `axes:<figure-id>` | `data-chart="axes"` (nested in `layer:background`) |
| chart data series | `series:<index>` | `data-name`, `data-unit`, `data-color`, `data-legend`, `data-entity` (in `layer:nodes`), `data-value` per mark |

Every node/relation/legend/container/title/caption element also carries
`data-prov="<path>#<locator>"` and `data-src-kind="explicit|derived|unsupported"`.
Chart chrome lives inside the seven frozen layers (axes in `background`, data
marks in `nodes`) so the layer count and z-order stay exactly 7 even for charts,
while axes/ticks/labels keep their own provenance.

Other guarantees:

* **the legend is the colour authority** (grading checks legend/colour mapping):
  * a `category`/`marker`/`value_scale` legend item whose `value`/`label` names an
    entity labels it - that entity is painted with the legend colour;
  * a `line_style` legend item whose `value` names a relation type
    (`activation`, `inhibition`, …) colours that relation;
  * `entities[].attributes.color` is honoured next;
  * anything the model does not colour is drawn **neutral**
    (`#4A5560` stroke, `#F4F7FA` fill), so every colour on the figure is
    accounted for by a legend entry. `figure.style.color_by_kind = true` opts
    into a per-kind palette, which still skips colours the legend already claims
    (lightening a palette entry by a deterministic amount when the palette is too
    small) so one colour never carries two meanings;
  * legend items that the model left without a colour inherit the matched
    entity's colour, so the mapping works in both directions;
  * `check_layout` reports `W_LEGEND_COLOR_MISMATCH` (legend colour ≠ matched
    node colour) and `W_LEGEND_COLOR_COLLISION` (one colour carrying two
    meanings) for hand-edited layouts;
* every label/title/legend entry is a real `<text>` with
  `font-family="DejaVu Sans, Liberation Sans, Arial"` (the model's stack, joined),
  `font-size` from pt→uu and an explicit `text-anchor`; **zero `<image>`**, no
  text-as-path, no embedded binary font;
* no stroked element is thinner than `MIN_STROKE_PT = 0.52 pt` (the export
  compliance gate measures every stroked element with a 0.5 pt floor; the extra
  0.02 pt leaves a margin after rounding to 3 decimals);
* `<metadata>` embeds one JSON object: `case_id`, `figure_id`, `figure_kind`,
  `model_sha256` (canonical JSON hash - deterministic), `generated_by`,
  `created_utc` (copied from the model, never `now()`), unit scale, font stack,
  palette, layer list, id scheme and the data path/sha256;
* deterministic output: sorted iteration everywhere, ties by id, no `random`,
  no `hash()`, no timestamps → identical model ⇒ byte-identical SVG.

## 9. `check_layout(layout, model, *, strict=True)`

Returns `{"errors": [...], "warnings": [...], "stats": {...}}` (same shape as
`validate_model`). Errors use only the four frozen codes:

| code | raised for |
|---|---|
| `E_NODE_OVERLAP` | two node boxes overlap, or two non-nested container boxes overlap |
| `E_OUT_OF_CANVAS` | a node/container/legend/chart/edge point leaves the canvas, or a box has no positive size |
| `E_TEXT_OVERFLOW_EST` | the label re-estimate (independent of the layout) does not fit the box, or a legend/container label leaves the canvas |
| `E_LEVEL_REGRESSION` | containment contradictions: a member outside its container, a non-member node inside a container, a container outside its parent, a containment edge whose target is outside the source enclosure, a membership cycle, or a forward directional edge drawn backwards without being marked as a feedback edge |

A **feedback edge is not an error**: it must be marked `data-feedback="true"` /
`layout.edges[i].feedback == true`; when it is, `strict=True` emits
`W_BACKWARD_EDGE` (informational). An unmarked backward edge *is*
`E_LEVEL_REGRESSION`. `strict=True` uses a 0.5 % estimate tolerance; `strict=False`
relaxes it to 5 % and only emits the structural warnings that do not depend on
the estimate. Defects are reported, never silently repaired.

## 10. Editing the SVG (or the layout) by hand

* **Text**: every label is a `<text>`; edit the content directly. Keep
  `font-family`/`font-size`/`text-anchor` so the export gates still pass. If a
  label gets longer, widen the sibling `<rect>` too (or re-run `layout.py`,
  which re-wraps and re-sizes automatically).
* **Ids and provenance**: `id="ent:…"/"rel:…"/"lg:…"` and `data-prov` are the
  join keys between the SVG, `source_map.json` and the model. When you add or
  rename an element, keep the `type:model_id` shape and copy `data-prov` from
  the model item; never leave a drawn element without provenance.
* **Direction**: change the head geometry only together with
  `data-rel-type`/`data-head-end`; a reviewer checks that inhibition is a tee.
  Marker geometry is 2–3 `<path>` elements per head, no `<marker>` defs.
* **Colors**: fills/strokes are literal `#RRGGBB` (no CSS classes, no gradients)
  so an image editor can read them; node fill = entity colour mixed 14 % with
  white.
* **Layers**: move an element between layers only if you accept the z-order
  change; do not add a new top-level `layer:*` group (the seven-group contract
  is machine-checked).
* **Preferred workflow**: edit `figure_model.json` (ids, labels, relations,
  data) and re-run `run.py render`; edit `layout.json` and re-render only for
  pure position tweaks, then verify with
  `py -3 -c "import layout,json; …check_layout(layout.json, model)"` — the same
  `check_layout` that the pipeline runs, so overlap/containment/level defects
  are caught before export.
