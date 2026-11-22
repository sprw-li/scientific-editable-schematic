# -*- coding: utf-8 -*-
"""run.py - single entry point for the `scientific-editable-schematic` skill.

Stages
------
    prepare   read the case input, inventory the materials, emit a source-bound
              draft model plus a bounded review batch for the agent to revise
    render    validate the agent-revised model, lay it out, write the layered
              editable SVG + the provenance map + the editable model copy
    export    produce the target formats and run the journal compliance gate
    edit      apply a source-preserving edit to the model, redraw, re-export,
              and record the change log
    finish    assemble result.json (all original output_contract fields kept)

Every stage prints exactly one JSON object on stdout; human-readable progress
goes to stderr. Exit codes are frozen in work/CONTRACT.md section 2:
0 ok, 2 config/JSON/path error, 3 environment blocked, 4 produced but a
consistency or compliance gate failed (artifacts are still written honestly).
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common  # noqa: E402
from common import (COMPLIANCE, CONFIG, ENV_BLOCKED, OK, SCHEMA_VERSION,  # noqa: E402
                    SkillError, die, emit, log, now_utc, read_json, safe_relpath,
                    sha256_file, sha256_text, write_json, write_text)

DEFAULT_INPUT = "/input"
DEFAULT_WORK = "/app/work"
DEFAULT_OUTPUT = "/app/output"

MODEL_NAME = "figure_model.json"
DRAFT_NAME = "figure_model.draft.json"
ISSUES_NAME = "figure_issues.json"

FIGURE_STEM = "figure"

# Which output_contract leaf keys map onto which produced artifact. Matching is
# token based and intentionally conservative: we only fill a key when its name
# clearly names an artifact we actually produced.
_CONTRACT_HINTS = (
    ("svg", "svg"),
    ("pdf", "pdf"),
    ("png", "png"),
    ("tiff", "tiff"),
    ("tif", "tiff"),
    ("eps", "eps"),
    ("source", "model"),
    ("model", "model"),
    ("editable", "model"),
    ("changelog", "changelog"),
    ("change_log", "changelog"),
    ("export", "export_report"),
    ("report", "export_report"),
    ("check", "checks"),
    ("result", "result"),
)


# --------------------------------------------------------------------------
# module loading
# --------------------------------------------------------------------------
def _load(name):
    try:
        return __import__(name)
    except ImportError as exc:  # pragma: no cover - only on a broken install
        die("skill module %s.py is missing or unreadable (%s)" % (name, exc), ENV_BLOCKED)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _paths(args):
    inp = common.resolve(getattr(args, "input", None) or DEFAULT_INPUT)
    work = common.resolve(getattr(args, "work", None) or DEFAULT_WORK)
    out = common.resolve(getattr(args, "output", None) or DEFAULT_OUTPUT)
    common.ensure_dir(work)
    common.ensure_dir(out)
    return inp, work, out


def _load_model(work, explicit=None):
    """Return (model, source_path, is_draft)."""
    cands = []
    if explicit:
        cands.append(explicit)
    cands.append(os.path.join(work, MODEL_NAME))
    cands.append(os.path.join(work, DRAFT_NAME))
    for path in cands:
        if os.path.isfile(path):
            model = common.load_json(path)
            if isinstance(model, dict):
                return model, path, os.path.basename(path) == DRAFT_NAME
    die("no figure model found under %s (looked for %s / %s); run `prepare` first "
        "and write the revised model" % (work, MODEL_NAME, DRAFT_NAME), CONFIG)


def _inventory(work):
    inv = common.load_json(os.path.join(work, "source_inventory.json"))
    if not isinstance(inv, dict):
        # Validation must still work without an inventory: it degrades to
        # "cannot verify" (which the validator reports as errors), never to a crash.
        inv = {"schema_version": SCHEMA_VERSION, "units": [], "tables": [], "warnings": [
            "source_inventory.json missing; provenance cannot be verified"]}
    return inv


def _case_manifest(work):
    cm = common.load_json(os.path.join(work, "case_manifest.json"))
    return cm if isinstance(cm, dict) else {}


def _figures_dir(out):
    d = os.path.join(out, "figures")
    common.ensure_dir(d)
    return d


def _write_previews(out):
    """Expose the rendered raster alongside the exports as an inspection preview.

    The runtime contract asks for real rendered PDF/PNG previews for inspection;
    the exports themselves live in figures/, so we surface a copy under preview/
    rather than leaving a reviewer to guess which file is the preview.
    """
    src_png = os.path.join(out, "figures", FIGURE_STEM + ".png")
    if not os.path.isfile(src_png):
        return []
    prev = common.ensure_dir(os.path.join(out, "preview"))
    made = []
    for name in (FIGURE_STEM + ".png",):
        dst = os.path.join(prev, name)
        try:
            with open(src_png, "rb") as fh:
                data = fh.read()
            with open(dst, "wb") as fh:
                fh.write(data)
            made.append(_rel(out, dst))
        except OSError as exc:
            log("[preview] could not write %s: %s" % (dst, exc))
    note = os.path.join(prev, "README.md")
    write_text(note, "# preview/\n\n"
               "Inspection previews of the exported figure (copies of `figures/`).\n"
               "The editable master is `figures/figure.svg`; the module source of "
               "truth is `figure_model.json`.\n")
    made.append(_rel(out, note))
    return made


def _rel(base, path):
    try:
        return safe_relpath(base, path)
    except SkillError:
        return os.path.basename(path)


RESULT_SELF_HASH_BASIS = ("sha256 of this document serialised as canonical JSON with "
                         "artifacts[key='result'].sha256 and .bytes set to null")
RESULT_KEY = "result"


def _self_excluded_hash(doc, key=RESULT_KEY):
    """Digest of a document over itself, with its own hash field nulled out.

    A file cannot contain its own digest, so the digest is defined over the
    document with that one field removed. Anyone can recompute it exactly:
    load result.json, set artifacts[key='result'].{sha256,bytes} to null,
    serialise with sort_keys=True and separators=(",", ":"), sha256 it.
    """
    clone = copy.deepcopy(doc)
    for entry in clone.get("artifacts", []) or []:
        if isinstance(entry, dict) and entry.get("key") == key:
            entry["sha256"] = None
            entry["bytes"] = None
    canon = json.dumps(clone, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(canon)


def _issues_summary(issues):
    return {
        "errors": [i for i in issues.get("errors", [])],
        "warnings": [i for i in issues.get("warnings", [])],
        "stats": issues.get("stats", {}),
        "error_count": len(issues.get("errors", [])),
        "warning_count": len(issues.get("warnings", [])),
    }


def _error_codes(issues, prefix):
    return sorted({i.get("code", "") for i in issues.get("errors", []) if i.get("code")})


def _environment(work):
    env = {
        "recorded_utc": now_utc(),
        "python": sys.version.split()[0],
        "executable": os.path.basename(sys.executable or ""),
        "platform": sys.platform,
        "cwd_writable": os.access(os.getcwd(), os.W_OK),
        "modules": {},
        "tools": {},
        "notes": [],
    }
    for mod in ("matplotlib", "PIL", "pypdf", "lxml", "numpy", "reportlab",
                "cairosvg", "svglib", "pandas"):
        env["modules"][mod] = {"available": common.have(mod),
                               "version": common.module_version(mod)}
    for tool in ("rsvg-convert", "inkscape", "pdfinfo", "pdffonts", "gs", "magick",
                 "convert", "gsdll64"):
        env["tools"][tool] = common.which(tool)
    missing = [k for k, v in env["modules"].items() if not v["available"]]
    if missing:
        env["notes"].append("third-party modules unavailable, optional paths will be "
                            "skipped and reported: " + ", ".join(missing))
    write_json(os.path.join(work, "environment.json"), env)
    return env


def _early_result(out, case_id, output_contract, status, note):
    """Write an honest early result.json so a crash later cannot look like success."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "status": status,
        "output_contract": output_contract or {},
        "artifacts": [],
        "sources": [],
        "uncertainty": [],
        "limitations": [note] if note else [],
        "checks": {"passed": False, "detail": note or "not evaluated yet"},
        "audit": {"written_utc": now_utc(), "stage": "prepare", "skill": common.SKILL_NAME},
    }
    write_json(os.path.join(out, "result.json"), payload)
    return payload


