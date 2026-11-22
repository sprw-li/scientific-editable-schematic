# -*- coding: utf-8 -*-
"""Source-bound figure model: best-effort drafting, anti-hallucination validation,
conservative auto-repair.

Frozen API (CONTRACT.md section 4.3):
    draft_model(case_manifest, inventory) -> dict
    validate_model(model, inventory, *, strict=True) -> dict
    auto_fix(model, issues) -> dict

The validator is the product: every label / number / unit that reaches the figure
must occur in the source inventory, and every asserted relation direction must be
supported by the verb actually found in the quoted source fragment.

Error codes (error level):
    E_PROVENANCE_MISSING E_QUOTE_NOT_FOUND E_LABEL_NOT_IN_SOURCE
    E_DIRECTION_UNSUPPORTED E_UNIT_MISSING E_LEGEND_DATA_MISMATCH
    E_ORPHAN_RELATION E_DUP_ID E_CONTAINER_CYCLE E_DANGLING_REF
    E_NUMBER_NOT_IN_SOURCE E_CONTRACT_KEY_MISSING
Warning codes:
    W_AMBIGUOUS_LEVEL W_LONG_LABEL W_NO_PANEL_ID W_COLOR_NOT_IN_PALETTE
    W_UNSUPPORTED_STYLE W_EMPTY_LEGEND
"""

from __future__ import annotations

import os
import re
import sys
from copy import deepcopy

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import common  # noqa: E402
import ingest  # noqa: E402

SCHEMA_VERSION = common.SCHEMA_VERSION

REQUIRED_TOP_KEYS = ("schema_version", "case_id", "figure", "entities", "relations",
                     "containers", "legend", "provenance")
FIGURE_KINDS = ("relationship_schematic", "chart", "flowchart", "mixed")
ENTITY_KINDS = ("gene", "protein", "process", "treatment", "sample", "category",
                "axis", "concept", "compound", "cell", "condition")
RELATION_TYPES = ingest.RELATION_TYPES
DIRECTIONS = ("forward", "bidirectional", "none")
LEGEND_KINDS = ("category", "marker", "line_style", "value_scale")
SOURCE_KINDS = ("explicit", "derived", "unsupported")
DWARF_STYLES = ("solid", "dashed", "dotted")

DEFAULT_PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#56B4E9", "#F0E442"]
LONG_LABEL_CHARS = 40
TITLE_LONG_CHARS = 80

PROVENANCE_CODES = ("E_PROVENANCE_MISSING", "E_QUOTE_NOT_FOUND",
                    "E_LABEL_NOT_IN_SOURCE", "E_NUMBER_NOT_IN_SOURCE")

#: error codes that draft-stage (strict=False) validation deliberately defers to
#: the Agent revision step
SOFT_CODES = ("E_LABEL_NOT_IN_SOURCE", "E_NUMBER_NOT_IN_SOURCE", "E_UNIT_MISSING",
              "E_LEGEND_DATA_MISMATCH")


def _err(errors, code, message, where):
    errors.append({"code": code, "message": message, "where": where})


def _warn(warnings, code, message, where):
    warnings.append({"code": code, "message": message, "where": where})


# --------------------------------------------------------------------------
# validate_model()
# --------------------------------------------------------------------------
def _as_list(value):
    return value if isinstance(value, list) else []


def _elem_where(kind, obj, index):
    if isinstance(obj, dict) and obj.get("id"):
        return "%s.%s" % (kind, obj["id"])
    return "%s[%d]" % (kind, index)


def _check_source(where, src, index, errors, warnings, required=True):
    """Provenance binding check. Returns one of: ok | derived | unsupported | missing."""
    if src is None and not required:
        return "ok"
    if not isinstance(src, dict):
        _err(errors, "E_PROVENANCE_MISSING",
             "no source binding (a path/locator/kind object is required)", where)
        return "missing"
    kind = src.get("kind")
    if kind not in SOURCE_KINDS:
        _err(errors, "E_PROVENANCE_MISSING",
             "source.kind must be one of %s (got %r)" % (list(SOURCE_KINDS), kind), where)
        return "missing"
    if kind == "unsupported":
        _warn(warnings, "W_UNSUPPORTED_STYLE",
              "element explicitly marked unsupported: it is NOT source-bound and must not "
              "be presented as evidence", where)
        return "unsupported"
    path = str(src.get("path") or "")
    locator = str(src.get("locator") or "")
    if not path:
        _err(errors, "E_PROVENANCE_MISSING", "source.path is empty", where)
        return "missing"
    if not locator:
        _err(errors, "E_PROVENANCE_MISSING",
             "source.locator is empty (the schema requires path+locator+kind; use e.g. "
             "'L12', 'L12-L18', 'p3' or 'table:<col>')", where)
        return "missing"
    if not index.has_path(path):
        _err(errors, "E_PROVENANCE_MISSING",
             "source.path %r is not present in the source inventory" % path, where)
        return "missing"
    if kind == "derived" and not _as_list(src.get("derived_from")):
        _err(errors, "E_PROVENANCE_MISSING",
             "derived source must list derived_from[] (which sources were combined)", where)
        return "missing"
    quote = str(src.get("quote") or "")
    if kind == "explicit":
        if not quote.strip():
            _err(errors, "E_QUOTE_NOT_FOUND", "explicit source has an empty quote", where)
            return "missing"
    if quote.strip() and not index.find_quote(path, locator, quote):
        _err(errors, "E_QUOTE_NOT_FOUND",
             "quote not found verbatim in %s#%s: %r" % (path, locator, quote[:80]), where)
        return "missing"
    return "derived" if kind == "derived" else "ok"


def _check_label(where, label, index, errors):
    if not str(label or "").strip():
        return
    if index.has_text(label) or index.has_text(ingest.strip_decorations(label)):
        return
    _err(errors, "E_LABEL_NOT_IN_SOURCE",
         "label %r does not occur anywhere in the source inventory" % label, where)


def _check_numbers(where, texts, index, errors):
    for text in texts:
        if text is None:
            continue
        for tok in ingest.numbers_in_text(text):
            if not index.has_number(tok):
                _err(errors, "E_NUMBER_NOT_IN_SOURCE",
                     "number %r does not occur in the source inventory" % tok, where)
                return


def _check_unsupported_style(warnings, where, style):
    if not isinstance(style, dict):
        return
    stroke = style.get("stroke")
    arrow = style.get("arrow")
    if stroke is not None and stroke not in DWARF_STYLES:
        _warn(warnings, "W_UNSUPPORTED_STYLE",
              "stroke %r is not one of %s" % (stroke, list(DWARF_STYLES)), where)
    if arrow is not None and arrow not in ("normal", "tee", "none"):
        _warn(warnings, "W_UNSUPPORTED_STYLE", "arrow %r is not a supported arrow head" % arrow,
              where)


