# -*- coding: utf-8 -*-
"""Deterministic, editable, layered SVG renderer.

Design rules (frozen contract, see ``references/layout_and_svg.md``)
-------------------------------------------------------------------
* **Exactly seven top-level layer groups**, in this z-order:
  ``layer:background, layer:containers, layer:edges, layer:nodes, layer:labels,
  layer:legend, layer:annotations``.  Every group has a ``<title>``.
* **Chart chrome lives inside those layers**: the axes group
  (``<g id="axes:<figure>"``) is nested in ``layer:background`` and the data
  marks (``<g id="series:N">``) in ``layer:nodes``, so the frozen seven-group
  structure and its z-order stay exactly as specified while axes, ticks, axis
  labels and series marks keep their own provenance attributes.
* **Text stays text**: every label/title/legend entry is a real ``<text>``
  element with ``font-family`` taken from ``figure.style.font_stack``, a
  ``font-size`` converted from points to user units (``pt * 96 / 72``) and an
  explicit ``text-anchor``.  No ``<image>``, never text-as-path.
* **Provenance**: nodes ``id="ent:<id>"``, relations ``id="rel:<id>"``, legend
  items ``id="lg:<id>"``, each with ``data-prov="<path>#<locator>"`` and
  ``data-src-kind="explicit|derived|unsupported"``; edges additionally carry
  ``data-rel-type`` and ``data-direction`` so a reviewer can machine-check that
  inhibition is drawn as a tee and activation as an arrow.
* **Determinism**: identical model + layout -> byte-identical SVG.  Set-like
  collections are iterated in sorted order, ties break on id and no timestamp or
  random value is ever embedded (the model hash is used instead).
* Unit scale: 1 user unit = 1 px @ 96 dpi, ``uu = mm * 96 / 25.4``.  The root
  element carries physical ``width``/``height`` in mm.
"""

from __future__ import annotations

import json
import re

try:                                        # package-style import
    from .common import xml_escape as _esc
except Exception:                           # pragma: no cover - script-style import
    try:
        from common import xml_escape as _esc
    except Exception:
        def _esc(text):
            s = "" if text is None else str(text)
            return (s.replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;").replace('"', "&quot;"))

MM_TO_UU = 96.0 / 25.4
PT_TO_UU = 96.0 / 72.0
LAYER_IDS = ("background", "containers", "edges", "nodes", "labels", "legend",
             "annotations")
LAYER_TITLES = {
    "background": "background: canvas fill and chart axes chrome",
    "containers": "containers: enclosure rectangles (containment)",
    "edges": "edges: relations with arrow / tee heads",
    "nodes": "nodes: entity boxes and labels (chart data marks)",
    "labels": "labels: figure title and panel letters",
    "legend": "legend: legend items derived from model and data series",
    "annotations": "annotations: panel captions",
}
DEFAULT_FONT_STACK = ["DejaVu Sans", "Liberation Sans", "Arial"]
DEFAULT_PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#56B4E9",
                   "#E69F00", "#F0E442", "#999999"]
HEAD_LEN_UU = 4.4
HEAD_HALF_UU = 2.1
TEE_HALF_UU = 4.2
AXIS_COLOR = "#333333"
GRID_COLOR = "#E4E4E4"
FRAME_COLOR = "#B9BFC6"
#: journal rule: never emit a stroked element thinner than this (pt).  The
#: export-compliance gate measures every stroked element, so decorative hairlines
#: are clamped up instead of being drawn below the printable minimum.  The extra
#: 0.02 pt keeps a margin over the gate even after rounding to 3 decimals.
MIN_STROKE_PT = 0.52


def _sw(width_pt):
    return max(MIN_STROKE_PT, _num(width_pt, MIN_STROKE_PT))


# --------------------------------------------------------------------------
# formatting helpers (deterministic, no locale, no exponent notation)
# --------------------------------------------------------------------------
def _fmt(value):
    try:
        x = round(float(value), 3)
    except (TypeError, ValueError):
        return "0"
    if x == 0:
        x = 0.0
    s = ("%.3f" % x).rstrip("0").rstrip(".")
    if s in ("", "-0"):
        return "0"
    return s


def _uu(mm):
    try:
        return float(mm) * MM_TO_UU
    except (TypeError, ValueError):
        return 0.0


def _num(value, default=0.0):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if f == f else default


def _attr(value):
    return _esc(value)