# --------------------------------------------------------------------------
# stage: prepare
# --------------------------------------------------------------------------
def cmd_prepare(args):
    inp, work, out = _paths(args)
    if not os.path.isdir(inp):
        die("input directory does not exist: %s" % inp, ENV_BLOCKED)

    ingest = _load("ingest")
    model_mod = _load("model")

    case_manifest = ingest.discover(inp)
    case_id = str(case_manifest.get("case_id") or "unknown-case")
    contract = case_manifest.get("output_contract") or {}

    inventory = ingest.extract_sources(case_manifest)
    draft = model_mod.draft_model(case_manifest, inventory)
    review = ingest.build_review_batch(case_manifest, inventory, draft)

    paths = ingest.write_artifacts(work, case_manifest, inventory, draft, review)
    env = _environment(work)
    write_json(os.path.join(work, "figure_model.draft.json"), draft)

    # Immediate honest partial result.
    result = _early_result(
        out, case_id, contract, "partial",
        "draft model written; the agent must review %s and write %s before render"
        % ("REVIEW_BATCH.json", MODEL_NAME))

    payload = {
        "stage": "prepare",
        "status": "ok",
        "case_id": case_id,
        "input_dir": inp,
        "work_dir": work,
        "output_dir": out,
        "materials": len(case_manifest.get("files", [])),
        "source_units": len(inventory.get("units", [])),
        "tables": len(inventory.get("tables", [])),
        "draft_entities": len(draft.get("entities", [])),
        "draft_relations": len(draft.get("relations", [])),
        "must_decide": len(review.get("must_decide", [])),
        "uncertainties": len(draft.get("uncertainty", [])),
        "artifacts": {k: _rel(work if str(v).startswith(work) else out, v)
                      for k, v in paths.items()} if isinstance(paths, dict) else {},
        "result_json": _rel(out, os.path.join(out, "result.json")),
        "output_contract_keys": sorted(contract.keys()) if isinstance(contract, dict) else [],
        "environment_modules": {k: v["available"] for k, v in env["modules"].items()},
        "warnings": list(case_manifest.get("warnings", [])) + list(inventory.get("warnings", [])),
        "next": [
            "read %s" % os.path.join(work, "REVIEW_BATCH.json"),
            "revise the draft with real scientific judgement from the materials",
            "write %s" % os.path.join(work, MODEL_NAME),
            "then run: render",
        ],
    }
    if not inventory.get("units") and not inventory.get("tables"):
        result["status"] = "needs_human"
        write_json(os.path.join(out, "result.json"), result)
        payload["status"] = "needs_human"
        payload["detail"] = ("no parseable source material was found; draft contains no "
                            "source-bound content, a human must supply the materials")
        emit(payload)
        return ENV_BLOCKED
    emit(payload)
    return OK