def validate_model(model, inventory, *, strict=True):
    """Prove that every figure element is bound to the source inventory.

    ``strict=True`` runs the full gate (numbers, units, legend/data consistency).
    ``strict=False`` is the draft-stage profile: structural + provenance errors are
    still reported, while the soft codes in :data:`SOFT_CODES` are deferred.
    """
    errors = []
    warnings = []
    stats = {}
    index = ingest.SourceIndex(inventory)

    def emit(code, message, where):
        if not strict and code in SOFT_CODES:
            return
        _err(errors, code, message, where)

    if not isinstance(model, dict):
        _err(errors, "E_CONTRACT_KEY_MISSING", "model is not a JSON object", "")
        return {"errors": errors, "warnings": warnings,
                "stats": {"strict": bool(strict), "errors": len(errors),
                          "warnings": len(warnings)}}

    for key in REQUIRED_TOP_KEYS:
        if key not in model:
            _err(errors, "E_CONTRACT_KEY_MISSING", "missing required top-level key %r" % key, key)

    figure = model.get("figure") if isinstance(model.get("figure"), dict) else None
    if figure is None:
        _err(errors, "E_CONTRACT_KEY_MISSING", "figure must be an object", "figure")
    else:
        for key in ("id", "kind", "canvas"):
            if key not in figure:
                _err(errors, "E_CONTRACT_KEY_MISSING",
                     "figure is missing required key %r" % key, "figure.%s" % key)
        if "kind" in figure and figure.get("kind") not in FIGURE_KINDS:
            _err(errors, "E_CONTRACT_KEY_MISSING",
                 "figure.kind %r is not in the frozen enum" % figure.get("kind"), "figure.kind")
        canvas = figure.get("canvas")
        if canvas is not None:
            if not isinstance(canvas, dict):
                _err(errors, "E_CONTRACT_KEY_MISSING", "figure.canvas must be an object",
                     "figure.canvas")
            else:
                for key in ("width_mm", "height_mm"):
                    v = canvas.get(key)
                    if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
                        _err(errors, "E_CONTRACT_KEY_MISSING",
                             "figure.canvas.%s must be a positive number" % key,
                             "figure.canvas.%s" % key)
        style = figure.get("style")
        if isinstance(style, dict):
            cs = style.get("color_space")
            if cs is not None and cs not in ("RGB", "CMYK"):
                _warn(warnings, "W_UNSUPPORTED_STYLE",
                      "color_space %r is not RGB/CMYK" % cs, "figure.style.color_space")
            if not _as_list(style.get("font_stack")):
                _warn(warnings, "W_UNSUPPORTED_STYLE",
                      "figure.style.font_stack is empty: font fallback is undecidable",
                      "figure.style.font_stack")
        title = figure.get("title")
        if isinstance(title, dict) and str(title.get("text") or "").strip():
            _check_source("figure.title", title.get("source"), index, errors, warnings)
            _check_numbers("figure.title", [title.get("text")], index, errors)
            if len(str(title.get("text"))) > TITLE_LONG_CHARS:
                _warn(warnings, "W_LONG_LABEL",
                      "figure title is %d chars (> %d): check it fits the canvas"
                      % (len(str(title.get("text"))), TITLE_LONG_CHARS), "figure.title")

    palette = []
    if figure and isinstance(figure.get("style"), dict):
        palette = [str(c) for c in _as_list(figure["style"].get("palette")) if c]
    palette_lc = {c.lower() for c in palette}

    used_colors = []

    # ---------------- entities ----------------
    entities = _as_list(model.get("entities"))
    entity_ids = set()
    seen_eids = set()
    for i, ent in enumerate(entities):
        where = _elem_where("entities", ent, i)
        if not isinstance(ent, dict):
            _err(errors, "E_CONTRACT_KEY_MISSING", "entity entry is not an object", where)
            continue
        for key in ("id", "label", "kind"):
            if not ent.get(key):
                _err(errors, "E_CONTRACT_KEY_MISSING",
                     "entity is missing required key %r" % key, where)
        if ent.get("kind") and ent.get("kind") not in ENTITY_KINDS:
            _err(errors, "E_CONTRACT_KEY_MISSING",
                 "entity.kind %r is not in the frozen enum" % ent.get("kind"), where)
        eid = ent.get("id")
        if eid:
            if eid in seen_eids:
                _err(errors, "E_DUP_ID", "duplicate entity id %r" % eid, where)
            seen_eids.add(eid)
            entity_ids.add(eid)
        status = _check_source(where, ent.get("source"), index, errors, warnings)
        if status not in ("unsupported",) and ent.get("label"):
            _check_label(where, ent["label"], index, errors)
        _check_numbers(where, [ent.get("label"), ent.get("value"), ent.get("unit")],
                       index, errors)
        if isinstance(ent.get("value"), (int, float)) and not isinstance(ent.get("value"), bool):
            if not str(ent.get("unit") or "").strip():
                emit("E_UNIT_MISSING",
                     "numeric entity value has no unit (entities.%s.unit)" % (eid or i), where)
        label = str(ent.get("label") or "")
        if len(label) > LONG_LABEL_CHARS:
            _warn(warnings, "W_LONG_LABEL",
                  "entity label is %d chars (> %d)" % (len(label), LONG_LABEL_CHARS), where)
        attrs = ent.get("attributes")
        if isinstance(attrs, dict) and attrs.get("color"):
            used_colors.append((str(attrs["color"]), where))

    # ---------------- relations ----------------
    relations = _as_list(model.get("relations"))
    container_ids = set()
    for i, con in enumerate(_as_list(model.get("containers"))):
        if isinstance(con, dict) and con.get("id"):
            container_ids.add(con["id"])

    seen_rids = set()
    level_of = {}
    for ent in entities:
        if isinstance(ent, dict) and isinstance(ent.get("layout"), dict):
            lvl = ent["layout"].get("level")
            if isinstance(lvl, int) and not isinstance(lvl, bool) and ent.get("id"):
                level_of[ent["id"]] = lvl

    for i, rel in enumerate(relations):
        where = _elem_where("relations", rel, i)
        if not isinstance(rel, dict):
            _err(errors, "E_CONTRACT_KEY_MISSING", "relation entry is not an object", where)
            continue
        for key in ("id", "from", "to", "type", "direction"):
            if not rel.get(key):
                _err(errors, "E_CONTRACT_KEY_MISSING",
                     "relation is missing required key %r" % key, where)
        rid = rel.get("id")
        if rid:
            if rid in seen_rids:
                _err(errors, "E_DUP_ID", "duplicate relation id %r" % rid, where)
            seen_rids.add(rid)
        if rel.get("type") and rel.get("type") not in RELATION_TYPES:
            _err(errors, "E_CONTRACT_KEY_MISSING",
                 "relation.type %r is not in the frozen enum" % rel.get("type"), where)
        if rel.get("direction") and rel.get("direction") not in DIRECTIONS:
            _err(errors, "E_CONTRACT_KEY_MISSING",
                 "relation.direction %r is not in the frozen enum" % rel.get("direction"), where)

        src = rel.get("source")
        status = _check_source(where, src, index, errors, warnings)

        frm, to = rel.get("from"), rel.get("to")
        if frm and to and (frm not in entity_ids or to not in entity_ids):
            missing = [x for x in (frm, to) if x not in entity_ids]
            _err(errors, "E_ORPHAN_RELATION",
                 "relation endpoint(s) %s do not exist in entities: the arrow floats "
                 "without a node" % ", ".join(repr(m) for m in missing), where)

        # direction semantics from the verb actually present in the quoted source
        if status != "unsupported":
            quote = ""
            if isinstance(src, dict):
                quote = str(src.get("quote") or "")
            blob = quote
            if not blob and isinstance(src, dict) and src.get("path"):
                blob = " ".join(index.unit_texts(src.get("path"), src.get("locator")))
            cues = ingest.cues_in_text(blob) if blob else {}
            rtype = rel.get("type")
            if cues:
                main_cues = [c for c in cues if c != "bidirectional"]
                if rtype in RELATION_TYPES and rtype not in ("association", "membership"):
                    if rtype not in cues and main_cues:
                        _err(errors, "E_DIRECTION_UNSUPPORTED",
                             "asserted type %r contradicts the source verb(s) %s in %r"
                             % (rtype, {c: cues[c] for c in main_cues}, blob[:80]), where)
                direction = rel.get("direction") or "forward"
                if "bidirectional" in cues and direction == "forward":
                    _err(errors, "E_DIRECTION_UNSUPPORTED",
                         "source says the interaction is bidirectional (%s) but direction is "
                         "'forward'" % cues["bidirectional"], where)
                if direction == "bidirectional" and "bidirectional" not in cues:
                    _err(errors, "E_DIRECTION_UNSUPPORTED",
                         "direction is 'bidirectional' but the source quote contains no "
                         "bidirectional cue", where)

        _check_numbers(where, [rel.get("label")], index, errors)
        style = rel.get("style")
        _check_unsupported_style(warnings, where, style)
        if isinstance(style, dict) and style.get("color"):
            used_colors.append((str(style["color"]), where))

        if (rel.get("type") in ("activation", "inhibition", "sequence", "causation")
                and frm in level_of and to in level_of and frm != to
                and level_of[to] <= level_of[frm]):
            _warn(warnings, "W_AMBIGUOUS_LEVEL",
                  "relation %s->%s goes to level %d from level %d: hierarchy may be "
                  "inverted or ambiguous" % (frm, to, level_of[to], level_of[frm]), where)

    # ---------------- containers ----------------
    containers = _as_list(model.get("containers"))
    seen_cids = set()
    for i, con in enumerate(containers):
        where = _elem_where("containers", con, i)
        if not isinstance(con, dict):
            _err(errors, "E_CONTRACT_KEY_MISSING", "container entry is not an object", where)
            continue
        for key in ("id", "label"):
            if not con.get(key):
                _err(errors, "E_CONTRACT_KEY_MISSING",
                     "container is missing required key %r" % key, where)
        cid = con.get("id")
        if cid:
            if cid in seen_cids:
                _err(errors, "E_DUP_ID", "duplicate container id %r" % cid, where)
            seen_cids.add(cid)
        status = _check_source(where, con.get("source"), index, errors, warnings)
        if status != "unsupported" and con.get("label"):
            _check_label(where, con["label"], index, errors)
        _check_numbers(where, [con.get("label")], index, errors)
        members = con.get("members")
        if not isinstance(members, list) or not members:
            _err(errors, "E_CONTRACT_KEY_MISSING",
                 "container.members must be a non-empty array", where)
        else:
            for m in members:
                if m not in entity_ids and m not in container_ids:
                    _err(errors, "E_DANGLING_REF",
                         "container member %r is neither a defined entity nor a nested "
                         "container" % m, where)

    # container -> container edges (nested grouping) must stay acyclic
    edges = {}
    for con in containers:
        if not isinstance(con, dict) or not con.get("id"):
            continue
        for m in _as_list(con.get("members")):
            if m in container_ids:
                edges.setdefault(con["id"], []).append(m)
    cycle_reported = set()

    def _dfs(node, stack):
        for nxt in edges.get(node, []):
            if nxt in stack:
                key = tuple(sorted(stack + [nxt]))
                if key not in cycle_reported:
                    cycle_reported.add(key)
                    _err(errors, "E_CONTAINER_CYCLE",
                         "container membership cycle: %s" % " -> ".join(stack + [nxt]),
                         "containers.%s" % node)
                continue
            _dfs(nxt, stack + [nxt])

    for node in sorted(edges):
        _dfs(node, [node])

    # entity.container references
    for i, ent in enumerate(entities):
        if not isinstance(ent, dict):
            continue
        con = ent.get("container")
        if con and con not in container_ids:
            _err(errors, "E_DANGLING_REF",
                 "entity.container %r is not a defined container" % con,
                 _elem_where("entities", ent, i))

    # ---------------- legend ----------------
    legend = _as_list(model.get("legend"))
    seen_lids = set()
    legend_cats = []
    for i, item in enumerate(legend):
        where = _elem_where("legend", item, i)
        if not isinstance(item, dict):
            _err(errors, "E_CONTRACT_KEY_MISSING", "legend entry is not an object", where)
            continue
        for key in ("id", "label", "kind"):
            if not item.get(key):
                _err(errors, "E_CONTRACT_KEY_MISSING",
                     "legend item is missing required key %r" % key, where)
        if item.get("kind") and item.get("kind") not in LEGEND_KINDS:
            _err(errors, "E_CONTRACT_KEY_MISSING",
                 "legend.kind %r is not in the frozen enum" % item.get("kind"), where)
        lid = item.get("id")
        if lid:
            if lid in seen_lids:
                _err(errors, "E_DUP_ID", "duplicate legend id %r" % lid, where)
            seen_lids.add(lid)
        status = _check_source(where, item.get("source"), index, errors, warnings)
        if status != "unsupported" and item.get("label"):
            _check_label(where, item["label"], index, errors)
        _check_numbers(where, [item.get("label"), item.get("value")], index, errors)
        if item.get("color"):
            used_colors.append((str(item["color"]), where))
        if item.get("kind") == "category":
            legend_cats.append(item)

    # ---------------- data / legend-data gate ----------------
    data = model.get("data")
    numeric_cols = []
    if isinstance(data, dict):
        cols = [str(c) for c in _as_list(data.get("columns"))]
        rows = [r for r in _as_list(data.get("rows")) if isinstance(r, (list, tuple))]
        units = data.get("units") if isinstance(data.get("units"), dict) else {}
        for idx, col in enumerate(cols):
            vals = [r[idx] for r in rows if idx < len(r)]
            numeric = [v for v in vals if re.fullmatch(r"\s*-?\d+(?:\.\d+)?\s*", str(v))]
            if numeric:
                numeric_cols.append(col)
        series = [s for s in _as_list(data.get("series")) if isinstance(s, dict)]
        if series:
            for s in series:
                if s.get("color"):
                    used_colors.append((str(s["color"]), "data.series.%s" % s.get("name")))
            names = [str(s.get("name")) for s in series if s.get("name")]
            unique_names = sorted(set(names))
            if not legend:
                _warn(warnings, "W_EMPTY_LEGEND",
                      "data has %d series but the legend is empty: readers cannot map "
                      "colours to categories" % len(series), "legend")
            elif legend_cats:
                if len(legend_cats) != len(unique_names):
                    emit("E_LEGEND_DATA_MISMATCH",
                         "legend has %d category item(s) but the data has %d categor%s "
                         "(%s)" % (len(legend_cats), len(unique_names),
                                   "y" if len(unique_names) == 1 else "ies",
                                   ", ".join(unique_names)),
                         "legend")
                for s in series:
                    name = str(s.get("name"))
                    match = None
                    for item in legend_cats:
                        cand = [str(item.get("value") or ""), str(item.get("label") or ""),
                                ingest.strip_decorations(item.get("label") or "")]
                        if name and name in cand:
                            match = item
                            break
                    if match is None:
                        emit("E_LEGEND_DATA_MISMATCH",
                             "series %r has no matching legend category" % name, "legend")
                    else:
                        a, b = str(match.get("color") or ""), str(s.get("color") or "")
                        if a and b and a.lower() != b.lower():
                            emit("E_LEGEND_DATA_MISMATCH",
                                 "legend colour %s for %r does not match series colour %s"
                                 % (a, name, b), "legend")
        # units for numeric columns
        series_unit = all(str(s.get("unit") or "").strip() for s in series) and bool(series)
        for col in numeric_cols:
            if not str(units.get(col) or "").strip() and not series_unit:
                emit("E_UNIT_MISSING",
                     "numeric column %r has no unit (data.units[%r] or every series.unit)"
                     % (col, col), "data.units.%s" % col)
        # numbers inside the data table must also be source-bound (one report per block)
        for r_i, row in enumerate(rows):
            bad = None
            for v in row:
                if isinstance(v, str) and re.fullmatch(r"\s*-?\d+(?:\.\d+)?\s*", v):
                    for tok in ingest.numbers_in_text(v):
                        if not index.has_number(tok):
                            bad = (v, tok)
                            break
                if bad:
                    break
            if bad:
                emit("E_NUMBER_NOT_IN_SOURCE",
                     "data value %r (row %d) does not occur in the source inventory"
                     % (bad[0], r_i), "data.rows[%d]" % r_i)
                break

    # ---------------- panels ----------------
    if isinstance(figure, dict) and figure.get("kind") == "chart":
        has_data = isinstance(data, dict) and bool(_as_list(data.get("rows"))
                                                   or _as_list(data.get("series")))
        if not has_data:
            _err(errors, "E_CONTRACT_KEY_MISSING",
                 "figure.kind is 'chart' but there is no data (rows/series): a data-driven "
                 "figure cannot be produced or re-generated from updated data", "data")
    panels = _as_list(model.get("panels"))
    for i, panel in enumerate(panels):
        if not isinstance(panel, dict) or not str(panel.get("id") or "").strip():
            _warn(warnings, "W_NO_PANEL_ID",
                  "panel entry %d has no id: sub-figure numbering is undecidable" % i,
                  "panels[%d]" % i)
            continue
        caption = panel.get("caption")
        if isinstance(caption, dict) and str(caption.get("text") or "").strip():
            _check_source("panels.%s.caption" % panel.get("id"), caption.get("source"),
                          index, errors, warnings)
            _check_numbers("panels.%s.caption" % panel.get("id"), [caption.get("text")],
                           index, errors)
    if isinstance(figure, dict) and figure.get("kind") == "mixed" and not panels:
        _warn(warnings, "W_NO_PANEL_ID", "figure.kind is 'mixed' but no panels are declared",
              "panels")

    # ---------------- palette ----------------
    if palette_lc:
        seen_colors = set()
        for color, where in used_colors:
            if not color or color.lower() in palette_lc or color.lower() in seen_colors:
                continue
            seen_colors.add(color.lower())
            _warn(warnings, "W_COLOR_NOT_IN_PALETTE",
                  "colour %s is not in figure.style.palette: colour mapping is not "
                  "reproducible from the declared palette" % color, where)

    stats = {
        "strict": bool(strict),
        "entities": len(entities),
        "relations": len(relations),
        "containers": len(containers),
        "legend_items": len(legend),
        "numeric_columns": len(numeric_cols),
        "source_units": sum(len(v) for v in index.units_by_path.values()),
        "source_unit_paths": len(index.units_by_path),
        "source_tables": sum(len(v) for v in index.tables_by_path.values()),
        "errors": len(errors),
        "warnings": len(warnings),
        "checked_utc": common.now_utc(),
    }
    return {"errors": errors, "warnings": warnings, "stats": stats}