def _canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# style / model access
# --------------------------------------------------------------------------
def _style_of(model, layout):
    style = layout.get("style") if isinstance(layout.get("style"), dict) else {}
    fig = model.get("figure") if isinstance(model.get("figure"), dict) else {}
    fstyle = fig.get("style") if isinstance(fig.get("style"), dict) else {}
    stack = style.get("font_stack") or fstyle.get("font_stack")
    stack = [str(s).strip() for s in stack if str(s).strip()] if isinstance(stack, list) else []
    if not stack:
        stack = list(DEFAULT_FONT_STACK)
    sizes = style.get("font_sizes_pt") if isinstance(style.get("font_sizes_pt"), dict) else {}
    sizes = dict(sizes)
    if isinstance(fstyle.get("font_sizes_pt"), dict):
        for k in sorted(fstyle["font_sizes_pt"]):
            sizes.setdefault(k, fstyle["font_sizes_pt"][k])
    for k in ("panel", "label", "title", "legend"):
        v = _num(sizes.get(k), 0.0)
        sizes[k] = v if v > 0 else {"panel": 9.0, "label": 7.0, "title": 9.0,
                                    "legend": 7.0}[k]
    widths = style.get("line_widths_pt") if isinstance(style.get("line_widths_pt"), dict) else {}
    if isinstance(fstyle.get("line_widths_pt"), dict):
        widths = dict(fstyle["line_widths_pt"], **widths)
    for k in ("edge", "node", "axis"):
        v = _num(widths.get(k), 0.0)
        widths[k] = v if v > 0 else {"edge": 0.8, "node": 0.6, "axis": 0.6}[k]
    palette = style.get("palette") if isinstance(style.get("palette"), list) else None
    if not palette:
        palette = fstyle.get("palette") if isinstance(fstyle.get("palette"), list) else None
    palette = [str(c) for c in palette] if palette else list(DEFAULT_PALETTE)
    return {"font_stack": stack, "font_family": ", ".join(stack),
            "font_sizes_pt": sizes, "line_widths_pt": widths, "palette": palette}


def _src_of(obj):
    src = obj.get("source") if isinstance(obj, dict) else None
    if not isinstance(src, dict):
        return "(none)", "(none)", "unsupported"
    kind = str(src.get("kind") or "")
    if kind not in ("explicit", "derived", "unsupported"):
        kind = "unsupported"
    return (str(src.get("path") or "(none)"), str(src.get("locator") or "(none)"), kind)


#: CONTRACT 4.7 locator set: L12 | L12-L18 | p3 | table:col | fig:1.
#: Mirrors layout.LOCATOR_RE so the renderer can validate without importing layout.
_PROV_LOCATOR_RE = re.compile(r"^(L\d+(?:-L\d+)?|p\d+|table:[^\s#]+|fig:[\w.\-]+)$")


def _valid_locator(locator):
    return bool(_PROV_LOCATOR_RE.match(str(locator or "").strip()))


def _prov_attr(obj):
    """``(data-prov, data-src-kind)`` for one drawn element, in the frozen form.

    ``data-prov`` is ``<relative POSIX path>#<locator>`` with the locator drawn
    from the CONTRACT 4.7 set (``L12 | L12-L18 | p3 | table:col | fig:1``).  A
    source that names a file but no usable locator cannot be verified, so it is
    normalised to the accepted placeholder ``(none)#(none)`` with
    ``unsupported`` rather than shipped as a malformed claim.
    """
    path, locator, kind = _src_of(obj)
    if isinstance(obj, dict) and obj.get("prov"):
        prov = str(obj["prov"])
        p, _, loc = prov.partition("#")
        if prov == "(none)#(none)" or (p and p != "(none)" and _valid_locator(loc)):
            return prov, str(obj.get("src_kind") or kind)
        return "(none)#(none)", "unsupported"
    if not path or path == "(none)" or not _valid_locator(locator):
        return "(none)#(none)", "unsupported"
    return "%s#%s" % (path, locator), kind


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------
def _text(x_mm, y_mm, content, font_pt, font_family, anchor="start", extra=""):
    return ('<text x="%s" y="%s" font-family="%s" font-size="%s" text-anchor="%s"%s>%s</text>'
            % (_fmt(_uu(x_mm)), _fmt(_uu(y_mm)), _attr(font_family),
               _fmt(font_pt * PT_TO_UU), anchor, extra, _esc(content)))


def _rect(x, y, w, h, fill, stroke="none", width_pt=0.0, rx=0.0, extra=""):
    sw = 0.0 if str(stroke) == "none" else _sw(width_pt)
    return ('<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="%s" '
            'stroke="%s" stroke-width="%s"%s/>'
            % (_fmt(_uu(x)), _fmt(_uu(y)), _fmt(_uu(w)), _fmt(_uu(h)), _fmt(_uu(rx)),
               _attr(fill), _attr(stroke), _fmt(sw * PT_TO_UU), extra))


def _polyline(points_mm, stroke, width_pt, dash=False, extra=""):
    if len(points_mm) < 2:
        return ""
    d = "M %s" % " L ".join("%s %s" % (_fmt(_uu(x)), _fmt(_uu(y))) for x, y in points_mm)
    dash_attr = ' stroke-dasharray="%s %s"' % (_fmt(2.6), _fmt(1.8)) if dash else ""
    return ('<path d="%s" fill="none" stroke="%s" stroke-width="%s" '
            'stroke-linecap="round" stroke-linejoin="round"%s%s/>'
            % (d, _attr(stroke), _fmt(_sw(width_pt) * PT_TO_UU), dash_attr, extra))