# --------------------------------------------------------------------------
# stage: render
# --------------------------------------------------------------------------
def _do_render(args, model, work, out, case_id, *, record=True):
    model_mod = _load("model")
    layout_mod = _load("layout")
    svg_mod = _load("render_svg")

    inventory = _inventory(work)
    issues = model_mod.validate_model(model, inventory, strict=True)
    layout = layout_mod.layout(model)
    lay_issues = layout_mod.check_layout(layout, model, strict=True)

    merged = {
        "errors": list(issues.get("errors", [])) + list(lay_issues.get("errors", [])),
        "warnings": list(issues.get("warnings", [])) + list(lay_issues.get("warnings", [])),
        "stats": {"model": issues.get("stats", {}), "layout": lay_issues.get("stats", {})},
    }
    write_json(os.path.join(work, ISSUES_NAME), merged)
    write_json(os.path.join(work, "layout.json"), layout)

    svg_text = svg_mod.render(model, layout)
    figs = _figures_dir(out)
    svg_path = os.path.join(figs, FIGURE_STEM + ".svg")
    write_text(svg_path, svg_text)

    # The editable model is itself a delivered source artifact.
    model_out = os.path.join(out, MODEL_NAME)
    write_json(model_out, model)

    source_map = _build_source_map(model, inventory)
    write_json(os.path.join(out, "source_map.json"), source_map)

    stats = svg_mod.svg_stats(svg_text)
    errors = merged["errors"]
    status = "ok" if not errors else "partial"
    if record:
        write_json(os.path.join(out, "render_report.json"), {
            "stage": "render", "status": status, "written_utc": now_utc(),
            "case_id": case_id,
            "svg": _rel(out, svg_path), "svg_bytes": os.path.getsize(svg_path),
            "svg_sha256": sha256_file(svg_path),
            "svg_stats": stats,
            "model_out": _rel(out, model_out),
            "source_map_elements": len(source_map.get("elements", [])),
            "unsupported_elements": source_map.get("unsupported_count", 0),
            "errors": errors, "warnings": merged["warnings"],
        })
    return {
        "svg_path": svg_path, "model_out": model_out, "layout": layout,
        "issues": merged, "stats": stats, "source_map": source_map,
        "status": status, "svg_text": svg_text,
    }


def _build_source_map(model, inventory):
    """element id -> provenance, re-read from the model (single source of truth)."""
    elements, unsupported = [], 0

    def add(element, kind, label, src, bound=None):
        nonlocal unsupported
        if bound is None:
            bound = bool(src) and src.get("kind") in ("explicit", "derived") and src.get("path")
        if not bound:
            unsupported += 1
        elements.append({"element": element, "kind": kind, "label": label or "",
                         "source": src or None, "bound": bool(bound)})

    for kind, key in (("entity", "entities"), ("relation", "relations"),
                      ("container", "containers"), ("legend", "legend")):
        for item in model.get(key) or []:
            add("%s:%s" % (kind[:3], item.get("id")), kind,
                item.get("label") or item.get("type"), item.get("source"))
    for panel in model.get("panels") or []:
        cap = panel.get("caption") or {}
        src = cap.get("source")
        add("panel:%s" % panel.get("id"), "panel", cap.get("text"), src,
            bound=bool(src) and src.get("kind") in ("explicit", "derived"))
    # Data marks are drawn from the table: bind each series to its column so a
    # reviewer can walk from a drawn mark back to the numbers it encodes.
    data = model.get("data") or {}
    data_path = data.get("path") or (model.get("figure", {}).get("kind") == "chart" and None)
    for idx, series in enumerate(data.get("series") or []):
        if not isinstance(series, dict):
            continue
        name = str(series.get("name") or "series[%d]" % idx)
        # Prefer the column the mark's value actually comes from: an explicit
        # column, then the y column, then the single numeric column carrying a
        # unit, and only then the series label (which for a category series is a
        # category value, not a column).
        units = data.get("units") if isinstance(data.get("units"), dict) else {}
        numeric_cols = [c for c in (data.get("columns") or []) if str(units.get(c) or "").strip()]
        col = (series.get("column") or series.get("y_column")
               or (numeric_cols[0] if len(numeric_cols) == 1 else None)
               or (series.get("x_column") if not numeric_cols else None)
               or name)
        src = None
        if data_path:
            src = {"path": data_path, "locator": "table:%s" % col, "kind": "derived",
                   "quote": name,
                   "derived_from": ["table:%s" % c for c in (data.get("columns") or [])]}
        add("series:%d" % idx, "series", name, src)
    if data.get("path") and not (data.get("series") or []):
        add("data:%s" % data.get("path"), "data", data.get("path"),
            {"path": data["path"], "locator": "table", "kind": "derived",
             "quote": "", "derived_from": ["table"]})
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": model.get("case_id"),
        "inventory_units": len(inventory.get("units", [])),
        "elements": elements,
        "unsupported_count": unsupported,
        "bound_count": sum(1 for e in elements if e["bound"]),
    }