# --------------------------------------------------------------------------
# draft_model()
# --------------------------------------------------------------------------
_MATERIAL_STOP = {
    "THE", "THIS", "THAT", "WITH", "FROM", "AND", "FOR", "NOT", "ALL", "BUT", "ARE",
    "TASK", "NOTE", "SOURCE", "MATERIAL", "MATERIALS", "TABLE", "FIGURE", "FIG", "DATA",
    "CSV", "TSV", "JSON", "YAML", "MD", "PDF", "PNG", "SVG", "TIFF", "EPS", "UTF",
    "KB", "MB", "NA", "SD", "SEM", "CI", "VS", "INPUT", "OUTPUT", "WORK", "SKILL",
    "README", "CODE", "TEXT", "FILE", "FILES", "PT", "MM", "DPI", "RGB",
}
_LATIN_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(\d+[-/][A-Za-z][A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*"
    r"|[A-Z][A-Za-z0-9]{1,}(?:[-/][A-Za-z0-9]+)*)"
    r"(?![A-Za-z0-9])")
_CJK_CAND_RE = re.compile(r"[\u4e00-\u9fff]{2,6}(?:模块|通路|过程|因子|组|样本|细胞)")
_CLAUSE_SPLIT_RE = re.compile(r"[。；;！!？?\n]")
_REL_CLAUSE_SPLIT_RE = re.compile(r"[。；;！!？?\n，,]")
_SUB_SPLIT_RE = re.compile(r"[，,、]")
_CJK_BAD_CHARS = set("的为与和及并被把将记该其此了对在是")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")


def _clip(text, limit):
    s = str(text or "").strip()
    return s if len(s) <= limit else s[: max(0, limit - 1)] + "…"


def _quote_around(unit_text, token):
    """A contiguous, verbatim fragment of `unit_text` containing `token`."""
    for seg in _CLAUSE_SPLIT_RE.split(unit_text):
        if token in seg:
            candidate = seg.strip()
            if not candidate:
                continue
            if len(candidate) > 160:
                pos = candidate.find(token)
                start = max(0, pos - 60)
                candidate = candidate[start:start + 160].strip()
            if token in candidate:
                return candidate
    for seg in _SUB_SPLIT_RE.split(unit_text):
        if token in seg and seg.strip():
            return seg.strip()
    return unit_text.strip()


def _entity_kind(token, context):
    if re.search(r"激酶|蛋白|kinase|protein", context):
        return "protein"
    if re.search(r"基因|gene", context):
        return "gene"
    if re.search(r"处理|抑制剂|treatment|inhibitor", context):
        return "treatment"
    if re.search(r"凋亡|过程|process|通路", context):
        return "process"
    if re.match(r"^\d+[A-Za-z]", token) or re.search(r"\d", token):
        return "protein"
    return "concept"


def _slug_id(prefix, label, used):
    stem = common.slug(label, fallback="")
    if not stem:
        stem = "x" + common.sha256_text(str(label))[:6]
    base = "%s_%s" % (prefix, stem)
    cand = base
    n = 2
    while cand in used:
        cand = "%s_%d" % (base, n)
        n += 1
    used.add(cand)
    return cand


def draft_model(case_manifest, inventory):
    """Best-effort first pass: entities/relations/containers/legend/data + uncertainties.

    Everything the extractor is not sure about goes into ``model["uncertainty"]``;
    nothing is invented to look complete.
    """
    case_manifest = case_manifest if isinstance(case_manifest, dict) else {}
    inventory = inventory if isinstance(inventory, dict) else {}
    index = ingest.SourceIndex(inventory)
    uncertainties = []

    fig_hint = case_manifest.get("figure_hint") or {}
    fig_kind = fig_hint.get("kind")
    if fig_kind not in FIGURE_KINDS:
        fig_kind = "relationship_schematic"
    canvas_hint = fig_hint.get("canvas") if isinstance(fig_hint.get("canvas"), dict) else {}
    width = canvas_hint.get("width_mm") or 180
    height = canvas_hint.get("height_mm") or 120
    fig_id = fig_hint.get("id") or common.stem_of(case_manifest.get("case_id") or "figure")

    # ---- entity candidates from text -----------------------------------
    used_ids = set()
    entities = []
    by_label = {}
    units_sorted = sorted(
        [u for u in inventory.get("units") or [] if isinstance(u, dict)],
        key=lambda u: (str(u.get("path") or ""), u.get("line") or 0))

    for unit in units_sorted:
        if str(unit.get("kind") or "") == "metadata":
            continue  # case.json / task.md are metadata, never scientific body text
        text = str(unit.get("text") or "")
        path = str(unit.get("path") or "")
        locator = str(unit.get("locator") or "")
        for m in _LATIN_TOKEN_RE.finditer(text):
            token = m.group(1)
            if token.upper() in _MATERIAL_STOP or len(token) < 2:
                continue
            key = ingest.normalise_text(token)
            if key in by_label:
                continue
            quote = _quote_around(text, token)
            findable = index.find_quote(path, locator, quote)
            source = {"path": path, "locator": locator, "kind": "explicit",
                      "quote": quote if findable else token}
            if not index.find_quote(source["path"], source["locator"], source["quote"]):
                source = {"path": path, "locator": locator, "kind": "unsupported",
                          "quote": ""}
                uncertainties.append({
                    "where": "entities.%s" % token,
                    "issue": "candidate token %r could not be bound to a verbatim quote in %s#%s"
                             % (token, path, locator),
                    "action": "confirm in the material or drop the entity"})
            kind = _entity_kind(token, text)
            ent = {"id": _slug_id("e", token, used_ids), "label": token, "kind": kind,
                   "container": None, "source": source}
            if kind == "protein" and not re.search(r"激酶|蛋白|kinase|protein",
                                                   text[max(0, m.start() - 12):m.end() + 12]):
                uncertainties.append({
                    "where": "entities.%s" % ent["id"],
                    "issue": "entity kind guessed as 'protein' from name shape only",
                    "action": "correct kind (gene/protein/process/...) after reading the material"})
            entities.append(ent)
            by_label[key] = ent

    cjk_ids = set()
    for unit in units_sorted:
        if str(unit.get("kind") or "") == "metadata":
            continue
        text = str(unit.get("text") or "")
        if text.lstrip().startswith("#"):
            continue  # section headings are structure, not named entities
        for m in _CJK_CAND_RE.finditer(text):
            token = m.group(0)
            key = ingest.normalise_text(token)
            if key in by_label:
                continue
            if any(ch in _CJK_BAD_CHARS for ch in token):
                continue
            if any(cue in token for cue in ingest.VERB_LEXICON["activation"]
                   + ingest.VERB_LEXICON["inhibition"] + ingest.VERB_LEXICON["containment"]):
                continue
            if not index.has_text(token):
                continue
            path = str(unit.get("path") or "")
            locator = str(unit.get("locator") or "")
            quote = _quote_around(text, token)
            if not index.find_quote(path, locator, quote):
                quote = token
            entities.append({"id": _slug_id("e", token, used_ids), "label": token,
                             "kind": "concept", "container": None,
                             "source": {"path": path, "locator": locator,
                                        "kind": "explicit", "quote": quote}})
            by_label[key] = entities[-1]
            cjk_ids.add(entities[-1]["id"])
            uncertainties.append({
                "where": "entities.%s" % entities[-1]["id"],
                "issue": "CJK candidate %r extracted by suffix pattern; kind/role unverified"
                         % token,
                "action": "verify it is a real named entity, not prose"})

    # category entities + legend + data from tables
    tables = [t for t in inventory.get("tables") or [] if isinstance(t, dict)]
    legend = []
    data_obj = None
    used_lg = set()
    palette = list(DEFAULT_PALETTE)
    for table in tables:
        cols = [str(c) for c in table.get("columns") or []]
        rows = [r for r in table.get("rows") or [] if isinstance(r, (list, tuple))]
        keys = [k for k in (table.get("keys") or []) if k in cols]
        numeric = []
        for i, col in enumerate(cols):
            vals = [str(r[i]) for r in rows if i < len(r)]
            if vals and all(re.fullmatch(r"\s*-?\d+(?:\.\d+)?\s*", v) for v in vals if v):
                numeric.append(col)
        group_col = keys[0] if keys else None
        if group_col:
            gi = cols.index(group_col)
            seen = []
            for r in rows:
                if gi < len(r) and str(r[gi]) not in seen:
                    seen.append(str(r[gi]))
            for j, value in enumerate(seen):
                value_key = ingest.normalise_text(value)
                if value_key not in by_label:
                    ent = {"id": _slug_id("e", value, used_ids), "label": value,
                           "kind": "category", "container": None,
                           "source": {"path": table.get("path"),
                                      "locator": "table:%s" % group_col,
                                      "kind": "explicit", "quote": value}}
                    entities.append(ent)
                    by_label[value_key] = ent
                legend.append({
                    "id": _slug_id("lg", value, used_lg), "label": value, "kind": "category",
                    "value": value, "color": palette[j % len(palette)], "marker": "circle",
                    "source": {"path": table.get("path"), "locator": "table:%s" % group_col,
                               "kind": "explicit", "quote": value}})
            if legend:
                uncertainties.append({
                    "where": "legend",
                    "issue": "legend colours were auto-assigned from the default palette; the "
                             "material may define its own mapping",
                    "action": "confirm colours/markers against the material, keep legend "
                              "categories == data categories"})
        if group_col and numeric:
            num_col = numeric[0]
            yidx = cols.index(num_col)
            label_col = None
            for k in keys[1:]:
                label_col = k
                break
            xidx = cols.index(label_col) if label_col else None
            series = []
            unit = (table.get("units") or {}).get(num_col) or None
            for j, value in enumerate(dict.fromkeys(str(r[cols.index(group_col)])
                                                    for r in rows
                                                    if cols.index(group_col) < len(r))):
                xs, ys = [], []
                for r in rows:
                    if cols.index(group_col) >= len(r) or str(r[cols.index(group_col)]) != value:
                        continue
                    if yidx >= len(r):
                        continue
                    if xidx is not None and xidx < len(r):
                        xs.append(str(r[xidx]))
                    else:
                        xs.append(len(xs) + 1)
                    try:
                        ys.append(float(r[yidx]))
                    except (TypeError, ValueError):
                        ys.append(r[yidx])
                series.append({"name": value, "x": xs, "y": ys, "unit": unit,
                               "color": palette[j % len(palette)]})
            data_obj = {"path": table.get("path"), "sha256": table.get("sha256"),
                        "columns": cols, "units": dict(table.get("units") or {}),
                        "rows": [[str(c) for c in r] for r in rows], "series": series}
            if not unit:
                uncertainties.append({
                    "where": "data.units.%s" % num_col,
                    "issue": "numeric column %r has no unit in the table header" % num_col,
                    "action": "find the unit verbatim in the material and put it in "
                              "data.units (or in every series.unit)"})
            break

    # ---- relations from verb cues --------------------------------------
    arrow_color = {"activation": "#0072B2", "inhibition": "#D55E00",
                   "sequence": "#009E73", "causation": "#CC79A7",
                   "association": "#56B4E9", "membership": "#F0E442",
                   "containment": "#000000"}
    relations = []
    containers = []
    seen_rel = set()
    seen_con = set()
    used_rel_ids = set()
    used_con_ids = set()
    for unit in units_sorted:
        text = str(unit.get("text") or "")
        path = str(unit.get("path") or "")
        locator = str(unit.get("locator") or "")
        last_seen = None
        for clause in _REL_CLAUSE_SPLIT_RE.split(text):
            clause = clause.strip()
            if not clause:
                continue
            cues = ingest.cues_in_text(clause)
            latin_hits, cjk_hits = [], []
            for m in _LATIN_TOKEN_RE.finditer(clause):
                tok = m.group(1)
                if tok.upper() in _MATERIAL_STOP or len(tok) < 2:
                    continue
                latin_hits.append((m.start(), tok))
            for m in _CJK_CAND_RE.finditer(clause):
                cjk_hits.append((m.start(), m.group(0)))
            # gene/protein symbols are the canonical endpoint names: when a clause has
            # any Latin token, prose-like CJK candidates must not win the endpoint slots
            hits = sorted(latin_hits if latin_hits else cjk_hits)
            tokens = []
            for pos, tok in hits:
                ent = by_label.get(ingest.normalise_text(tok))
                if ent and ent["id"] not in [t[0] for t in tokens]:
                    tokens.append((ent["id"], ent["label"], pos))
            if not cues:
                if tokens:
                    last_seen = tokens[-1][0]
                continue
            primary = next((c for c in ingest.CUE_CLASS_ORDER if c in cues), None)
            if primary is None:
                if tokens:
                    last_seen = tokens[-1][0]
                continue

            clause_last = tokens[-1][0] if tokens else last_seen
            prepended = False
            if len(tokens) == 1:
                # "进而激活 CAMK2" / "抑制 CASP3": the subject is in the earlier clause
                if last_seen and last_seen != tokens[0][0]:
                    tokens = [(last_seen, "", -1)] + tokens
                    prepended = True
                else:
                    last_seen = clause_last
                    continue
            if len(tokens) < 2:
                last_seen = clause_last
                continue

            positions = []
            for cue in cues[primary]:
                pos = clause.find(cue)
                if pos >= 0:
                    positions.append(pos)
            positions = sorted(set(positions))
            cue_pos = positions[0] if positions else 0
            if not prepended and positions:
                # prefer the verb that actually sits between two distinct entities,
                # e.g. "活化的 CREB 促进 BCL2 转录" -> 促进, not the adjective 活化
                chosen = None
                for p in positions:
                    b = [t for t in tokens if t[2] < p]
                    a = [t for t in tokens if t[2] >= p]
                    if b and a and b[-1][0] != a[0][0]:
                        chosen = p
                        if primary != "containment":
                            break
                cue_pos = chosen if chosen is not None else (
                    positions[-1] if primary == "containment" else positions[0])

            if primary == "containment":
                label = re.split(r"[，,、：:；;]", clause[:cue_pos])[-1].strip()
                label = re.sub(r"^(上述|这些|其中|所有|均|都|也|该|此)+", "", label).strip()
                label = re.sub(r"(归入|分为|属于|构成|组成|包括|包含|的|为|是|两个|三个|若干)$",
                               "", label).strip()
                members = [t[0] for t in tokens]
                if len(members) >= 1 and len(label) >= 2:
                    key = ingest.normalise_text(label)
                    if key not in seen_con:
                        seen_con.add(key)
                        cid = _slug_id("c", label, used_con_ids)
                        containers.append({
                            "id": cid, "label": label, "members": members,
                            "source": {"path": path, "locator": locator, "kind": "explicit",
                                       "quote": clause}})
                        uncertainties.append({
                            "where": "containers.%s" % cid,
                            "issue": "container label %r and member list were split from one "
                                     "sentence by a rule, not read as a declared grouping"
                                     % label,
                            "action": "confirm the grouping boundary and membership"})
                last_seen = clause_last
                continue

            if prepended:
                frm, to = tokens[0][0], tokens[1][0]
            else:
                before = [t for t in tokens if t[2] < cue_pos]
                after = [t for t in tokens if t[2] >= cue_pos]
                frm = (before[-1] if before else tokens[0])[0]
                to = (after[0] if after else tokens[-1])[0]
            if frm == to:
                last_seen = clause_last
                continue

            key = (frm, to, primary)
            last_seen = clause_last
            if key in seen_rel:
                continue
            seen_rel.add(key)
            rid = _slug_id("r", "%s_%s_%s" % (frm, to, primary), used_rel_ids)
            direction = "bidirectional" if "bidirectional" in cues else "forward"
            quote = clause
            if not index.find_quote(path, locator, quote):
                quote = clause
            relations.append({
                "id": rid, "from": frm, "to": to, "type": primary, "direction": direction,
                "label": cues[primary][0],
                "style": {"stroke": "solid",
                          "arrow": "tee" if primary == "inhibition" else "normal",
                          "color": arrow_color.get(primary, "#333333")},
                "source": {"path": path, "locator": locator, "kind": "explicit",
                           "quote": quote}})
            uncertainties.append({
                "where": "relations.%s" % rid,
                "issue": "direction extracted by verb rule from %r; the entity pair was chosen "
                         "by nearest-token heuristics" % _clip(clause, 60),
                "action": "confirm from/to and type/direction against the material"})

    # drop CJK candidates that are only container names and carry no relation
    con_labels = {ingest.normalise_text(c["label"]) for c in containers}
    referenced = set()
    for rel in relations:
        referenced.add(rel["from"])
        referenced.add(rel["to"])
    entities = [e for e in entities
                if not ((ingest.normalise_text(str(e.get("label") or "")) in con_labels
                         or e["id"] in cjk_ids)
                        and e["id"] not in referenced)]
    surviving = {e["id"] for e in entities}
    containers = [dict(c, members=[m for m in c["members"] if m in surviving])
                  for c in containers]
    containers = [c for c in containers if c["members"]]
    used_ids = {e["id"] for e in entities}

    # line-style legend items for the relation families actually present
    present = {}
    for rel in relations:
        present.setdefault(rel["type"], rel)
    used_lg = {lg["id"] for lg in legend}
    for rtype in ("activation", "inhibition"):
        rel = present.get(rtype)
        if not rel:
            continue
        cue = rel.get("label") or rtype
        legend.append({
            "id": _slug_id("lg", rtype, used_lg),
            "label": "%s（%s）" % (cue, "实线箭头" if rtype == "activation" else "平头线"),
            "kind": "line_style", "value": rtype, "color": rel["style"]["color"],
            "marker": "arrow:%s" % rel["style"]["arrow"],
            "source": deepcopy(rel["source"])})

    # ---- title ----------------------------------------------------------
    title_text = ""
    title_source = None
    task_text = str(case_manifest.get("task") or case_manifest.get("task_text") or "")
    task_path = str(case_manifest.get("task_path") or "")
    if task_text.strip():
        first = _CLAUSE_SPLIT_RE.split(task_text.strip())[0]
        title_text = _clip(first, 60)
        quote = task_text.strip()[:120]          # verbatim slice: no ellipsis marker
        if task_path and index.has_path(task_path) and index.find_quote(task_path, "L1", quote):
            title_source = {"path": task_path, "locator": "L1", "kind": "derived",
                            "quote": quote,
                            "derived_from": sorted({u.get("locator") for u in units_sorted
                                                    if u.get("path") == task_path})[:6]}
        else:
            title_source = {"path": task_path or "", "locator": "", "kind": "unsupported",
                            "quote": ""}
        uncertainties.append({
            "where": "figure.title",
            "issue": "title is a clipped restatement of the task text, not a material sentence",
            "action": "rewrite the title from the materials and bind an explicit quote, or keep "
                      "it marked derived"})
    else:
        title_text = "%s 来源关系示意" % fig_id
        title_source = {"path": "", "locator": "", "kind": "unsupported", "quote": ""}
        uncertainties.append({
            "where": "figure.title",
            "issue": "no task text and no material-derived title available",
            "action": "write a title bound to a verbatim material quote"})

    sources = []
    for entry in case_manifest.get("files") or []:
        if isinstance(entry, dict) and entry.get("role") == "material":
            sources.append({"path": entry.get("rel"), "sha256": entry.get("sha256")})

    model = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_manifest.get("case_id", "unknown-case"),
        "figure": {
            "id": fig_id,
            "kind": fig_kind,
            "title": {"text": title_text, "source": title_source},
            "canvas": {"width_mm": width, "height_mm": height, "background": "#FFFFFF"},
            "style": {
                "font_stack": ["DejaVu Sans", "Liberation Sans", "Arial",
                               "Noto Sans CJK SC", "sans-serif"],
                "color_space": "RGB",
                "font_sizes_pt": {"panel": 9, "label": 7, "title": 9, "legend": 7},
                "line_widths_pt": {"edge": 0.8, "node": 0.6, "axis": 0.6},
                "palette": palette,
            },
        },
        "entities": entities,
        "relations": relations,
        "containers": containers,
        "legend": legend,
        "data": data_obj,
        "panels": [{"id": "A"}],
        "uncertainty": uncertainties,
        "provenance": {
            "generated_by": "%s/draft" % common.SKILL_NAME,
            "created_utc": common.now_utc(),
            "model_version": SCHEMA_VERSION,
            "source_files": sources,
            "extractor": {"name": "ingest.draft_model", "version": "1.0",
                          "strategy": "latin-token + biological verb lexicon + delimited tables"},
        },
    }
    return model