def _head(points_mm, at_end, kind, color):
    """Explicit arrow head / tee bar geometry (no <marker>, converter-proof)."""
    if kind not in ("arrow", "tee") or len(points_mm) < 2:
        return ""
    if at_end:
        tip = points_mm[-1]
        ref = points_mm[-2]
    else:
        tip = points_mm[0]
        ref = points_mm[1]
    dx = float(tip[0]) - float(ref[0])
    dy = float(tip[1]) - float(ref[1])
    ln = (dx * dx + dy * dy) ** 0.5
    if ln <= 0:
        return ""
    ux, uy = dx / ln, dy / ln
    px, py = -uy, ux
    if kind == "tee":
        half = TEE_HALF_UU / MM_TO_UU
        p1 = (tip[0] - px * half, tip[1] - py * half)
        p2 = (tip[0] + px * half, tip[1] + py * half)
        return ('<path d="M %s %s L %s %s" fill="none" stroke="%s" stroke-width="%s"/>'
                % (_fmt(_uu(p1[0])), _fmt(_uu(p1[1])), _fmt(_uu(p2[0])), _fmt(_uu(p2[1])),
                   _attr(color), _fmt(_sw(2.0) * PT_TO_UU)))
    back = HEAD_LEN_UU / MM_TO_UU
    half = HEAD_HALF_UU / MM_TO_UU
    base = (tip[0] - ux * back, tip[1] - uy * back)
    a = (base[0] - px * half, base[1] - py * half)
    b = (base[0] + px * half, base[1] + py * half)
    return ('<path d="M %s %s L %s %s L %s %s Z" fill="%s" stroke="%s" '
            'stroke-width="%s"/>'
            % (_fmt(_uu(tip[0])), _fmt(_uu(tip[1])), _fmt(_uu(a[0])), _fmt(_uu(a[1])),
               _fmt(_uu(b[0])), _fmt(_uu(b[1])), _attr(color), _attr(color),
               _fmt(_sw(0.2) * PT_TO_UU)))


# --------------------------------------------------------------------------
# layers
# --------------------------------------------------------------------------
def _layer_open(layer_id):
    return ('<g id="layer:%s">' % layer_id,
            "<title>%s</title>" % _esc(LAYER_TITLES.get(layer_id, layer_id)))


def _background_layer(layout, style, chart):
    W = _num(layout.get("canvas", {}).get("width_mm"), 180.0)
    H = _num(layout.get("canvas", {}).get("height_mm"), 120.0)
    bg = layout.get("canvas", {}).get("background") or "#FFFFFF"
    out = list(_layer_open("background"))
    out.append(_rect(0.0, 0.0, W, H, bg))
    if chart:
        out.extend(_axes_group(chart, style, layout))
    out.append("</g>")
    return out


def _axes_group(chart, style, layout):
    fig_id = "chart"
    fig = (layout.get("figure_id") or "")
    if fig:
        fig_id = str(fig)
    prov = chart.get("prov") or "(none)"
    kind = chart.get("src_kind") or "derived"
    ff = style["font_family"]
    plot = chart.get("plot") or {}
    x0 = _num(plot.get("x"))
    y0 = _num(plot.get("y"))
    w = _num(plot.get("w"))
    h = _num(plot.get("h"))
    x2, y2 = x0 + w, y0 + h
    out = ['<g id="axes:%s" data-prov="%s" data-src-kind="%s" data-chart="axes">'
           % (_attr(fig_id), _attr(prov), _attr(kind))]
    out.append("<title>%s</title>" % _esc("axes: %s / %s"
                                          % ((chart.get("x") or {}).get("title", "x"),
                                             (chart.get("y") or {}).get("title", "y"))))
    out.append(_rect(x0, y0, w, h, "#FFFFFF", FRAME_COLOR, _num(style["line_widths_pt"]["axis"]) * 0.8))
    yspec = chart.get("y") or {}
    xspec = chart.get("x") or {}
    for tick in yspec.get("ticks") or []:
        ty = _num(tick.get("pos_mm"))
        out.append(_polyline([(x0, ty), (x2, ty)], GRID_COLOR,
                             _num(style["line_widths_pt"]["axis"]) * 0.7,
                             dash=True, extra=' data-prov="%s" data-src-kind="%s"'
                             % (_attr(yspec.get("prov", prov)), _attr(yspec.get("src_kind", kind)))))
        out.append(_polyline([(x0 - 1.3, ty), (x0, ty)], AXIS_COLOR,
                             _num(style["line_widths_pt"]["axis"])))
        tick_pt = _num(yspec.get("tick_font_pt"), 7.0)
        out.append(_text(x0 - 2.0, ty + tick_pt * 0.3528 * 0.36,
                         tick.get("label", ""), tick_pt, ff,
                         "end", ' data-prov="%s" data-src-kind="%s"'
                         % (_attr(yspec.get("prov", prov)), _attr(yspec.get("src_kind", kind)))))
    xlabels = xspec.get("ticks") or []
    spacing = 0.0
    if len(xlabels) >= 2:
        positions = sorted(_num(t.get("pos_mm")) for t in xlabels)
        spacing = min(positions[i + 1] - positions[i] for i in range(len(positions) - 1))
    longest = max([len(str(t.get("label", ""))) for t in xlabels] or [0])
    label_pt = _num(xspec.get("tick_font_pt"), 7.0)
    rotate = bool(xlabels) and (longest * label_pt * 0.58 * 0.3528 > max(4.0, spacing * 0.85))
    for tick in xlabels:
        tx = _num(tick.get("pos_mm"))
        out.append(_polyline([(tx, y2), (tx, y2 + 1.3)], AXIS_COLOR,
                             _num(style["line_widths_pt"]["axis"])))
        extra = ' data-prov="%s" data-src-kind="%s"' % (
            _attr(xspec.get("prov", prov)), _attr(xspec.get("src_kind", kind)))
        if rotate:
            extra += ' transform="rotate(-35 %s %s)"' % (_fmt(_uu(tx)), _fmt(_uu(y2 + 3.6)))
            out.append(_text(tx, y2 + 3.6, tick.get("label", ""), label_pt, ff, "end", extra))
        else:
            out.append(_text(tx, y2 + 1.3 + label_pt * 0.3528 * 0.9, tick.get("label", ""),
                             label_pt, ff, "middle", extra))
    if xspec.get("title"):
        out.append(_text(x0 + w / 2.0, y2 + 3.0 + label_pt * 0.3528 * (2.4 if rotate else 1.6),
                         xspec["title"], _num(xspec.get("font_pt"), 7.0), ff, "middle",
                         ' data-prov="%s" data-src-kind="%s"'
                         % (_attr(xspec.get("prov", prov)), _attr(xspec.get("src_kind", kind)))))
    if yspec.get("title"):
        out.append(_text(x0 - 11.0, y0 + h / 2.0, yspec["title"],
                         _num(yspec.get("font_pt"), 7.0), ff, "middle",
                         ' transform="rotate(-90 %s %s)" data-prov="%s" data-src-kind="%s"'
                         % (_fmt(_uu(x0 - 11.0)), _fmt(_uu(y0 + h / 2.0)),
                            _attr(yspec.get("prov", prov)), _attr(yspec.get("src_kind", kind)))))
    out.append("</g>")
    return out