def cmd_render(args):
    inp, work, out = _paths(args)
    model, path, is_draft = _load_model(work, getattr(args, "model", None))
    case_id = str(model.get("case_id") or _case_manifest(work).get("case_id") or "unknown-case")
    if is_draft:
        log("[render] WARNING: using the unrevised draft model; provenance may be "
            "incomplete. The agent should write %s first." % MODEL_NAME)
    res = _do_render(args, model, work, out, case_id)
    # An unrevised draft is not a failure of the gates, but it is not a finished
    # figure either: the model-level judgement step has not happened yet, so the
    # status says partial and the reason is reported instead of a silent "ok".
    status = res["status"]
    if status == "ok" and is_draft:
        status = "partial"
    payload = {
        "stage": "render", "status": status, "case_id": case_id,
        "model_used": os.path.basename(path), "used_draft": is_draft,
        "svg": _rel(out, res["svg_path"]),
        "svg_stats": res["stats"],
        "errors": res["issues"]["errors"],
        "warnings": res["issues"]["warnings"],
        "error_codes": _error_codes(res["issues"], "E_"),
        "source_map": {"bound": res["source_map"]["bound_count"],
                       "unsupported": res["source_map"]["unsupported_count"]},
        "next": ["run: export"] if status == "ok" else (
            ["the agent has not revised the draft model; write %s with the real "
             "scientific judgement, then re-run render" % MODEL_NAME] if is_draft and
            not res["issues"]["errors"] else
            ["fix the reported errors in %s and re-run render" % MODEL_NAME]),
    }
    emit(payload)
    return OK if not res["issues"]["errors"] else COMPLIANCE


# --------------------------------------------------------------------------
# stage: export
# --------------------------------------------------------------------------
def _export_spec(args, case_manifest, layout=None):
    export_mod = _load("export")
    preset_name = getattr(args, "journal", None) or "generic"
    spec = export_mod.journal_preset(preset_name)
    spec = dict(spec)
    # The layout may legitimately grow the canvas when content cannot fit; the
    # exporters must measure the size actually drawn, not the size requested.
    if isinstance(layout, dict) and isinstance(layout.get("canvas"), dict):
        spec["canvas"] = layout["canvas"]
    if getattr(args, "dpi", None):
        spec["dpi"] = int(args.dpi)
    if getattr(args, "width_mm", None):
        spec["width_mm"] = float(args.width_mm)
    if getattr(args, "formats", None):
        spec["formats"] = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
    contract = (case_manifest or {}).get("output_contract") or {}
    blob = " ".join(str(k) for k in contract.keys()).lower() if isinstance(contract, dict) else ""
    wanted = list(spec.get("formats") or [])
    for token, fmt in (("svg", "svg"), ("pdf", "pdf"), ("png", "png"),
                       ("tiff", "tiff"), ("eps", "eps")):
        if token in blob and fmt not in wanted:
            wanted.append(fmt)
    for required in ("svg", "pdf", "png"):
        if required not in wanted:
            wanted.append(required)
    spec["formats"] = wanted
    return spec