# --------------------------------------------------------------------------
# auto_fix()
# --------------------------------------------------------------------------
def _fix_actions(model, actions):
    unc = model.get("uncertainty")
    if not isinstance(unc, list):
        unc = []
        model["uncertainty"] = unc
    for act in actions:
        unc.append(act)
        common.log(str(act.get("issue")))


def auto_fix(model, issues):
    """Conservative repair only.

    * fill missing ids (deterministic, derived from the label);
    * de-duplicate ids and rewrite every reference to the renamed element;
    * resolve dangling references by *dropping* the offending relation / member
      (never by inventing a target);
    * demote source-less elements to ``kind="unsupported"`` so the gate reports them
      as warnings instead of pretending they are evidenced.

    It never invents a source and never changes a relation's type or direction.
    """
    m = deepcopy(model) if isinstance(model, dict) else {}
    actions = []
    if not isinstance(m, dict):
        return {}

    for key in ("entities", "relations", "containers", "legend"):
        if not isinstance(m.get(key), list):
            m[key] = []
    for key in REQUIRED_TOP_KEYS:
        if key not in m:
            if key == "figure":
                m[key] = {"id": "figure", "kind": "relationship_schematic",
                          "canvas": {"width_mm": 180, "height_mm": 120}}
            elif key in ("entities", "relations", "containers", "legend"):
                m[key] = []
            elif key == "schema_version":
                m[key] = SCHEMA_VERSION
            elif key == "case_id":
                m[key] = "unknown-case"
            elif key == "provenance":
                m[key] = {"generated_by": "%s/auto_fix" % common.SKILL_NAME,
                          "source_files": []}
            actions.append({"where": key, "issue": "auto_fix: filled missing top-level key %r"
                                                   % key, "action": "default value added"})

    def _fill_and_dedupe(items, prefix):
        rename = {}
        used = set()
        for i, obj in enumerate(items):
            if not isinstance(obj, dict):
                continue
            oid = obj.get("id")
            if not isinstance(oid, str) or not oid.strip():
                label = obj.get("label") or obj.get("name") or "%s%d" % (prefix, i + 1)
                oid = common.slug("%s-%s" % (prefix, label), fallback="%s%d" % (prefix, i + 1))
                actions.append({"where": "%s[%d]" % (prefix, i),
                                "issue": "auto_fix: filled missing id with %r" % oid,
                                "action": "id generated from label"})
            while oid in used:
                new = "%s_%d" % (oid, len(used) + 1)
                actions.append({"where": "%s.%s" % (prefix, oid),
                                "issue": "auto_fix: duplicate id %r renamed to %r" % (oid, new),
                                "action": "duplicate id disambiguated"})
                rename[oid] = new
                oid = new
            used.add(oid)
            obj["id"] = oid
        return rename, used

    ent_rename, ent_ids = _fill_and_dedupe(m["entities"], "e")
    con_rename, con_ids = _fill_and_dedupe(m["containers"], "c")
    _fill_and_dedupe(m["relations"], "r")
    _fill_and_dedupe(m["legend"], "lg")
    if isinstance(m.get("panels"), list):
        _fill_and_dedupe(m["panels"], "A")

    def _map(value, rename, kept):
        """Rewrite a reference only when it no longer resolves to a kept element.

        A duplicate id is renamed on the *later* occurrence, so existing references
        keep pointing at the id that already resolved (never silently re-targeted).
        """
        if value in kept:
            return value
        return rename.get(value, value)

    if ent_rename:
        for rel in m["relations"]:
            if isinstance(rel, dict):
                rel["from"] = _map(rel.get("from"), ent_rename, ent_ids)
                rel["to"] = _map(rel.get("to"), ent_rename, ent_ids)
        for con in m["containers"]:
            if isinstance(con, dict) and isinstance(con.get("members"), list):
                con["members"] = [_map(x, ent_rename, ent_ids | con_ids)
                                  for x in con["members"]]
    if con_rename:
        for ent in m["entities"]:
            if isinstance(ent, dict) and ent.get("container"):
                ent["container"] = _map(ent["container"], con_rename, con_ids)

    # dangling references -> drop, never invent
    known_ent = set(ent_ids)
    kept_relations = []
    for rel in m["relations"]:
        if not isinstance(rel, dict):
            continue
        frm, to = rel.get("from"), rel.get("to")
        if frm not in known_ent or to not in known_ent:
            actions.append({"where": "relations.%s" % rel.get("id"),
                            "issue": "auto_fix: dropped relation %s(%s -> %s): endpoint(s) %s "
                                     "are not defined entities"
                                     % (rel.get("id"), frm, to,
                                        [x for x in (frm, to) if x not in known_ent]),
                            "action": "relation dropped as dangling"})
            continue
        kept_relations.append(rel)
    m["relations"] = kept_relations

    for con in m["containers"]:
        if not isinstance(con, dict) or not isinstance(con.get("members"), list):
            continue
        kept = []
        for member in con["members"]:
            if member in known_ent or member in con_ids:
                kept.append(member)
            else:
                actions.append({"where": "containers.%s" % con.get("id"),
                                "issue": "auto_fix: removed container member %r from %r: not a "
                                         "defined entity" % (member, con.get("id")),
                                "action": "member removed as dangling"})
        con["members"] = kept
    for ent in m["entities"]:
        if isinstance(ent, dict) and ent.get("container") and ent["container"] not in con_ids:
            actions.append({"where": "entities.%s" % ent.get("id"),
                            "issue": "auto_fix: cleared entity.container %r: not a defined "
                                     "container" % ent["container"],
                            "action": "container reference cleared"})
            ent["container"] = None

    # provenance problems -> explicit "unsupported" (warning, not fake evidence)
    by_path = {}
    for kind in ("entities", "relations", "containers", "legend"):
        for obj in m[kind]:
            if isinstance(obj, dict) and obj.get("id"):
                by_path["%s.%s" % (kind, obj["id"])] = obj
    if isinstance(m.get("figure"), dict) and isinstance(m["figure"].get("title"), dict):
        by_path["figure.title"] = m["figure"]["title"]

    for issue in issues.get("errors") if isinstance(issues, dict) else (issues or []):
        if not isinstance(issue, dict) or issue.get("code") not in PROVENANCE_CODES:
            continue
        target = by_path.get(str(issue.get("where") or ""))
        if target is None:
            continue
        src = target.get("source") if isinstance(target.get("source"), dict) else {}
        if src.get("kind") == "unsupported":
            continue
        src = dict(src)
        src["kind"] = "unsupported"
        src.pop("quote", None)
        src.pop("derived_from", None)
        target["source"] = src
        actions.append({"where": issue.get("where"),
                        "issue": "auto_fix: %s -> provenance demoted to 'unsupported' (no "
                                 "source was invented)" % issue.get("code"),
                        "action": "element kept but no longer claimed as evidenced"})

    m["provenance"] = m.get("provenance") if isinstance(m.get("provenance"), dict) else {}
    m["provenance"].setdefault("generated_by", "%s/auto_fix" % common.SKILL_NAME)
    m["provenance"].setdefault("source_files", [])
    m["provenance"]["auto_fixed_utc"] = common.now_utc()
    m["provenance"]["autofix_actions"] = len(actions)
    _fix_actions(m, actions)
    return m


__all__ = [
    "draft_model", "validate_model", "auto_fix",
    "REQUIRED_TOP_KEYS", "FIGURE_KINDS", "ENTITY_KINDS", "RELATION_TYPES",
    "DIRECTIONS", "LEGEND_KINDS", "DEFAULT_PALETTE", "SOFT_CODES",
]