def _series_marks(chart, style):
    """Chart data marks; live in layer:nodes (above the axes chrome)."""
    out = []
    bar = chart.get("bar") or {}
    nser = max(1, int(_num(bar.get("n_series"), 1)))
    bar_w = _num(bar.get("bar_w_mm"))
    yspec = chart.get("y") or {}
    plot = chart.get("plot") or {}
    y_lo = _num(yspec.get("min"))
    y_hi = _num(yspec.get("max"))
    span = y_hi - y_lo

    def y_of(value):
        if span <= 0:
            return _num(plot.get("y")) + _num(plot.get("h")) / 2.0
        return _num(plot.get("y")) + _num(plot.get("h")) - (value - y_lo) / span * _num(plot.get("h"))

    for s in chart.get("series") or []:
        prov = s.get("prov") or "(none)#(none)"
        kind = s.get("src_kind") or ("derived" if chart.get("src_kind") == "derived"
                                     else "unsupported")
        color = s.get("color") or style["palette"][int(_num(s.get("index"), 0)) % len(style["palette"])]
        idx = int(_num(s.get("index"), 0))
        out.append('<g id="series:%d" data-prov="%s" data-src-kind="%s" data-name="%s" '
                   'data-unit="%s" data-color="%s"%s%s>'
                   % (idx, _attr(prov), _attr(kind),
                      _attr(s.get("name", "")), _attr(s.get("unit", "")),
                      _attr(color),
                      ' data-legend="%s"' % _attr(s.get("legend_id")) if s.get("legend_id") else "",
                      ' data-entity="%s"' % _attr(s.get("entity_id")) if s.get("entity_id") else ""))
        out.append("<title>%s</title>" % _esc(s.get("name", "")))
        shape = s.get("shape") or "line"
        if shape == "bar" and bar_w > 0:
            group_w = _num(bar.get("group_w_mm"))
            offset = -group_w / 2.0 + idx * bar_w
            zero_pt = _num(bar.get("baseline"), 0.0)
            y_zero = y_of(zero_pt)          # the baseline bar lengths are measured from
            for pt in s.get("points") or []:
                py = _num(pt.get("y_mm"))
                x = _num(pt.get("x_mm")) + offset
                top = min(py, y_zero)
                height = max(0.2, abs(y_zero - py))
                out.append(_rect(x, top, bar_w * 0.86, height, color,
                                 "none", 0.0, 0.0,
                                 ' data-prov="%s" data-src-kind="%s" data-value="%s" '
                                 'data-baseline="%s"'
                                 % (_attr(prov), _attr(kind), _attr(pt.get("y")),
                                    _fmt(zero_pt))))
        else:
            pts = [(pt.get("x_mm"), pt.get("y_mm")) for pt in (s.get("points") or [])]
            if len(pts) >= 2:
                out.append(_polyline(pts, color, _num(style["line_widths_pt"]["edge"]),
                                     extra=' data-prov="%s" data-src-kind="%s"'
                                     % (_attr(prov), _attr(kind))))
            for pt in s.get("points") or []:
                out.append('<circle cx="%s" cy="%s" r="%s" fill="%s" stroke="#FFFFFF" '
                           'stroke-width="%s" data-prov="%s" data-src-kind="%s" data-value="%s"/>'
                           % (_fmt(_uu(_num(pt.get("x_mm")))), _fmt(_uu(_num(pt.get("y_mm")))),
                              _fmt(1.5), _attr(color), _fmt(_sw(0.5) * PT_TO_UU), _attr(prov),
                              _attr(kind), _attr(pt.get("y"))))
        out.append("</g>")
    return out