def cmd_export(args):
    inp, work, out = _paths(args)
    export_mod = _load("export")
    compliance = _load("compliance")
    model, path, _ = _load_model(work, getattr(args, "model", None))
    case_id = str(model.get("case_id") or "unknown-case")
    layout = common.load_json(os.path.join(work, "layout.json"))
    if not isinstance(layout, dict):
        die("layout.json missing; run `render` before `export`", CONFIG)
    svg_path = os.path.join(_figures_dir(out), FIGURE_STEM + ".svg")
    if not os.path.isfile(svg_path):
        die("rendered SVG missing at %s; run `render` before `export`" % svg_path, CONFIG)
    svg_text = common.read_text(svg_path)

    spec = _export_spec(args, _case_manifest(work), layout)
    report = export_mod.export_all(model, layout, svg_text, out, spec, work_dir=work)
    produced = []
    for entry in report.get("formats", []):
        p = entry.get("path")
        if p and os.path.isfile(p):
            produced.append(p)
    checks = compliance.check_artifacts(produced, spec, model=model)
    write_json(os.path.join(out, "export_report.json"), report)
    write_json(os.path.join(out, "checks.json"), checks)
    previews = _write_previews(out)

    ok = bool(checks.get("ok"))
    payload = {
        "stage": "export", "status": "ok" if ok else "partial", "case_id": case_id,
        "spec": {k: v for k, v in spec.items() if k != "notes"},
        "formats": [{k: e.get(k) for k in ("format", "status", "bytes", "dpi",
                                           "color_space", "producer", "error")}
                    for e in report.get("formats", [])],
        "previews": previews,
        "checks": [{"id": c["id"], "level": c["level"], "ok": c["ok"]}
                   for c in checks.get("checks", [])],
        "failed_checks": [c["id"] for c in checks.get("checks", []) if not c.get("ok")],
        "tools": report.get("tools", {}),
        "next": ["run: finish"] if ok else ["inspect checks.json and repair the export spec"],
    }
    emit(payload)
    return OK if ok else COMPLIANCE


# --------------------------------------------------------------------------
# stage: edit (source-preserving)
# --------------------------------------------------------------------------
_ALLOWED_OPS = {"rename_label", "set_label", "set_color", "set_attribute",
                "set_unit", "set_value", "set_number", "update_data", "add_entity",
                "remove_entity", "add_relation", "remove_relation", "set_style"}

# Element targets (`ent:<id>`, `rel:<id>`, `lg:<id>`, `cont:<id>`) name an object,
# not a field; the op decides which field of that object is written. Writing the
# object's `id` instead would silently orphan every reference to it.
_PREFIXES = {"ent": "entities", "rel": "relations", "lg": "legend", "cont": "containers"}
_FIELD_FOR_OP = {"rename_label": "label", "set_label": "label", "set_color": "color",
                 "set_unit": "unit", "set_value": "value", "set_number": "value",
                 "set_attribute": "attributes", "set_style": "style"}
_MERGE_FIELDS = {"attributes", "style"}


def _resolve_pointer(model, target, field=None):
    """Resolve an edit target to (node, key).

    Element form -> (element_object, field) where field comes from the op.
    Dotted form  -> (parent_object, last_key).
    """
    if not target:
        die("edit op is missing 'target'", CONFIG)
    t = str(target)
    if ":" in t.split(".", 1)[0]:
        pfx, ident = t.split(":", 1)
        key = _PREFIXES.get(pfx)
        if not key:
            die("unknown element prefix in target %r (use ent:/rel:/lg:/cont: or a "
                "dotted path)" % t, CONFIG)
        for item in model.get(key) or []:
            if isinstance(item, dict) and str(item.get("id")) == ident:
                if field is None:
                    die("target %r names an element but op %r does not write a field"
                        % (t, field), CONFIG)
                return item, field
        die("edit target not found: %s" % t, CONFIG)
    node = model
    parts = t.split(".")
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            die("edit target path not found: %s" % t, CONFIG)
        node = node[part]
    last = parts[-1]
    if not isinstance(node, dict) or last not in node:
        die("edit target path not found: %s" % t, CONFIG)
    return node, last


def _apply_ops(model, ops_doc):
    if not isinstance(ops_doc, dict) or not isinstance(ops_doc.get("ops"), list):
        die("edit ops file must be {\"ops\": [ ... ]}", CONFIG)
    change_records = []
    new_model = copy.deepcopy(model)
    for idx, op in enumerate(ops_doc["ops"]):
        if not isinstance(op, dict):
            die("edit op #%d is not an object" % idx, CONFIG)
        name = op.get("op")
        if name not in _ALLOWED_OPS:
            die("edit op #%d uses unsupported op %r (allowed: %s)"
                % (idx, name, ", ".join(sorted(_ALLOWED_OPS))), CONFIG)
        value = op.get("value")
        target = op.get("target")

        if name == "add_entity" or name == "add_relation":
            bucket = "entities" if name == "add_entity" else "relations"
            if not isinstance(value, dict) or not value.get("id"):
                die("%s needs value={id,...}" % name, CONFIG)
            if any(str(e.get("id")) == str(value["id"]) for e in new_model.get(bucket) or []):
                die("%s id already exists: %s" % (name, value["id"]), CONFIG)
            new_model.setdefault(bucket, []).append(value)
            before, after = None, value

        elif name in ("remove_entity", "remove_relation"):
            ident = str(target or "").split(":", 1)[-1]
            if name == "remove_entity":
                before = [e for e in new_model.get("entities", [])
                          if str(e.get("id")) == ident]
                new_model["entities"] = [e for e in new_model.get("entities", [])
                                         if str(e.get("id")) != ident]
                new_model["relations"] = [r for r in new_model.get("relations", [])
                                          if str(r.get("from")) != ident
                                          and str(r.get("to")) != ident]
            else:
                before = [r for r in new_model.get("relations", [])
                          if str(r.get("id")) == ident]
                new_model["relations"] = [r for r in new_model.get("relations", [])
                                          if str(r.get("id")) != ident]
            after = None

        elif name == "update_data":
            # Two accepted forms: value is an object merged into model["data"], or a
            # scalar with a dotted target such as data.units.fold_change.
            if isinstance(value, dict):
                data = dict(new_model.get("data") or {})
                before = copy.deepcopy(data)
                data.update(value)
                new_model["data"] = data
                after = data
            else:
                node, key = _resolve_pointer(new_model, target)
                before, node[key], after = node.get(key), value, value

        else:
            field = op.get("field") or _FIELD_FOR_OP.get(name)
            if name in ("rename_label", "set_label") and not op.get("field"):
                field = "label"
            node, key = _resolve_pointer(new_model, target, field)
            before = copy.deepcopy(node.get(key))
            if key in _MERGE_FIELDS and isinstance(value, dict):
                merged = dict(node.get(key) or {})
                merged.update(value)
                node[key] = merged
            else:
                node[key] = value
            after = node.get(key)

        change_records.append({
            "op": name,
            "target": target or ("%s:%s" % (name.replace("add_", ""),
                                            (op.get("value") or {}).get("id"))),
            "before": before,
            "after": after,
            "reason": op.get("reason") or "",
            "source_refs": op.get("source_refs") or [],
            "applied_utc": now_utc(),
        })
    return new_model, change_records