def _containers_layer(layout, style):
    out = list(_layer_open("containers"))
    containers = layout.get("containers") if isinstance(layout.get("containers"), dict) else {}
    ordered = sorted(containers, key=lambda c: (_num(containers[c].get("depth")),
                                                _num(containers[c].get("y_mm")),
                                                _num(containers[c].get("x_mm")), str(c)))
    line_w = _num(style["line_widths_pt"]["node"])
    for cid in ordered:
        c = containers[cid]
        if not isinstance(c, dict):
            continue
        eid = str(c.get("element_id") or ("cnt:%s" % cid))
        prov, skind = _prov_attr(c)
        dash = ' stroke-dasharray="%s %s"' % (_fmt(2.4), _fmt(1.6)) if c.get("role") == "entity" else ""
        out.append('<g id="%s" data-prov="%s" data-src-kind="%s" data-role="%s" '
                   'data-level-span="%s" class="container">'
                   % (_attr(eid), _attr(prov), _attr(skind), _attr(c.get("role", "explicit")),
                      _attr("%s-%s" % ((c.get("level_span") or [0, 0])[0],
                                       (c.get("level_span") or [0, 0])[1]))))
        out.append("<title>%s</title>" % _esc(c.get("label", cid)))
        out.append(_rect(_num(c.get("x_mm")), _num(c.get("y_mm")), _num(c.get("w_mm")),
                         _num(c.get("h_mm")), "#F5F8FB", "#8C97A3", line_w, 2.2, dash))
        lines = c.get("lines") or ([c.get("label")] if c.get("label") else [])
        anchor = c.get("label_anchor") or {}
        ax = _num(anchor.get("x_mm"), _num(c.get("x_mm")))
        ay = _num(anchor.get("y_mm"), _num(c.get("y_mm")) + 3.5)
        pt = _num(c.get("font_pt"), style["font_sizes_pt"]["legend"])
        for i, line in enumerate(lines):
            out.append(_text(ax, ay + i * pt * 0.3528 * 1.35, line, pt,
                             style["font_family"], "start"))
        out.append("</g>")
    out.append("</g>")
    return out


def _edges_layer(layout, style):
    out = list(_layer_open("edges"))
    edges = layout.get("edges") if isinstance(layout.get("edges"), list) else []
    for e in sorted([x for x in edges if isinstance(x, dict)], key=lambda x: str(x.get("id"))):
        prov, skind = _prov_attr(e)
        color = e.get("color") or style["palette"][0]
        width_pt = _num(e.get("width_pt"), 0.8)
        points = [(p[0], p[1]) for p in (e.get("points_mm") or [])
                  if isinstance(p, (list, tuple)) and len(p) >= 2]
        out.append('<g id="rel:%s" data-prov="%s" data-src-kind="%s" data-rel-type="%s" '
                   'data-direction="%s" data-head-start="%s" data-head-end="%s" '
                   'data-feedback="%s" class="relation">'
                   % (_attr(e.get("id")), _attr(prov), _attr(skind),
                      _attr(e.get("type", "association")), _attr(e.get("direction", "forward")),
                      _attr(e.get("head_start", "none")), _attr(e.get("head_end", "none")),
                      "true" if e.get("feedback") else "false"))
        out.append("<title>%s</title>" % _esc(e.get("label") or "%s %s" % (e.get("type", ""), e.get("id", ""))))
        if len(points) >= 2:
            out.append(_polyline(points, color, width_pt, dash=(e.get("stroke") == "dashed")))
            out.append(_head(points, False, str(e.get("head_start") or "none"), color))
            out.append(_head(points, True, str(e.get("head_end") or "none"), color))
        lines = e.get("label_lines") or []
        pos = e.get("label_pos_mm")
        if lines and pos:
            pt = _num(e.get("font_pt"), style["font_sizes_pt"]["label"])
            anchor = str(e.get("label_anchor") or "middle")
            lw = _num(e.get("label_w_mm"), 0.0)
            lh = _num(e.get("label_h_mm"), len(lines) * pt * 0.3528 * 1.3)
            # white plate behind the label so the line never strikes through the text
            plate_h = lh + 0.8
            plate_w = lw + 1.6
            plate_x = _num(pos[0]) - (plate_w / 2.0 if anchor == "middle" else 0.8)
            plate_y = _num(pos[1]) - pt * 0.3528 * 0.95 - 0.4
            out.append('<rect class="edge-label-plate" x="%s" y="%s" width="%s" '
                       'height="%s" fill="#FFFFFF" stroke="none" data-prov="%s" '
                       'data-src-kind="%s"/>'
                       % (_fmt(_uu(plate_x)), _fmt(_uu(plate_y)), _fmt(_uu(plate_w)),
                          _fmt(_uu(plate_h)), _attr(prov), _attr(skind)))
            for i, line in enumerate(lines):
                out.append(_text(_num(pos[0]), _num(pos[1]) + i * pt * 0.3528 * 1.3, line, pt,
                                 style["font_family"], anchor))
        out.append("</g>")
    out.append("</g>")
    return out


def _nodes_layer(layout, style, chart):
    out = list(_layer_open("nodes"))
    nodes = layout.get("nodes") if isinstance(layout.get("nodes"), dict) else {}
    line_w = _num(style["line_widths_pt"]["node"])
    ordered = sorted(nodes, key=lambda n: (_num(nodes[n].get("y_mm")),
                                           _num(nodes[n].get("x_mm")), str(n)))
    for nid in ordered:
        n = nodes[nid]
        if not isinstance(n, dict):
            continue
        prov, skind = _prov_attr(n)
        x = _num(n.get("x_mm"))
        y = _num(n.get("y_mm"))
        w = _num(n.get("w_mm"))
        h = _num(n.get("h_mm"))
        font_pt = _num(n.get("font_pt"), style["font_sizes_pt"]["label"])
        line_h = _num(n.get("line_h_mm"), font_pt * 0.3528 * 1.35)
        lines = n.get("lines") or ([n.get("label")] if n.get("label") else [])
        out.append('<g id="ent:%s" data-prov="%s" data-src-kind="%s" data-node-kind="%s" '
                   'data-level="%s" data-container="%s" class="entity">'
                   % (_attr(nid), _attr(prov), _attr(skind), _attr(n.get("kind", "concept")),
                      _attr(n.get("level", 0)), _attr(n.get("container") or "")))
        out.append("<title>%s</title>" % _esc(n.get("label", nid)))
        out.append(_rect(x, y, w, h, n.get("fill") or "#FFFFFF", n.get("stroke") or "#333333",
                         line_w, 1.6))
        total = len(lines) * line_h
        first = y + h / 2.0 - total / 2.0 + line_h * 0.5 + font_pt * 0.3528 * 0.36
        for i, line in enumerate(lines):
            out.append(_text(x + w / 2.0, first + i * line_h, line, font_pt,
                             style["font_family"], "middle"))
        out.append("</g>")
    if chart:
        out.extend(_series_marks(chart, style))
    out.append("</g>")
    return out


def _labels_layer(layout, style):
    out = list(_layer_open("labels"))
    title = layout.get("title")
    if isinstance(title, dict) and title.get("lines"):
        prov, skind = _prov_attr(title)
        pt = _num(title.get("font_pt"), style["font_sizes_pt"]["title"])
        line_h = pt * 0.3528 * 1.35
        lines = title["lines"]
        y0 = _num(title.get("y_mm"))
        out.append('<g id="fig:title" data-prov="%s" data-src-kind="%s" class="title">'
                   % (_attr(prov), _attr(skind)))
        out.append("<title>%s</title>" % _esc(title.get("text", "")))
        for i, line in enumerate(lines):
            out.append(_text(_num(title.get("x_mm")), y0 + i * line_h, line, pt,
                             style["font_family"], "middle",
                             ' font-weight="bold"'))
        out.append("</g>")
    panels = layout.get("panels") if isinstance(layout.get("panels"), dict) else {}
    for pid in sorted(panels, key=lambda p: _num(panels[p].get("x_mm"))):
        p = panels[pid]
        if not isinstance(p, dict):
            continue
        prov, skind = _prov_attr(p)
        out.append('<g id="pnl:%s" data-prov="%s" data-src-kind="%s" class="panel">'
                   % (_attr(pid), _attr(prov), _attr(skind)))
        out.append("<title>%s</title>" % _esc("panel %s" % pid))
        out.append(_text(_num(p.get("x_mm")), _num(p.get("y_mm")), p.get("letter", pid),
                         _num(p.get("font_pt"), style["font_sizes_pt"]["panel"]),
                         style["font_family"], "start", ' font-weight="bold"'))
        out.append("</g>")
    out.append("</g>")
    return out