def cmd_edit(args):
    inp, work, out = _paths(args)
    ops_path = common.resolve(getattr(args, "ops", None) or os.path.join(work, "edit_ops.json"))
    if not os.path.isfile(ops_path):
        die("edit ops file not found: %s" % ops_path, CONFIG)
    model, path, _ = _load_model(work, getattr(args, "model", None))
    case_id = str(model.get("case_id") or "unknown-case")

    figs = _figures_dir(out)
    def snapshot():
        snap = {}
        for name in sorted(os.listdir(figs)) if os.path.isdir(figs) else []:
            full = os.path.join(figs, name)
            if os.path.isfile(full):
                snap[name] = sha256_file(full)
        for name in ("checks.json", "export_report.json", MODEL_NAME):
            full = os.path.join(out, name)
            if os.path.isfile(full):
                snap[name] = sha256_file(full)
        return snap

    before_snap = snapshot()
    new_model, records = _apply_ops(model, common.load_json(ops_path))
    prev_path = os.path.join(work, "figure_model.pre-edit.json")
    write_json(prev_path, model)
    write_json(os.path.join(work, MODEL_NAME), new_model)

    res = _do_render(args, new_model, work, out, case_id)

    export_mod = _load("export")
    compliance = _load("compliance")
    spec = _export_spec(args, _case_manifest(work), res["layout"])
    report = export_mod.export_all(new_model, res["layout"], res["svg_text"], out, spec, work_dir=work)
    produced = [e["path"] for e in report.get("formats", [])
                if e.get("path") and os.path.isfile(e["path"])]
    checks = compliance.check_artifacts(produced, spec, model=new_model)
    write_json(os.path.join(out, "export_report.json"), report)
    write_json(os.path.join(out, "checks.json"), checks)
    _write_previews(out)

    after_snap = snapshot()
    changed = sorted({k for k in set(before_snap) | set(after_snap)
                      if before_snap.get(k) != after_snap.get(k)})
    change_log = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "ops_file": ops_path,
        "written_utc": now_utc(),
        "entries": records,
        "artifacts_before": before_snap,
        "artifacts_after": after_snap,
        "artifacts_changed": changed,
        "provenance_preserved": all(
            (e.get("source", {}) or {}).get("kind") in ("explicit", "derived")
            for e in (new_model.get("entities") or []) if e.get("source")),
        "post_edit_errors": res["issues"]["errors"],
    }
    write_json(os.path.join(out, "change_log.json"), change_log)

    status = "ok" if (not res["issues"]["errors"] and checks.get("ok")) else "partial"
    payload = {
        "stage": "edit", "status": status, "case_id": case_id,
        "ops_applied": len(records),
        "artifacts_changed": changed,
        "post_edit_error_codes": _error_codes(res["issues"], "E_"),
        "checks_ok": bool(checks.get("ok")),
        "change_log": _rel(out, os.path.join(out, "change_log.json")),
        "next": ["run: finish"] if status == "ok" else
                ["a source-preserving edit must not introduce unverifiable elements; "
                 "fix the ops or add the missing source"],
    }
    emit(payload)
    return OK if status == "ok" else COMPLIANCE


# --------------------------------------------------------------------------
# stage: finish
# --------------------------------------------------------------------------
def _fill_contract(contract, artifacts):
    """Fill every original output_contract key with a real value, never dropping
    or flattening a key, and never inventing a path that was not produced."""
    if not isinstance(contract, dict):
        return {}
    filled = {}
    for key, value in contract.items():
        token = str(key).lower()
        target = None
        for hint, art in _CONTRACT_HINTS:
            if hint in token and art in artifacts:
                target = art
                break
        if isinstance(value, dict):
            filled[key] = _fill_contract(value, artifacts)
            if target:
                for sub in filled[key]:
                    if isinstance(filled[key][sub], str) and not filled[key][sub]:
                        filled[key][sub] = artifacts[target]
        elif target:
            filled[key] = artifacts[target]
        elif isinstance(value, list):
            filled[key] = value or ([artifacts[target]] if target else [])
        elif value is None or value == "":
            filled[key] = ""
        else:
            # Unknown key with a non-empty default: keep the original value
            # rather than overwriting a contract with a guess.
            filled[key] = value
    return filled


def cmd_finish(args):
    inp, work, out = _paths(args)
    strict = bool(getattr(args, "strict", False))
    model, path, is_draft = _load_model(work, getattr(args, "model", None))
    case_manifest = _case_manifest(work)
    case_id = str(model.get("case_id") or case_manifest.get("case_id") or "unknown-case")
    contract = case_manifest.get("output_contract") or {}
    required = case_manifest.get("required_fields") or []

    figures = {}
    figs = _figures_dir(out)
    for name in sorted(os.listdir(figs)):
        full = os.path.join(figs, name)
        if os.path.isfile(full):
            figures[os.path.splitext(name)[1].lstrip(".").lower()] = full
    model_out = os.path.join(out, MODEL_NAME)
    artifacts = {}
    if os.path.isfile(model_out):
        artifacts["model"] = _rel(out, model_out)
    for fmt, full in figures.items():
        if fmt == "svg":
            artifacts["svg"] = _rel(out, full)
        else:
            artifacts[fmt] = _rel(out, full)
    for key, name in (("changelog", "change_log.json"), ("checks", "checks.json"),
                      ("export_report", "export_report.json"),
                      ("source_map", "source_map.json"),
                      ("preview", os.path.join("preview", FIGURE_STEM + ".png")),
                      ("result", "result.json")):
        full = os.path.join(out, name)
        if os.path.isfile(full) or name == "result.json":
            artifacts[key] = _rel(out, full)

    checks = common.load_json(os.path.join(out, "checks.json")) or {}
    issues = common.load_json(os.path.join(work, ISSUES_NAME)) or {"errors": [], "warnings": []}
    inventory = _inventory(work)
    export_report = common.load_json(os.path.join(out, "export_report.json")) or {}

    artifact_list = []
    for key, relp in sorted(artifacts.items()):
        full = os.path.join(out, relp) if not os.path.isabs(relp) else relp
        entry = {"key": key, "path": relp, "exists": os.path.isfile(full)}
        if entry["exists"]:
            if key == RESULT_KEY:
                # Self-referential: filled in after the document is assembled, and
                # defined so that it is independently recomputable (see hash_basis).
                entry["bytes"] = None
                entry["sha256"] = None
                entry["self_referential"] = True
                entry["hash_basis"] = RESULT_SELF_HASH_BASIS
            else:
                entry["bytes"] = os.path.getsize(full)
                entry["sha256"] = sha256_file(full)
        artifact_list.append(entry)

    sources = []
    for unit in inventory.get("units", [])[:200]:
        sources.append({"path": unit.get("path"), "locator": unit.get("locator"),
                        "sha256": unit.get("sha256")})
    for tbl in inventory.get("tables", [])[:50]:
        sources.append({"path": tbl.get("path"), "locator": "table",
                        "sha256": tbl.get("sha256")})

    formats_ok = [e for e in export_report.get("formats", []) if e.get("status") == "ok"]
    unavailable = [e.get("format") for e in export_report.get("formats", [])
                   if e.get("status") == "unavailable"]
    errors = issues.get("errors", [])
    has_core = bool(artifacts.get("svg")) and bool(artifacts.get("model"))

    if not inventory.get("units") and not inventory.get("tables"):
        status = "needs_human"
    elif errors or not has_core or not checks.get("ok") or is_draft:
        status = "partial" if has_core else "needs_human"
    else:
        status = "ok"

    limitations = []
    if is_draft:
        limitations.append("the model was not revised by an agent; it is the raw draft")
    if errors:
        limitations.append("%d unresolved model/layout error(s): %s"
                           % (len(errors), ", ".join(_error_codes(issues, "E_"))))
    if unavailable:
        limitations.append("formats unavailable in this environment: " + ", ".join(sorted(set(unavailable))))
    if not checks.get("ok"):
        failed = [c["id"] for c in checks.get("checks", []) if not c.get("ok")]
        if failed:
            limitations.append("failed export checks: " + ", ".join(failed))
    limitations.extend(case_manifest.get("warnings", [])[:10])

    uncertainty = list(model.get("uncertainty") or [])
    for cid in ("E_QUOTE_NOT_FOUND", "E_LABEL_NOT_IN_SOURCE"):
        for err in errors:
            if err.get("code") == cid:
                uncertainty.append({"where": err.get("where", ""), "issue": err.get("message", "")})

    filled = _fill_contract(contract, artifacts)
    missing_required = [k for k in required
                        if isinstance(filled, dict) and not filled.get(k)]

    result = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "status": status,
        "output_contract": filled,
        "required_fields_present": {k: bool(filled.get(k)) for k in required} if isinstance(filled, dict) else {},
        "missing_required_fields": missing_required,
        "artifacts": artifact_list,
        "sources": sources,
        "source_unit_count": len(inventory.get("units", [])),
        "table_count": len(inventory.get("tables", [])),
        "uncertainty": uncertainty,
        "limitations": limitations,
        "checks": {
            "export_ok": bool(checks.get("ok")),
            "export_checks": [{"id": c["id"], "ok": c["ok"], "level": c["level"],
                               "detail": c.get("detail")} for c in checks.get("checks", [])],
            "model_errors": len(errors),
            "model_warnings": len(issues.get("warnings", [])),
            "formats_ok": [e.get("format") for e in formats_ok],
            "formats_unavailable": sorted(set(unavailable)),
        },
        "audit": {
            "skill": common.SKILL_NAME,
            "skill_path": os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "stage": "finish",
            "written_utc": now_utc(),
            "model_file_used": os.path.basename(path),
            "model_sha256": sha256_text(common.read_text(path)) if os.path.isfile(path) else None,
            "output_dir": out,
            "work_dir": work,
            "deterministic": True,
        },
    }
    # The self digest is defined over the assembled document with its own hash
    # field nulled, so it stays stable after this assignment and is recomputable.
    for entry in result["artifacts"]:
        if entry.get("self_referential"):
            entry["sha256"] = _self_excluded_hash(result)
    write_json(os.path.join(out, "result.json"), result)

    payload = {
        "stage": "finish", "status": status, "case_id": case_id,
        "result_json": _rel(out, os.path.join(out, "result.json")),
        "artifacts": {a["key"]: a["path"] for a in artifact_list},
        "output_contract_keys": sorted(contract.keys()) if isinstance(contract, dict) else [],
        "missing_required_fields": missing_required,
        "export_ok": bool(checks.get("ok")),
        "formats_ok": result["checks"]["formats_ok"],
        "formats_unavailable": result["checks"]["formats_unavailable"],
        "limitations": limitations,
    }
    emit(payload)
    if strict and status != "ok":
        return ENV_BLOCKED
    return OK


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="run.py",
        description="Source-bound editable scientific schematic: prepare -> render -> "
                    "export -> (edit) -> finish")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("--input", default=None, help="input root (default /input)")
        sp.add_argument("--work", default=None, help="work dir (default /app/work)")
        sp.add_argument("--output", default=None, help="output dir (default /app/output)")

    sp = sub.add_parser("prepare", help="inventory materials and emit the draft model")
    add_common(sp)
    sp.set_defaults(func=cmd_prepare)

    sp = sub.add_parser("render", help="validate, lay out and write the editable SVG")
    add_common(sp)
    sp.add_argument("--model", default=None, help="explicit model path (default <work>/figure_model.json)")
    sp.set_defaults(func=cmd_render)

    sp = sub.add_parser("export", help="produce target formats and run compliance checks")
    add_common(sp)
    sp.add_argument("--model", default=None)
    sp.add_argument("--journal", default="generic",
                    help="journal preset: nature|science|cell|ieee|generic")
    sp.add_argument("--dpi", default=None, type=int)
    sp.add_argument("--width-mm", default=None)
    sp.add_argument("--formats", default=None, help="comma separated override, e.g. svg,pdf,png")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("edit", help="apply a source-preserving edit and redraw")
    add_common(sp)
    sp.add_argument("--model", default=None)
    sp.add_argument("--ops", default=None, help="operations JSON (default <work>/edit_ops.json)")
    sp.add_argument("--journal", default="generic")
    sp.add_argument("--dpi", default=None, type=int)
    sp.add_argument("--width-mm", default=None)
    sp.add_argument("--formats", default=None)
    sp.set_defaults(func=cmd_edit)

    sp = sub.add_parser("finish", help="assemble result.json")
    add_common(sp)
    sp.add_argument("--model", default=None)
    sp.add_argument("--strict", action="store_true", help="exit 3 unless status==ok")
    sp.set_defaults(func=cmd_finish)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except SkillError as exc:
        emit({"stage": getattr(args, "cmd", None), "status": "error",
              "error": str(exc), "exit_code": exc.code})
        log("ERROR: %s" % exc)
        return exc.code
    except KeyboardInterrupt:  # pragma: no cover
        emit({"stage": getattr(args, "cmd", None), "status": "error",
              "error": "interrupted", "exit_code": ENV_BLOCKED})
        return ENV_BLOCKED
    except Exception as exc:  # noqa: BLE001 - never hide a stack trace from the log
        traceback.print_exc(file=sys.stderr)
        emit({"stage": getattr(args, "cmd", None), "status": "error",
              "error": "%s: %s" % (type(exc).__name__, exc), "exit_code": CONFIG})
        return CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