def _legend_layer(layout, style):
    out = list(_layer_open("legend"))
    legend = layout.get("legend") if isinstance(layout.get("legend"), dict) else None
    if not legend:
        out.append("</g>")
        return out
    line_w = _num(style["line_widths_pt"]["node"])
    # decorative chrome: no provenance attributes at all.  A provenance claim must
    # be verifiable, and CONTRACT 4.7 lists only explicit/derived/unsupported as
    # src-kinds - the frame is none of them; the legend ITEMS below are the bound ones.
    out.append('<g id="legend:frame" data-role="legend-frame">'
               "<title>%s</title>" % _esc("legend frame"))
    out.append(_rect(_num(legend.get("x_mm")), _num(legend.get("y_mm")),
                     _num(legend.get("w_mm")), _num(legend.get("h_mm")),
                     "#FFFFFF", FRAME_COLOR, line_w * 0.8, 1.6))
    out.append("</g>")
    for it in legend.get("items") or []:
        if not isinstance(it, dict):
            continue
        prov, skind = _prov_attr(it)
        color = it.get("color") or style["palette"][0]
        gx = _num(it.get("x_mm"))
        cy = _num(it.get("glyph_cy_mm"))
        gw = _num(it.get("glyph_w_mm"), 6.0)
        kind = str(it.get("kind") or "category")
        marker = str(it.get("marker") or "")
        out.append('<g id="lg:%s" data-prov="%s" data-src-kind="%s" data-legend-kind="%s" '
                   'data-marker="%s" data-origin="%s" class="legend-item">'
                   % (_attr(it.get("id")), _attr(prov), _attr(skind), _attr(kind),
                      _attr(marker), _attr(it.get("origin", "legend"))))
        out.append("<title>%s</title>" % _esc(it.get("label", "")))
        if kind == "line_style":
            half = gw / 2.0
            pts = [(gx, cy), (gx + gw, cy)]
            out.append(_polyline(pts, color, _num(style["line_widths_pt"]["edge"]),
                                 dash=("dashed" in marker or "dashed" in str(it.get("value") or ""))))
            head = "none"
            if marker.endswith("normal"):
                head = "arrow"
            elif marker.endswith("tee"):
                head = "tee"
            out.append(_head(pts, True, head, color))
        elif marker == "line":
            pts = [(gx, cy), (gx + gw, cy)]
            out.append(_polyline(pts, color, _num(style["line_widths_pt"]["edge"])))
            out.append('<circle cx="%s" cy="%s" r="%s" fill="%s" stroke="#FFFFFF" '
                       'stroke-width="%s"/>' % (_fmt(_uu(gx + gw * 0.5)), _fmt(_uu(cy)),
                                                _fmt(1.4), _attr(color),
                                                _fmt(_sw(0.5) * PT_TO_UU)))
        elif marker == "circle":
            out.append('<circle cx="%s" cy="%s" r="%s" fill="%s" stroke="#FFFFFF" '
                       'stroke-width="%s"/>' % (_fmt(_uu(gx + gw / 2.0)), _fmt(_uu(cy)),
                                                _fmt(1.9), _attr(color),
                                                _fmt(_sw(0.5) * PT_TO_UU)))
        elif marker == "triangle":
            out.append(_triangle(gx + gw / 2.0, cy, 2.2, color))
        elif marker == "diamond":
            out.append(_diamond(gx + gw / 2.0, cy, 2.2, color))
        elif kind == "value_scale":
            out.append(_rect(gx, cy - 1.6, gw, 3.2, color, "#666666", line_w * 0.6))
        else:
            size = 6.4
            out.append(_rect(gx + (gw - size) / 2.0, cy - size / 2.0, size, size, color,
                             "#FFFFFF", _sw(0.4)))
        pt = _num(it.get("font_pt"), style["font_sizes_pt"]["legend"])
        line_h = pt * 0.3528 * 1.3
        for i, line in enumerate(it.get("lines") or [it.get("label", "")]):
            out.append(_text(_num(it.get("text_x_mm")), _num(it.get("y_mm")) + line_h * 0.8 + i * line_h,
                             line, pt, style["font_family"], "start"))
        out.append("</g>")
    out.append("</g>")
    return out


def _triangle(cx, cy, half, color):
    pts = [(cx, cy - half), (cx + half, cy + half * 0.8), (cx - half, cy + half * 0.8)]
    d = "M %s %s L %s %s L %s %s Z" % tuple(
        v for p in pts for v in (_fmt(_uu(p[0])), _fmt(_uu(p[1]))))
    return '<path d="%s" fill="%s" stroke="#FFFFFF" stroke-width="%s"/>' % (
        d, _attr(color), _fmt(0.4))


def _diamond(cx, cy, half, color):
    pts = [(cx, cy - half), (cx + half, cy), (cx, cy + half), (cx - half, cy)]
    d = "M %s %s L %s %s L %s %s L %s %s Z" % tuple(
        v for p in pts for v in (_fmt(_uu(p[0])), _fmt(_uu(p[1]))))
    return '<path d="%s" fill="%s" stroke="#FFFFFF" stroke-width="%s"/>' % (
        d, _attr(color), _fmt(0.4))


def _annotations_layer(layout, style):
    out = list(_layer_open("annotations"))
    for ann in layout.get("annotations") or []:
        if not isinstance(ann, dict):
            continue
        prov, skind = _prov_attr(ann)
        pt = _num(ann.get("font_pt"), style["font_sizes_pt"]["legend"])
        line_h = pt * 0.3528 * 1.35
        out.append('<g id="%s" data-prov="%s" data-src-kind="%s" class="caption">'
                   % (_attr(ann.get("id")), _attr(prov), _attr(skind)))
        out.append("<title>%s</title>" % _esc("panel %s caption" % ann.get("panel", "")))
        for i, line in enumerate(ann.get("lines") or []):
            out.append(_text(_num(ann.get("x_mm")), _num(ann.get("y_mm")) + i * line_h,
                             line, pt, style["font_family"],
                             str(ann.get("anchor") or "start")))
        out.append("</g>")
    out.append("</g>")
    return out


# --------------------------------------------------------------------------
# metadata
# --------------------------------------------------------------------------
def _metadata(model, layout, style, chart):
    fig = model.get("figure") if isinstance(model.get("figure"), dict) else {}
    prov = model.get("provenance") if isinstance(model.get("provenance"), dict) else {}
    meta = {
        "schema_version": str(layout.get("schema_version") or model.get("schema_version") or "1.0"),
        "case_id": str(model.get("case_id") or "(none)"),
        "figure_id": str(fig.get("id") or ""),
        "figure_kind": str(fig.get("kind") or ""),
        "model_sha256": _sha256_text(_canonical(model)),
        "generated_by": str(prov.get("generated_by") or "(none)"),
        "created_utc": str(prov.get("created_utc") or "(none)"),
        "unit_scale": {"uu_per_mm": round(MM_TO_UU, 10), "uu_per_pt": round(PT_TO_UU, 10),
                       "base_dpi": 96.0, "canvas_width_mm": _num(
                           (layout.get("canvas") or {}).get("width_mm")),
                       "canvas_height_mm": _num(
                           (layout.get("canvas") or {}).get("height_mm"))},
        "font_stack": list(style["font_stack"]),
        "palette": list(style["palette"]),
        "layers": ["layer:%s" % x for x in LAYER_IDS],
        "id_scheme": {"entity": "ent:<id>", "relation": "rel:<id>",
                      "legend": "lg:<id>", "container": "cnt:<id>|ent:<id>",
                      "axes": "axes:<figure-id>", "series": "series:<index>"},
        "provenance_attributes": ["data-prov", "data-src-kind", "data-rel-type",
                                  "data-direction"],
        "chart": bool(chart),
        "editable_text": True,
    }
    if isinstance(model.get("data"), dict) and model["data"].get("path"):
        meta["data"] = {"path": str(model["data"]["path"]),
                        "sha256": str(model["data"].get("sha256") or "")}
    return meta


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def render(model, layout):
    """Return the complete SVG document for ``model`` + ``layout`` (never raises)."""
    if not isinstance(model, dict):
        model = {}
    if not isinstance(layout, dict):
        layout = {}
    style = _style_of(model, layout)
    canvas = layout.get("canvas") if isinstance(layout.get("canvas"), dict) else {}
    fig = model.get("figure") if isinstance(model.get("figure"), dict) else {}
    fig_canvas = fig.get("canvas") if isinstance(fig.get("canvas"), dict) else {}
    W = _num(canvas.get("width_mm"), _num(fig_canvas.get("width_mm"), 180.0)) or 180.0
    H = _num(canvas.get("height_mm"), _num(fig_canvas.get("height_mm"), 120.0)) or 120.0
    chart = layout.get("chart") if isinstance(layout.get("chart"), dict) else None

    title_text = ""
    if isinstance(layout.get("title"), dict):
        title_text = str(layout["title"].get("text") or "")
    if not title_text and isinstance(fig.get("title"), dict):
        title_text = str(fig["title"].get("text") or "")
    if not title_text:
        title_text = "figure %s" % (fig.get("id") or "(unnamed)")

    body = []
    body.append('<?xml version="1.0" encoding="UTF-8"?>')
    body.append('<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
                'width="%smm" height="%smm" viewBox="0 0 %s %s" '
                'preserveAspectRatio="xMidYMid meet" '
                'shape-rendering="geometricPrecision" text-rendering="geometricPrecision">'
                % (_fmt(W), _fmt(H), _fmt(_uu(W)), _fmt(_uu(H))))
    body.append("<title>%s</title>" % _esc(title_text))
    body.append("<desc>%s</desc>" % _esc(
        "Editable layered scientific figure generated deterministically from a "
        "source-bound model; %s" % (style["font_family"])))
    body.append("<metadata>%s</metadata>" % _esc(_canonical(_metadata(model, layout, style, chart))))
    body.extend(_background_layer(layout, style, chart))
    body.extend(_containers_layer(layout, style))
    body.extend(_edges_layer(layout, style))
    body.extend(_nodes_layer(layout, style, chart))
    body.extend(_labels_layer(layout, style))
    body.extend(_legend_layer(layout, style))
    body.extend(_annotations_layer(layout, style))
    body.append("</svg>")
    return "\n".join(body) + "\n"


def svg_stats(svg_text):
    """Machine-checkable statistics of a rendered SVG (frozen key set)."""
    t = svg_text if isinstance(svg_text, str) else ""
    return {
        "texts": len(re.findall(r"<text[\s>]", t)),
        "paths": len(re.findall(r"<path[\s>]", t)),
        "rects": len(re.findall(r"<rect[\s>]", t)),
        "images": len(re.findall(r"<image[\s>]", t)),
        "layers": len(re.findall(r'<g id="layer:', t)),
        "has_metadata": "<metadata" in t,
        "data_prov_count": len(re.findall(r'data-prov="', t)),
        "bytes": len(t.encode("utf-8")),
    }


def _main(argv):
    import sys
    if len(argv) < 3:
        sys.stderr.write("usage: render_svg.py <model.json> <layout.json> [out.svg]\n")
        return 2
    with open(argv[1], "r", encoding="utf-8") as fh:
        model = json.load(fh)
    with open(argv[2], "r", encoding="utf-8") as fh:
        layout = json.load(fh)
    svg = render(model, layout)
    if len(argv) > 3:
        with open(argv[3], "w", encoding="utf-8", newline="\n") as fh:
            fh.write(svg)
    else:
        sys.stdout.write(svg)
    sys.stderr.write(json.dumps(svg_stats(svg)) + "\n")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv))
