# -*- coding: utf-8 -*-
"""Journal-compliance gate for exported figure artifacts.

Frozen interface (CONTRACT.md section 4.6)::

    check_artifacts(paths, spec, *, model=None) -> dict

Every check really opens the artifact it talks about: SVG is parsed as XML,
rasters are opened with Pillow, PDFs with pypdf, EPS and magic bytes read from
disk.  A check that cannot run because its input is missing or corrupt returns
``ok=False`` with a clear ``detail`` -- it never raises and never silently
passes.

Return value::

    {"checks": [{"id","level","ok","detail","evidence"}], "ok": bool, ...}

``level`` is ``"error"`` only for defects that genuinely break a journal
submission; advisory problems are ``"warn"`` and do not flip ``ok``.
"""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET

try:  # package-style import
    from . import common
except ImportError:  # flat import from the scripts directory
    import common

SCHEMA_VERSION = common.SCHEMA_VERSION
MM_PER_INCH = common.MM_PER_INCH
PT_PER_INCH = common.PT_PER_INCH

REQUIRED_SVG_LAYERS = 6

MAGIC = {
    "pdf": [b"%PDF-"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "tiff": [b"II*\x00", b"MM\x00*"],
    "eps": [b"%!PS"],
}

_EXT_TO_FORMAT = {
    ".svg": "svg", ".pdf": "pdf", ".png": "png",
    ".tif": "tiff", ".tiff": "tiff", ".eps": "eps", ".ps": "eps",
}


# ---------------------------------------------------------------------------
# Spec / path normalisation
# ---------------------------------------------------------------------------
_FALLBACK_PRESETS = {
    "nature": {"width_mm": 89.0, "width_double_mm": 183.0, "dpi": 300,
               "min_line_width_pt": 0.5, "min_text_pt": 5.0, "max_height_mm": 247.0,
               "color_space": "RGB", "font_embedding_required": True,
               "formats": ["svg", "pdf", "png", "tiff", "eps"]},
    "science": {"width_mm": 55.0, "width_double_mm": 120.0, "dpi": 300,
                "min_line_width_pt": 0.5, "min_text_pt": 6.0, "max_height_mm": 240.0,
                "color_space": "RGB", "font_embedding_required": True,
                "formats": ["svg", "pdf", "png", "tiff", "eps"]},
    "cell": {"width_mm": 85.0, "width_double_mm": 174.0, "dpi": 300,
             "min_line_width_pt": 0.5, "min_text_pt": 6.0, "max_height_mm": 240.0,
             "color_space": "RGB", "font_embedding_required": True,
             "formats": ["svg", "pdf", "png", "tiff", "eps"]},
    "ieee": {"width_mm": 88.9, "width_double_mm": 181.8, "dpi": 300,
             "min_line_width_pt": 0.5, "min_text_pt": 8.0, "max_height_mm": 240.0,
             "color_space": "RGB", "font_embedding_required": True,
             "formats": ["svg", "pdf", "png", "tiff", "eps"]},
    "generic": {"width_mm": 180.0, "width_double_mm": 180.0, "dpi": 300,
                "min_line_width_pt": 0.5, "min_text_pt": 6.0, "max_height_mm": 240.0,
                "color_space": "RGB", "font_embedding_required": True,
                "formats": ["svg", "pdf", "png", "tiff", "eps"]},
}


def _journal_preset(name):
    """Use export.journal_preset; if the sibling cannot be imported, use the same
    values from a local copy (only reachable when import is impossible, so the
    preset table stays identical to the exporter's)."""
    key = str(name or "generic").strip().lower().replace("-", "_")
    try:
        try:
            from . import export as _export_mod  # noqa: WPS433
        except Exception:  # noqa: BLE001 - flat layout
            import export as _export_mod  # type: ignore # noqa: WPS433
        return _export_mod.journal_preset(key)
    except common.SkillError:
        raise
    except Exception:  # noqa: BLE001 - sibling unavailable: local mirror, still real
        if key not in _FALLBACK_PRESETS:
            common.die("unknown journal preset %r (known: %s)"
                       % (name, ", ".join(sorted(_FALLBACK_PRESETS))), common.CONFIG)
        out = dict(_FALLBACK_PRESETS[key])
        out["name"] = key
        out["source"] = ("export.py unreachable: using compliance.py's mirrored preset "
                         "table (identical values)")
        return out


def _spec(spec) -> dict:
    """Read the compliance-relevant spec keys; tolerate presets and overrides."""
    if spec is None:
        spec = {}
    if isinstance(spec, str):
        # A named preset must be real: an unknown name is a caller/config error.
        spec = _journal_preset(spec)
    out = dict(spec) if isinstance(spec, dict) else {}
    if out.get("preset") and "dpi" not in out:
        preset = _journal_preset(str(out["preset"]))
        for key, value in preset.items():
            out.setdefault(key, value)
    out["dpi"] = int(round(float(out.get("dpi") or 300)))
    out["min_line_width_pt"] = float(out.get("min_line_width_pt") or 0.5)
    out["min_text_pt"] = float(out.get("min_text_pt") or 0.0)
    out["color_space"] = str(out.get("color_space") or "RGB").upper()
    out["font_embedding_required"] = bool(out.get("font_embedding_required", True))
    out["width_mm"] = float(out.get("width_mm") or 180.0)
    out["max_height_mm"] = float(out.get("max_height_mm") or 240.0)
    formats = out.get("formats") or ["svg", "pdf", "png", "tiff"]
    if isinstance(formats, str):
        formats = [formats]
    out["formats"] = [str(f).lower().lstrip(".") for f in formats]
    out["cmyk_explicit"] = out["color_space"] == "CMYK"
    return out


def _normalise_paths(paths):
    """Accept list[str], list[dict], dict{name: path|dict}, or a directory."""
    found = []
    if paths is None:
        return found
    if isinstance(paths, (str, os.PathLike)):
        paths = [paths]
    if isinstance(paths, dict):
        found = []
        for name, value in paths.items():
            if isinstance(value, dict):
                entry = dict(value)
                entry.setdefault("path", entry.get("path"))
                entry.setdefault("name", name)
                found.append(entry)
            else:
                found.append({"name": name, "path": value})
        paths = found
    if isinstance(paths, (str, os.PathLike)):  # pragma: no cover - handled above
        paths = [paths]
    out = []
    for item in paths:
        if isinstance(item, dict):
            path = item.get("path")
            name = item.get("name") or (os.path.basename(str(path)) if path else "")
            entry = dict(item)
            entry["name"] = name
            entry["format"] = (entry.get("format") or _EXT_TO_FORMAT.get(
                os.path.splitext(str(path or name))[1].lower(), "")).lower()
            out.append(entry)
        else:
            path = str(item)
            out.append({"path": path, "name": os.path.basename(path),
                        "format": _EXT_TO_FORMAT.get(
                            os.path.splitext(path)[1].lower(), "")})
    resolved = []
    for entry in out:
        path = entry.get("path")
        if not path:
            resolved.append(entry)
            continue
        path = str(path)
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                child = os.path.join(path, name)
                fmt = _EXT_TO_FORMAT.get(os.path.splitext(name)[1].lower())
                if os.path.isfile(child) and fmt:
                    resolved.append({"path": child, "name": name, "format": fmt})
            continue
        entry["path"] = os.path.abspath(path)
        resolved.append(entry)
    return resolved


def _by_format(entries):
    groups = {}
    for entry in entries:
        groups.setdefault(entry.get("format") or "unknown", []).append(entry)
    return groups


def _check(check_id, level, ok, detail, evidence=None):
    return {"id": check_id, "level": level, "ok": bool(ok), "detail": detail,
            "evidence": evidence if evidence is not None else {}}


def _missing_check(check_id, what, channels, fmts, optional=False):
    """N/A when the format was never requested; a real failure when it was.

    Keeps the frozen check id present in every report while never claiming a
    pass for an artifact that should exist.  ``optional=True`` marks formats
    whose absence is advisory (e.g. EPS is an extra, not a core deliverable).
    """
    requested = [f for f in fmts if f in channels.get("formats", [])]
    if not requested:
        return _check(check_id, "warn", True,
                      "N/A: %s not requested by spec (%s)"
                      % (what, ", ".join(channels.get("formats") or [])),
                      {"applicable": False, "requested_formats": channels.get("formats")})
    level = "warn" if optional else "error"
    return _check(check_id, level, bool(optional),
                  "%s requested by spec (%s) but no %s artifact was supplied"
                  % (", ".join(requested), ", ".join(channels.get("formats") or []), what)
                  + ("; treated as advisory (optional extra format)" if optional else ""),
                  {"applicable": True, "missing_formats": requested, "optional": optional})


def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# SVG helpers
# ---------------------------------------------------------------------------
def _parse_svg(path):
    """Return (root, error_string).  Namespace-agnostic element handling."""
    try:
        raw = _read_bytes(path)
    except OSError as exc:
        return None, "cannot read file: %s" % exc
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return None, "not well-formed XML: %s" % exc
    return root, None


def _strip_ns(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag


def _iter_all(root):
    for el in root.iter():
        yield el


def _attr(el, name, default=None):
    if name in el.attrib:
        return el.attrib[name]
    for key, value in el.attrib.items():
        if _strip_ns(key) == name:
            return value
    return default


def _svg_text_elements(root):
    return [el for el in _iter_all(root) if _strip_ns(el.tag) == "text"]


def _text_content(el):
    return "".join(el.itertext()).strip()


def _svg_length_to_mm(value, axis_mm=None, viewbox_extent=None):
    """Convert an SVG length to mm using an explicit unit or a known scale."""
    if value is None:
        return None
    m = re.match(r"^\s*([+-]?[0-9.]+(?:[eE][+-]?[0-9]+)?)\s*([a-zA-Z%]*)\s*$", str(value))
    if not m:
        return None
    number = float(m.group(1))
    unit = m.group(2).lower()
    if unit == "mm":
        return number
    if unit == "cm":
        return number * 10.0
    if unit in ("in",):
        return number * MM_PER_INCH
    if unit == "pt":
        return common.pt_to_mm(number)
    if unit == "pc":
        return common.pt_to_mm(number * 12.0)
    if unit in ("px", ""):
        # Unitless/viewBox user units: use the known physical size when supplied.
        if axis_mm is not None and viewbox_extent:
            return number * (float(axis_mm) / float(viewbox_extent))
        return number * (MM_PER_INCH / 96.0)  # CSS px
    return None


def _svg_canvas_mm(root, metadata=None):
    width_mm = _svg_length_to_mm(_attr(root, "width"))
    height_mm = _svg_length_to_mm(_attr(root, "height"))
    if metadata:
        canvas = (metadata.get("canvas") or {}) if isinstance(metadata, dict) else {}
        width_mm = width_mm or (float(canvas["width_mm"]) if canvas.get("width_mm") else None)
        height_mm = height_mm or (float(canvas["height_mm"]) if canvas.get("height_mm") else None)
    return width_mm, height_mm


def _svg_metadata(root):
    for el in _iter_all(root):
        if _strip_ns(el.tag) == "metadata":
            text = (el.text or "").strip()
            if not text:
                text = "".join(el.itertext()).strip()
            if not text:
                continue
            try:
                return json.loads(text)
            except ValueError:
                try:  # some writers double-escape the JSON inside <metadata>
                    from xml.sax.saxutils import unescape
                    return json.loads(unescape(text))
                except (ValueError, ImportError):
                    continue
    return {}


def _ancestor_scale_map(root):
    """Approximate cumulative transform scale for every element (stroke widths)."""
    scales = {}
    parents = {child: parent for parent in _iter_all(root) for child in parent}

    def local_scale(transform):
        if not transform:
            return 1.0
        scale = 1.0
        for op, args in re.findall(r"(matrix|scale|translate|rotate)\s*\(([^)]*)\)", transform):
            nums = [float(x) for x in re.split(r"[\s,]+", args.strip()) if x]
            if op == "scale" and nums:
                scale *= (nums[0] * (nums[1] if len(nums) > 1 else nums[0])) ** 0.5
            elif op == "matrix" and len(nums) >= 4:
                scale *= (abs(nums[0] * nums[3] - nums[1] * nums[2])) ** 0.5
        return scale or 1.0

    for el in _iter_all(root):
        own = local_scale(_attr(el, "transform"))
        parent = parents.get(el)
        accumulated = own
        guard = 0
        while parent is not None and guard < 64:
            accumulated *= local_scale(_attr(parent, "transform"))
            parent = parents.get(parent)
            guard += 1
        scales[el] = accumulated
    return scales


_STROKE_UNIT_RE = re.compile(r"^\s*([+-]?[0-9.]+(?:[eE][+-]?[0-9]+)?)\s*([a-zA-Z%]*)\s*$")


def _stroke_width_pt(el, mm_per_user, scale):
    raw = _attr(el, "stroke-width")
    style = _attr(el, "style") or ""
    if raw is None:
        m = re.search(r"stroke-width\s*:\s*([^;]+)", style)
        if m:
            raw = m.group(1)
    if raw is None:
        return None
    m = _STROKE_UNIT_RE.match(str(raw))
    if not m:
        return None
    number = float(m.group(1))
    unit = m.group(2).lower()
    if unit == "pt":
        return number
    if unit == "mm":
        return common.mm_to_pt(number)
    if unit == "cm":
        return common.mm_to_pt(number * 10.0)
    if unit == "in":
        return number * PT_PER_INCH
    if unit in ("px", ""):
        return common.mm_to_pt(number * mm_per_user) * (scale or 1.0)
    return None


# ---------------------------------------------------------------------------
# Raster helpers
# ---------------------------------------------------------------------------
def _dpi_from_image(im):
    try:
        dpi = im.info.get("dpi")
    except AttributeError:
        dpi = None
    if dpi:
        try:
            return float(dpi[0]), float(dpi[1]), "image.info(dpi)"
        except (TypeError, ValueError, IndexError):
            pass
    tag_v2 = getattr(im, "tag_v2", None)
    if tag_v2:
        xres = tag_v2.get(282)
        yres = tag_v2.get(283)
        unit = tag_v2.get(296, 2)
        if xres:
            factor = 1.0 if unit == 2 else (2.54 if unit == 3 else 1.0)
            try:
                return float(xres) * factor, float(yres or xres) * factor, "TIFF tag 282/283"
            except (TypeError, ValueError):
                pass
    return None, None, None


def _open_image(path):
    """Open + verify + fully load an image; returns (im, error)."""
    try:
        from PIL import Image
    except Exception as exc:  # noqa: BLE001
        return None, "Pillow unavailable (%s): cannot open rasters" % exc
    try:
        im = Image.open(path)
    except Exception as exc:  # noqa: BLE001
        return None, "PIL cannot identify the image: %s" % exc
    try:
        im.verify()
    except Exception as exc:  # noqa: BLE001
        return None, "PIL verify() failed (file is truncated or corrupt): %s" % exc
    try:
        im = Image.open(path)  # verify() leaves the object unusable
        im.load()
    except Exception as exc:  # noqa: BLE001
        return None, "PIL cannot decode pixel data: %s" % exc
    return im, None


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------
def _quiet_pypdf(name):
    """Keep pypdf's own warnings off stderr; this module reports the findings."""
    try:
        import logging
        logging.getLogger(name).setLevel(logging.ERROR)
    except Exception:  # noqa: BLE001
        pass


def _pdf_reader(path):
    try:
        from pypdf import PdfReader
        _quiet_pypdf("pypdf")
    except Exception:  # noqa: BLE001
        try:
            from PyPDF2 import PdfReader  # type: ignore
            _quiet_pypdf("PyPDF2")
        except Exception as exc:  # noqa: BLE001
            return None, "no PDF parser installed (pypdf / PyPDF2): %s" % exc, None
    try:
        reader = PdfReader(path)
    except Exception as exc:  # noqa: BLE001
        return None, "pypdf cannot open the file: %s: %s" % (type(exc).__name__, exc), None
    try:
        npages = len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        return None, "pypdf cannot read the page tree: %s" % exc, None
    return reader, None, npages


def _pdf_fonts(reader):
    """Walk every page /Resources /Font (and Form XObject resources)."""
    fonts = []

    def _obj(value):
        try:
            return value.get_object()
        except Exception:  # noqa: BLE001
            return value

    def walk(resources, depth=0):
        if resources is None or depth > 4:
            return
        resources = _obj(resources)
        if not isinstance(resources, dict):
            return
        font_dict = _obj(resources.get("/Font"))
        if isinstance(font_dict, dict):
            for name, ref in font_dict.items():
                fdict = _obj(ref)
                if isinstance(fdict, dict):
                    fonts.append((str(name), fdict))
        xobjects = _obj(resources.get("/XObject"))
        if isinstance(xobjects, dict):
            for _name, ref in xobjects.items():
                xobj = _obj(ref)
                if isinstance(xobj, dict) and str(xobj.get("/Subtype")) == "/Form":
                    walk(xobj.get("/Resources"), depth + 1)

    for page in reader.pages:
        walk(page.get("/Resources"))
    return fonts


def _font_descriptor(fdict):
    descriptor = fdict.get("/FontDescriptor")
    if descriptor is not None:
        try:
            descriptor = descriptor.get_object()
        except Exception:  # noqa: BLE001
            descriptor = None
    if isinstance(descriptor, dict):
        return descriptor
    descendants = fdict.get("/DescendantFonts")
    if descendants is not None:
        try:
            descendants = descendants.get_object()
        except Exception:  # noqa: BLE001
            descendants = None
        if descendants:
            try:
                first = descendants[0]
            except (TypeError, IndexError):
                first = None
            first = first.get_object() if hasattr(first, "get_object") else first
            if isinstance(first, dict):
                desc = first.get("/FontDescriptor")
                if desc is not None:
                    desc = desc.get_object() if hasattr(desc, "get_object") else desc
                    if isinstance(desc, dict):
                        return desc
    return None


def _font_report(fdict):
    subtype = str(fdict.get("/Subtype") or "")
    base = str(fdict.get("/BaseFont") or fdict.get("/Name") or "?")
    descriptor = _font_descriptor(fdict)
    files = []
    if isinstance(descriptor, dict):
        for key in ("/FontFile", "/FontFile2", "/FontFile3"):
            if descriptor.get(key) is not None:
                files.append(key.lstrip("/"))
    embedded = bool(files)
    if subtype == "/Type3":
        # Type3 glyphs are inline procedure streams: neither embedded nor selectable.
        embedded = False
    return {"name": base, "subtype": subtype or "?", "embedded": embedded,
            "files": files,
            "embedded_as": ("TrueType" if "FontFile2" in files
                            else ("Type1" if "FontFile" in files
                                  else ("CFF/OpenType" if "FontFile3" in files else None)))}


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------
def _check_svg_layers(svg_entries, channels):
    if not svg_entries:
        return _missing_check("svg_layers", "SVG", channels, ["svg"])
    evidence = {}
    all_ok = True
    problems = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            all_ok = False
            evidence[entry["name"]] = {"error": err}
            problems.append("%s: %s" % (entry["name"], err))
            continue
        layers = []
        for el in _iter_all(root):
            if _strip_ns(el.tag) != "g":
                continue
            ident = _attr(el, "id") or ""
            if ident.startswith("layer:") or _attr(el, "data-layer") is not None:
                layers.append(ident or _attr(el, "data-layer"))
        count = len(set(layers))
        evidence[entry["name"]] = {"layers": sorted(set(layers)), "count": count,
                                   "required": REQUIRED_SVG_LAYERS}
        if count < REQUIRED_SVG_LAYERS:
            all_ok = False
            problems.append("%s: %d layer groups (< %d required)"
                            % (entry["name"], count, REQUIRED_SVG_LAYERS))
    detail = ("layer groups: %s" % ", ".join(
        "%s=%d" % (name, ev.get("count", 0)) for name, ev in evidence.items()))
    if problems:
        detail = "; ".join(problems) + " (" + detail + ")"
    return _check("svg_layers", "error", all_ok, detail, evidence)


def _check_svg_editable(svg_entries, channels):
    if not svg_entries:
        return _missing_check("svg_editable_text", "SVG", channels, ["svg"])
    evidence = {}
    all_ok = True
    problems = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            all_ok = False
            evidence[entry["name"]] = {"error": err}
            problems.append("%s: %s" % (entry["name"], err))
            continue
        texts = _svg_text_elements(root)
        text_chars = sum(len(_text_content(el)) for el in texts)
        images = [el for el in _iter_all(root) if _strip_ns(el.tag) == "image"]
        # An <image> is only acceptable inside a layer explicitly marked as a chart raster.
        rasterised_layers = set()
        image_parents = {}
        for parent in _iter_all(root):
            for child in parent:
                image_parents[child] = parent
        bad_images = []
        for img in images:
            parent = image_parents.get(img)
            allowed = False
            guard = 0
            while parent is not None and guard < 32:
                ident = (_attr(parent, "id") or "") + " " + (_attr(parent, "data-role") or "")
                if "raster" in ident.lower() or "chart" in ident.lower():
                    allowed = True
                    break
                parent = image_parents.get(parent)
                guard += 1
            if not allowed:
                bad_images.append(_attr(img, "id") or "image")
        text_as_path = []
        for el in _iter_all(root):
            tag = _strip_ns(el.tag)
            role = str(_attr(el, "data-role") or "") + " " + str(_attr(el, "class") or "")
            ident = str(_attr(el, "id") or "")
            if tag == "path" and (re.search(r"text|glyph|label", role, re.I)
                                  or ident.startswith(("text:", "txt:", "glyph:"))):
                text_as_path.append(ident or role.strip() or "path")
        faces = sorted({str(_attr(el, "font-family") or _attr(el, "font")) for el in texts
                        if _attr(el, "font-family") or _attr(el, "font")})
        evidence[entry["name"]] = {
            "text_elements": len(texts), "text_chars": text_chars,
            "text_as_path": text_as_path[:20],
            "images": len(images), "images_outside_chart": bad_images[:20],
            "font_families": faces[:8],
        }
        if not texts:
            all_ok = False
            problems.append("%s: 0 <text> elements (no editable text)" % entry["name"])
        if text_as_path:
            all_ok = False
            problems.append("%s: %d text-as-path element(s)" % (entry["name"], len(text_as_path)))
        if bad_images:
            all_ok = False
            problems.append("%s: %d <image> outside a chart raster"
                            % (entry["name"], len(bad_images)))
    detail = "; ".join(problems) if problems else (
        "editable text present: %s" % ", ".join(
            "%s=%d <text>/%d chars" % (n, e.get("text_elements", 0), e.get("text_chars", 0))
            for n, e in evidence.items()))
    return _check("svg_editable_text", "error", all_ok, detail, evidence)


def _requested_canvas_mm(model, channels):
    """The *requested* figure size: model.figure.canvas (or the spec width)."""
    canvas = ((model or {}).get("figure") or {}).get("canvas") or {}
    try:
        width = float(canvas.get("width_mm") or channels["width_mm"])
    except (TypeError, ValueError):
        width = float(channels["width_mm"])
    try:
        height = float(canvas.get("height_mm") or 0) or None
    except (TypeError, ValueError):
        height = None
    return width, height


def _drawn_canvas_mm(svg_entries, model, channels):
    """The size the artifacts were **actually drawn at**.

    A layout may legitimately grow the canvas (``layout.stats.canvas_adjusted``),
    so the rendered master SVG is the authoritative record of the drawn size;
    ``spec["canvas"]``/``spec["layout_canvas"]`` win when the caller passes the
    layout through, and ``model.figure.canvas`` is only the *requested* size.
    """
    for key in ("canvas", "layout_canvas"):
        raw = channels.get(key)
        if isinstance(raw, dict) and raw.get("width_mm"):
            try:
                return {"width_mm": float(raw["width_mm"]),
                        "height_mm": float(raw.get("height_mm") or 0) or None,
                        "source": "spec[%r] (layout canvas)" % key}
            except (TypeError, ValueError):
                pass
    for entry in svg_entries or []:
        path = entry.get("path")
        if not path or not os.path.isfile(path):
            continue
        root, err = _parse_svg(path)
        if err:
            continue
        width, height = _svg_canvas_mm(root, _svg_metadata(root))
        if width:
            return {"width_mm": float(width), "height_mm": float(height) if height else None,
                    "source": "rendered SVG width/height (%s)" % entry.get("name")}
    width, height = _requested_canvas_mm(model, channels)
    return {"width_mm": width, "height_mm": height, "source": "model.figure.canvas (requested)"}


def _canvas_drift_note(model, drawn, channels):
    """Advisory when the drawn size differs from the requested canvas."""
    requested_w, requested_h = _requested_canvas_mm(model, channels)
    notes = []
    tol_w = max(0.5, requested_w * 0.02)
    if abs(drawn["width_mm"] - requested_w) > tol_w:
        notes.append("canvas width requested %.1f mm, drawn %.1f mm"
                     % (requested_w, drawn["width_mm"]))
    if requested_h and drawn.get("height_mm"):
        tol_h = max(0.5, requested_h * 0.02)
        if abs(drawn["height_mm"] - requested_h) > tol_h:
            notes.append("canvas height requested %.1f mm, drawn %.1f mm (a layout may grow "
                         "the canvas: layout.stats.canvas_adjusted)"
                         % (requested_h, drawn["height_mm"]))
    return notes


def _provenance_expectation(model):
    """How many ``data-prov`` bindings the SVG must carry for this model.

    Relationship schematics must bind every entity, relation, container and
    legend entry.  A chart figure binds the plotted values instead (one per
    series point) plus its legend entries and panels -- its entities are axis
    categories, not drawn boxes, so the schematic count would be the wrong bar.
    """
    if not isinstance(model, dict):
        return 0
    base = sum(len(model.get(key) or []) for key in
               ("entities", "relations", "containers", "legend"))
    kind = str(((model.get("figure") or {}).get("kind")) or "")
    if kind == "chart":
        data = model.get("data") or {}
        points = sum(len((series or {}).get("y") or []) for series in (data.get("series") or []))
        chart_expect = len(model.get("legend") or []) + points + len(model.get("panels") or [])
        return min(base, max(3, chart_expect)) if base else max(3, chart_expect)
    return base


_LOCATOR_RE = re.compile(r"^(L\d+(-L\d+)?|p\d+|table:[^\s#]+|fig:\d+)$")


def _locator_problem(value):
    """Return why a ``data-prov`` is outside the frozen CONTRACT 4.7 form, or None.

    Frozen form: ``<POSIX path relative to the input root>#<locator>`` with
    ``locator`` in ``L12 | L12-L18 | p3 | table:col | fig:1``.  The ``(none)``
    placeholder is accepted only as ``(none)#(none)`` for elements with no source.
    """
    text = str(value or "").strip()
    if not text:
        return "empty data-prov"
    if text in ("(none)#(none)", "(none)"):
        return None
    if "#" not in text:
        return "no '#' separating path and locator"
    path, locator = text.split("#", 1)
    if not path or any(ch.isspace() for ch in path):
        return "path is empty or contains whitespace"
    if path.startswith(("/", "\\")) or "\\" in path or "//" in path:
        return "path is not a relative POSIX path"
    if any(part in ("", ".", "..") for part in path.split("/")):
        return "path has empty/./.. segments"
    if not _LOCATOR_RE.match(locator):
        return "locator %r not in L12|L12-L18|p3|table:col|fig:1" % locator
    return None


def _locator_parts(value):
    """Split a ``data-prov`` into (path, locator) tolerantly."""
    text = str(value or "")
    if "#" in text:
        path, locator = text.split("#", 1)
        return path, locator
    return text, ""


def _provenance_records(root):
    """Structured per-element provenance verdicts.

    Shape (shared with layout-render's ``prov_form_scan.py`` so both sides can be
    diffed element-by-element)::

        {"element_id", "data_prov", "path", "locator", "src_kind",
         "problem": None|str, "severity": None|"error"|"warn"}

    ``severity`` is error only for ``src_kind="explicit"`` (an "it is in the
    quoted source" claim that cannot be resolved), warn for derived/unsupported
    placeholders.
    """
    records = []
    for el in _iter_all(root):
        value = _attr(el, "data-prov")
        if value is None:
            continue
        kind = str(_attr(el, "data-src-kind") or "unknown")
        problem = _locator_problem(str(value))
        path, locator = _locator_parts(value)
        records.append({
            "element_id": str(_attr(el, "id") or _strip_ns(el.tag)),
            "data_prov": str(value), "path": path, "locator": locator,
            "src_kind": kind, "problem": problem,
            "severity": (None if not problem
                         else ("error" if kind == "explicit" else "warn")),
        })
    return records


def locator_form_report(source):
    """Validate every ``data-prov`` in an SVG **path or text**.

    Helper (not part of the frozen CONTRACT 4.6 API) so a renderer-side scan can
    diff verdicts per element against this gate::

        {"checked": int, "src_kind_histogram": {...}, "nonconformant": [
            {"element_id", "data_prov", "path", "locator", "src_kind",
             "problem", "severity"}, ...], "ok": bool}

    ``ok`` is False when any ``severity == "error"`` record exists.
    """
    if isinstance(source, (str, os.PathLike)) and os.path.isfile(str(source)):
        root, err = _parse_svg(str(source))
        if err:
            return {"checked": 0, "src_kind_histogram": {}, "nonconformant": [],
                    "error": err, "ok": False}
    elif isinstance(source, (str, bytes)):
        raw = source.encode("utf-8") if isinstance(source, str) else source
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            return {"checked": 0, "src_kind_histogram": {}, "nonconformant": [],
                    "error": str(exc), "ok": False}
    else:
        root = source
    records = _provenance_records(root)
    histogram = {}
    for record in records:
        histogram[record["src_kind"]] = histogram.get(record["src_kind"], 0) + 1
    bad = [record for record in records if record["problem"]]
    return {"checked": len(records), "src_kind_histogram": histogram,
            "nonconformant": bad,
            "ok": not any(record["severity"] == "error" for record in bad)}


def _check_svg_provenance(svg_entries, model, channels):
    if not svg_entries:
        return _missing_check("svg_provenance", "SVG", channels, ["svg"])
    expected = _provenance_expectation(model)
    evidence = {}
    all_ok = True
    problems = []
    advisory = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            all_ok = False
            evidence[entry["name"]] = {"error": err}
            problems.append("%s: %s" % (entry["name"], err))
            continue
        prov = 0
        kinds = {}
        unsupported = 0
        records = _provenance_records(root)
        format_errors = []
        format_advisories = []
        for record in records:
            prov += 1
            kinds[record["src_kind"]] = kinds.get(record["src_kind"], 0) + 1
            if not record["data_prov"].strip() and record["src_kind"] != "unsupported":
                unsupported += 1
            if record["problem"]:
                if record["severity"] == "error":
                    # "explicit" claims the element IS in the quoted source: a
                    # malformed path/locator makes that claim unverifiable.
                    format_errors.append(record)
                else:
                    format_advisories.append(record)
        # Count of addressable elements: id="ent:*|rel:*|lg:*|cnt:*"
        addressable = 0
        for el in _iter_all(root):
            ident = str(_attr(el, "id") or "")
            if ident.startswith(("ent:", "rel:", "lg:", "cnt:")):
                addressable += 1
        evidence[entry["name"]] = {
            "data_prov_count": prov, "addressable_elements": addressable,
            "src_kinds": kinds, "expected_from_model": expected,
            "missing_id_prefixes": unsupported,
            "locator_format_errors": format_errors[:20],
            "locator_format_advisories": format_advisories[:20],
            "provenance_records_checked": len(records),
        }
        if format_errors:
            all_ok = False
            problems.append("%s: %d data-prov locator(s) outside the frozen CONTRACT "
                            "set with data-src-kind=explicit: %s"
                            % (entry["name"], len(format_errors),
                               "; ".join("%s (%s) -> %s" % (r["element_id"], r["data_prov"],
                                                            r["problem"])
                                         for r in format_errors[:3])))
        if format_advisories:
            advisory.append("%s: %d data-prov locator(s) outside the frozen set "
                            "(src-kind=%s): %s"
                            % (entry["name"], len(format_advisories),
                               ",".join(sorted({r["src_kind"] for r in format_advisories})),
                               "; ".join("%s (%s) -> %s" % (r["element_id"], r["data_prov"],
                                                            r["problem"])
                                         for r in format_advisories[:3])))
        if expected and prov < expected:
            all_ok = False
            problems.append("%s: %d data-prov attributes < %d model elements"
                            % (entry["name"], prov, expected))
        elif not expected and prov < 1:
            all_ok = False
            problems.append("%s: no data-prov provenance attributes" % entry["name"])
        if expected and addressable < expected:
            # Data-prov is the hard requirement; traceable ids are role-specific
            # (a chart figure addresses series:, not ent:), so this is advisory.
            advisory.append("%s: %d ent:/rel:/lg:/cnt: ids for %d model elements "
                            "(chart figures legitimately address series: instead)"
                            % (entry["name"], addressable, expected))
    notes = problems + advisory
    level = "error" if problems else ("warn" if advisory else "error")
    detail = "; ".join(notes) if notes else "provenance attributes: %s" % ", ".join(
        "%s=%d (expected>=%d)" % (n, e.get("data_prov_count", 0), e.get("expected_from_model", 0))
        for n, e in evidence.items())
    return _check("svg_provenance", level, all_ok, detail, evidence)


def _check_raster_dpi(raster_entries, channels, model, drawn):
    if not raster_entries:
        return _missing_check("raster_dpi", "raster (PNG/TIFF)", channels, ["png", "tiff"])
    # Measure against the size the figure was DRAWN at, not the requested canvas.
    width_mm = drawn["width_mm"]
    height_mm = drawn.get("height_mm")
    required = channels["dpi"]
    evidence = {}
    all_ok = True
    warnings = []
    problems = []
    for entry in raster_entries:
        path = entry["path"]
        if not os.path.isfile(path):
            all_ok = False
            evidence[entry["name"]] = {"error": "file does not exist"}
            problems.append("%s: missing file" % entry["name"])
            continue
        im, err = _open_image(path)
        if err:
            all_ok = False
            evidence[entry["name"]] = {"error": err}
            problems.append("%s: %s" % (entry["name"], err))
            continue
        try:
            dpi_x, dpi_y, source = _dpi_from_image(im)
            px_w, px_h = im.size
            mode = im.mode
        finally:
            im.close()
        needed_px = int(common.mm_to_px(width_mm, required))
        # PNG pHYs / TIFF XResolution store pixels-per-metre and are quantised:
        # 300 dpi round-trips as 11811 px/m == 299.9994 dpi.  Allow that rounding,
        # which is ~0.002% -- far below any real under-resolution.
        dpi_tolerance = max(0.1, required * 0.001)
        info = {"pixel_size": [px_w, px_h], "dpi_metadata": [dpi_x, dpi_y],
                "dpi_source": source, "required_dpi": required,
                "dpi_tolerance": round(dpi_tolerance, 4),
                "required_px_width": needed_px, "mode": mode}
        evidence[entry["name"]] = info
        if dpi_x is None:
            # No metadata: only provable via pixel count; that is a warning, not a pass.
            if px_w >= needed_px:
                warnings.append("%s: no DPI metadata; pixel width %d meets %d px for %d dpi "
                                "but the physical resolution is undeclared" %
                                (entry["name"], px_w, needed_px, required))
            else:
                all_ok = False
                problems.append("%s: no DPI metadata and pixel width %d < %d px required for "
                                "%d dpi at %.1f mm" %
                                (entry["name"], px_w, needed_px, required, width_mm))
            continue
        if min(dpi_x, dpi_y) + dpi_tolerance < required:
            all_ok = False
            problems.append("%s: declared %gx%g dpi < required %d dpi (tolerance %g)"
                            % (entry["name"], dpi_x, dpi_y, required, dpi_tolerance))
        if height_mm:
            physical_w = px_w / dpi_x * MM_PER_INCH
            physical_h = px_h / dpi_y * MM_PER_INCH
            info["physical_size_mm"] = [round(physical_w, 2), round(physical_h, 2)]
            tol_w = max(0.5, width_mm * 0.03)
            tol_h = max(0.5, height_mm * 0.03)
            if abs(physical_w - width_mm) > tol_w or abs(physical_h - height_mm) > tol_h:
                all_ok = False
                problems.append("%s: %gx%g px at %g dpi = %.1fx%.1f mm, canvas is %.1fx%.1f mm"
                                % (entry["name"], px_w, px_h, dpi_x, physical_w, physical_h,
                                   width_mm, height_mm))
    drift = _canvas_drift_note(model, drawn, channels)
    if drift:
        warnings.extend(drift)
        for info in evidence.values():
            if isinstance(info, dict):
                info["canvas_drift"] = drift
    notes = problems + warnings
    detail = "; ".join(notes) if notes else (
        "; ".join("%s: %sx%s px @ %s dpi (%s)" %
                  (n, e.get("pixel_size", ["?"])[0], e.get("pixel_size", ["?", "?"])[1],
                   e.get("dpi_metadata", ["?"])[0], e.get("dpi_source"))
                  for n, e in evidence.items()))
    if all_ok and not problems:
        detail += " [drawn at %.1f mm from %s]" % (width_mm, drawn.get("source"))
    level = "warn" if (all_ok and warnings) else "error"
    return _check("raster_dpi", level, all_ok, detail, evidence)


def _check_raster_opens(raster_entries, channels):
    if not raster_entries:
        return _missing_check("raster_opens", "raster (PNG/TIFF)", channels, ["png", "tiff"])
    evidence = {}
    all_ok = True
    problems = []
    for entry in raster_entries:
        path = entry["path"]
        if not os.path.isfile(path):
            all_ok = False
            evidence[entry["name"]] = {"error": "file does not exist"}
            problems.append("%s: missing file" % entry["name"])
            continue
        im, err = _open_image(path)
        if err:
            all_ok = False
            evidence[entry["name"]] = {"error": err, "bytes": os.path.getsize(path)}
            problems.append("%s: %s" % (entry["name"], err))
            continue
        try:
            evidence[entry["name"]] = {"format": im.format, "mode": im.mode,
                                       "size": list(im.size), "bytes": os.path.getsize(path)}
        finally:
            im.close()
    detail = "; ".join(problems) if problems else "Pillow verify()+load() OK: %s" % ", ".join(
        "%s(%s %s)" % (n, e.get("format"), e.get("mode")) for n, e in evidence.items())
    return _check("raster_opens", "error", all_ok, detail, evidence)


def _check_pdf_opens(pdf_entries, channels):
    if not pdf_entries:
        return _missing_check("pdf_opens", "PDF", channels, ["pdf"])
    evidence = {}
    all_ok = True
    problems = []
    for entry in pdf_entries:
        path = entry["path"]
        if not os.path.isfile(path):
            all_ok = False
            evidence[entry["name"]] = {"error": "file does not exist"}
            problems.append("%s: missing file" % entry["name"])
            continue
        reader, err, npages = _pdf_reader(path)
        if err:
            all_ok = False
            evidence[entry["name"]] = {"error": err, "bytes": os.path.getsize(path)}
            problems.append("%s: %s" % (entry["name"], err))
            continue
        try:
            encrypted = bool(reader.is_encrypted)
        except Exception:  # noqa: BLE001
            encrypted = False
        evidence[entry["name"]] = {"pages": npages, "bytes": os.path.getsize(path),
                                   "encrypted": encrypted}
        if not npages:
            all_ok = False
            problems.append("%s: 0 pages" % entry["name"])
        if encrypted:
            all_ok = False
            problems.append("%s: PDF is encrypted" % entry["name"])
    detail = "; ".join(problems) if problems else "pypdf opened: %s" % ", ".join(
        "%s(%s pages, %s bytes)" % (n, e.get("pages"), e.get("bytes")) for n, e in evidence.items())
    return _check("pdf_opens", "error", all_ok, detail, evidence)


def _check_pdf_fonts(pdf_entries, channels):
    if not pdf_entries:
        return _missing_check("pdf_fonts_embedded", "PDF", channels, ["pdf"])
    evidence = {}
    all_ok = True
    problems = []
    skipped = []
    for entry in pdf_entries:
        path = entry["path"]
        if not os.path.isfile(path):
            all_ok = False
            evidence[entry["name"]] = {"error": "file does not exist"}
            problems.append("%s: missing file" % entry["name"])
            continue
        reader, err, _npages = _pdf_reader(path)
        if err:
            skipped.append(entry["name"])
            evidence[entry["name"]] = {"skipped": True, "reason": err}
            continue
        try:
            fonts = _pdf_fonts(reader)
        except Exception as exc:  # noqa: BLE001
            skipped.append(entry["name"])
            evidence[entry["name"]] = {"skipped": True,
                                       "reason": "resource walk failed: %s" % exc}
            continue
        report = [_font_report(fdict) for _name, fdict in fonts]
        missing = [f for f in report if not f["embedded"]]
        evidence[entry["name"]] = {"font_count": len(report), "fonts": report,
                                   "not_embedded": [f["name"] for f in missing]}
        if not report:
            all_ok = False
            problems.append("%s: no fonts in /Resources /Font (text cannot be editable)"
                            % entry["name"])
        elif missing:
            all_ok = False
            problems.append("%s: %d/%d fonts without FontFile/FontFile2/FontFile3: %s"
                            % (entry["name"], len(missing), len(report),
                               ", ".join(f["name"] for f in missing[:6])))
    if skipped and not problems:
        return _check("pdf_fonts_embedded", "error", False,
                      "skipped: PDF could not be parsed (%s)" % "; ".join(skipped),
                      evidence)
    if skipped:
        problems.append("skipped for unparseable PDF(s): %s" % ", ".join(skipped))
        all_ok = False
    detail = "; ".join(problems) if problems else "all fonts embedded: %s" % ", ".join(
        "%s(%d fonts)" % (n, e.get("font_count", 0)) for n, e in evidence.items())
    return _check("pdf_fonts_embedded", "error", all_ok, detail, evidence)


def _normalise_for_match(text):
    return re.sub(r"[\s\u00a0\u200b\ufeff]+", "", str(text or "")).lower()



def _expected_labels(model, svg_texts=None):
    """Labels the produced PDF must keep as real, extractable text.

    When the editable master is available, only labels it actually **draws** are
    required: a ``kind=chart`` figure deliberately draws no entity boxes, so
    entity labels that never appear in the SVG must not be demanded of the PDF
    (otherwise ingest's draft word-salad entities would look like an export
    defect).  Without an SVG the model drives the expectation as before.
    """
    if not isinstance(model, dict):
        return []
    labels = []
    for key in ("entities", "relations", "legend", "containers"):
        for item in model.get(key) or []:
            if isinstance(item, dict) and item.get("label"):
                labels.append(str(item["label"]))
    for series in ((model.get("data") or {}).get("series") or []):
        if isinstance(series, dict) and series.get("name"):
            labels.append(str(series["name"]))
    legend_values = [str(leg.get("value")) for leg in (model.get("legend") or [])
                     if isinstance(leg, dict) and leg.get("value") not in (None, "")]
    labels.extend(legend_values)
    for column in (model.get("data") or {}).get("columns") or []:
        labels.append(str(column))
    for unit in ((model.get("data") or {}).get("units") or {}).values():
        if unit:
            labels.append(str(unit))
    title = ((model.get("figure") or {}).get("title") or {}).get("text")
    if title:
        labels.append(str(title))
    seen, ordered = set(), []
    for label in labels:
        key = _normalise_for_match(label)
        if len(key) < 2 or key in seen:
            continue
        seen.add(key)
        ordered.append(label)
    if svg_texts:
        svg_norm = _normalise_for_match(" ".join(svg_texts))
        drawn = [label for label in ordered if _normalise_for_match(label) in svg_norm]
        # Never let a master with no matching text make the PDF check vacuous:
        # fall back to the model-derived expectation when nothing lines up.
        if drawn:
            return drawn
    return ordered


def _svg_text_samples(svg_entries):
    """Every drawn string in the master SVG (used to know what the PDF owes)."""
    texts = []
    for entry in svg_entries or []:
        path = entry.get("path")
        if not path or not os.path.isfile(path):
            continue
        root, err = _parse_svg(path)
        if err:
            continue
        for el in _iter_all(root):
            if _strip_ns(el.tag) == "text":
                content = _text_content(el)
                if content:
                    texts.append(content)
    return texts


def _check_pdf_text(pdf_entries, model, channels, svg_entries=None):
    if not pdf_entries:
        return _missing_check("pdf_text_extractable", "PDF", channels, ["pdf"])
    svg_texts = _svg_text_samples(svg_entries)
    labels = _expected_labels(model, svg_texts)
    evidence = {}
    fatal = []
    advisory = []
    skipped = []
    for entry in pdf_entries:
        path = entry["path"]
        if not os.path.isfile(path):
            fatal.append("%s: missing file" % entry["name"])
            evidence[entry["name"]] = {"error": "file does not exist"}
            continue
        reader, err, _npages = _pdf_reader(path)
        if err:
            skipped.append(entry["name"])
            evidence[entry["name"]] = {"skipped": True, "reason": err}
            continue
        try:
            pages = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception as exc:  # noqa: BLE001
                    pages.append("")
                    evidence.setdefault(entry["name"], {})["page_error"] = str(exc)
            text = "\n".join(pages)
        except Exception as exc:  # noqa: BLE001
            skipped.append(entry["name"])
            evidence[entry["name"]] = {"skipped": True,
                                       "reason": "text extraction failed: %s" % exc}
            continue
        norm = _normalise_for_match(text)
        found = [label for label in labels if _normalise_for_match(label) in norm]
        missing = [label for label in labels if label not in found]
        info = {"extracted_chars": len(text), "expected_labels": len(labels),
                "found_count": len(found), "missing_count": len(missing),
                "found": found[:20], "missing": missing[:20],
                "sample": re.sub(r"\s+", " ", text)[:300]}
        evidence[entry["name"]] = info
        if labels:
            if not found:
                fatal.append("%s: extract_text() contains none of the %d model labels"
                             % (entry["name"], len(labels)))
            elif len(found) < len(labels):
                advisory.append("%s: only %d/%d labels the master draws are extractable "
                                "(missing: %s)"
                                % (entry["name"], len(found), len(labels),
                                   ", ".join(missing[:6])))
        elif len(norm) < 3:
            fatal.append("%s: extract_text() returned no text "
                         "(no model supplied for label comparison)" % entry["name"])
    if skipped:
        fatal.append("skipped for unparseable PDF(s): %s" % ", ".join(skipped))
    problems = fatal + advisory
    if problems:
        return _check("pdf_text_extractable", "error" if fatal else "warn",
                      not fatal, "; ".join(problems), evidence)
    detail = "labels the master draws are extractable: %s" % ", ".join(
        "%s(%s/%s)" % (n, e.get("found_count"), e.get("expected_labels") or 0)
        for n, e in evidence.items())
    return _check("pdf_text_extractable", "error", True, detail, evidence)


def _check_line_width(svg_entries, channels):
    if not svg_entries:
        return _missing_check("line_width_min", "SVG", channels, ["svg"])
    required = channels["min_line_width_pt"]
    evidence = {}
    all_ok = True
    problems = []
    advisory = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            all_ok = False
            evidence[entry["name"]] = {"error": err}
            problems.append("%s: %s" % (entry["name"], err))
            continue
        metadata = _svg_metadata(root)
        width_mm, _height_mm = _svg_canvas_mm(root, metadata)
        viewbox = _attr(root, "viewBox") or _attr(root, "viewbox")
        vb_w = vb_h = None
        if viewbox:
            try:
                parts = [float(x) for x in re.split(r"[\s,]+", viewbox.strip()) if x]
                if len(parts) == 4:
                    vb_w, vb_h = parts[2], parts[3]
            except ValueError:
                vb_w = vb_h = None
        if not width_mm and metadata:
            canvas = metadata.get("canvas") or {}
            try:
                width_mm = float(canvas.get("width_mm") or 0) or None
            except (TypeError, ValueError):
                width_mm = None
        if width_mm and vb_w:
            mm_per_user = width_mm / vb_w
            scale_basis = "width %s / viewBox %s" % (width_mm, vb_w)
        elif width_mm and not vb_w:
            mm_per_user = MM_PER_INCH / 96.0
            scale_basis = "no viewBox: 1 user unit = 1 CSS px"
        else:
            mm_per_user = None
            scale_basis = "unknown canvas scale (no width/viewBox/metadata)"
        scales = _ancestor_scale_map(root)
        widths = []
        for el in _iter_all(root):
            if _strip_ns(el.tag) not in ("path", "line", "polyline", "polygon", "rect",
                                         "circle", "ellipse"):
                continue
            stroke = _attr(el, "stroke")
            if stroke in (None, "none"):
                continue
            if mm_per_user is None:
                continue
            pt = _stroke_width_pt(el, mm_per_user, scales.get(el, 1.0))
            if pt is None or pt <= 0:
                continue
            widths.append((round(pt, 4), _attr(el, "id") or _strip_ns(el.tag)))
        if mm_per_user is None:
            advisory.append("%s: cannot convert stroke-width to pt: %s"
                            % (entry["name"], scale_basis))
            evidence[entry["name"]] = {"error": scale_basis, "applicable": False}
            continue
        evidence[entry["name"]] = {
            "scale_basis": scale_basis, "stroked_elements": len(widths),
            "min_pt": min((w for w, _ in widths), default=None),
            "min_element": min(widths, default=(None, None))[1],
            "required_pt": required,
            "thin_examples": sorted(widths)[:5],
        }
        if not widths:
            advisory.append("%s: no stroked elements found to measure "
                            "(journal line-width rule is vacuous here)" % entry["name"])
            continue
        thin = [(w, el) for w, el in widths if w + 1e-9 < required]
        if thin:
            all_ok = False
            problems.append("%s: %d element(s) below %.2f pt (min %.3f pt on %s)"
                            % (entry["name"], len(thin), required, thin[0][0], thin[0][1]))
    notes = problems + advisory
    level = "error" if problems else ("warn" if advisory else "error")
    detail = "; ".join(notes) if notes else "min stroke width OK: %s" % ", ".join(
        "%s: min %s pt (required %s pt)" % (n, e.get("min_pt"), e.get("required_pt"))
        for n, e in evidence.items())
    return _check("line_width_min", level, all_ok, detail, evidence)


def _check_color_space(entries, channels):
    required = channels["color_space"]
    evidence = {}
    fatal = []
    advisory = []
    for entry in entries:
        fmt = entry.get("format")
        path = entry["path"]
        if not os.path.isfile(path):
            fatal.append("%s: missing file" % entry["name"])
            evidence[entry["name"]] = {"error": "file does not exist"}
            continue
        observed = None
        info = {}
        if fmt == "svg":
            root, err = _parse_svg(path)
            if err:
                fatal.append("%s: %s" % (entry["name"], err))
                evidence[entry["name"]] = {"error": err}
                continue
            metadata = _svg_metadata(root)
            declared = None
            if isinstance(metadata, dict):
                declared = ((metadata.get("figure") or {}).get("style") or {}).get("color_space") \
                    or ((metadata.get("style") or {}).get("color_space"))
                if not declared:
                    declared = metadata.get("color_space")
            raw = _read_bytes(path).decode("utf-8", "replace")
            has_srgb = "sRGB" in raw or "srgb" in raw
            observed = str(declared or ("sRGB" if has_srgb else "")).upper() or None
            info = {"declared": declared, "sRGB_marker": has_srgb}
        elif fmt in ("png", "tiff"):
            im, err = _open_image(path)
            if err:
                fatal.append("%s: %s" % (entry["name"], err))
                evidence[entry["name"]] = {"error": err}
                continue
            try:
                observed = {"RGB": "RGB", "RGBA": "RGB", "P": "RGB", "L": "GRAY",
                            "CMYK": "CMYK"}.get(im.mode, im.mode)
                info = {"mode": im.mode, "icc_profile": bool(im.info.get("icc_profile"))}
            finally:
                im.close()
        elif fmt == "pdf":
            raw = _read_bytes(path)
            markers = []
            if b"/DeviceCMYK" in raw:
                markers.append("DeviceCMYK")
            if b"/DeviceRGB" in raw:
                markers.append("DeviceRGB")
            if b"/ICCBased" in raw:
                markers.append("ICCBased")
            reader, _err, _npages = _pdf_reader(path)
            operators, spaces = ([], [])
            if reader is not None:
                operators, spaces = _pdf_colour_streams(reader)
            observed = None
            if "DeviceCMYK" in markers or "DeviceCMYK" in spaces or \
                    any(op in operators for op in ("k", "K")):
                observed = "CMYK"
            elif "DeviceRGB" in markers or "DeviceRGB" in spaces or \
                    any(op in operators for op in ("rg", "RG")):
                observed = "RGB"
            elif "ICCBased" in markers or "ICCBased" in spaces:
                observed = "ICCBased"
            elif any(op in operators for op in ("g", "G")):
                observed = "GRAY"
            info = {"markers": markers, "content_operators": operators,
                    "content_colour_spaces": spaces}
        elif fmt == "eps":
            raw = _read_bytes(path)
            markers = []
            if b"setcmykcolor" in raw:
                markers.append("setcmykcolor")
            if b"setrgbcolor" in raw:
                markers.append("setrgbcolor")
            observed = "CMYK" if "setcmykcolor" in markers else (
                "RGB" if "setrgbcolor" in markers else None)
            info = {"markers": markers}
        info["observed"] = observed
        evidence[entry["name"]] = info
        if observed is None:
            if required == "CMYK":
                fatal.append("%s: no colour-space declaration found but CMYK is required"
                             % entry["name"])
            else:
                advisory.append("%s: no explicit colour-space declaration (advisory)"
                                % entry["name"])
            continue
        compatible = (observed.upper().startswith(required[:3])
                      or (required == "RGB" and observed.upper() in ("SRGB", "RGBA", "ICCBASED")))
        if not compatible:
            if required == "CMYK":
                fatal.append("%s: colour space %s, journal requires CMYK"
                             % (entry["name"], observed))
            else:
                advisory.append("%s: colour space %s while spec asks %s"
                                % (entry["name"], observed, required))
    problems = fatal + advisory
    level = "error" if fatal else ("warn" if advisory else "error")
    detail = "; ".join(problems) if problems else "colour space %s declared in: %s" % (
        required, ", ".join("%s=%s" % (n, e.get("observed")) for n, e in evidence.items()))
    return _check("color_space_declared", level, not fatal, detail, evidence)


def _check_nonempty(entries, channels):
    if not entries:
        return _missing_check("artifact_nonempty", "artifact", channels,
                              ["svg", "pdf", "png", "tiff", "eps"])
    evidence = {}
    all_ok = True
    problems = []
    for entry in entries:
        path = entry["path"]
        fmt = entry.get("format") or ""
        if not os.path.isfile(path):
            all_ok = False
            evidence[entry["name"]] = {"error": "file does not exist"}
            problems.append("%s: missing file" % entry["name"])
            continue
        size = os.path.getsize(path)
        try:
            head = _read_bytes(path)[:64]
        except OSError as exc:
            all_ok = False
            evidence[entry["name"]] = {"error": str(exc)}
            problems.append("%s: unreadable" % entry["name"])
            continue
        magic_ok = None
        if fmt in MAGIC:
            magic_ok = any(head.startswith(sig) for sig in MAGIC[fmt])
        elif fmt == "svg":
            text = head.decode("utf-8", "replace")
            magic_ok = "<svg" in text or text.lstrip().startswith("<?xml")
        evidence[entry["name"]] = {"bytes": size, "format": fmt,
                                   "magic_ok": magic_ok, "head": head[:16].decode("latin-1")}
        if size <= 0:
            all_ok = False
            problems.append("%s: 0 bytes" % entry["name"])
        elif magic_ok is False:
            all_ok = False
            problems.append("%s: magic bytes do not match .%s (renamed file?)"
                            % (entry["name"], fmt))
    detail = "; ".join(problems) if problems else "all artifacts non-empty with matching magic: %s" % \
        ", ".join("%s=%dB" % (n, e.get("bytes")) for n, e in evidence.items())
    return _check("artifact_nonempty", "error", all_ok, detail, evidence)


def _pdf_colour_streams(reader):
    """Scan decompressed page content streams for colour spaces and operators.

    matplotlib PDFs carry no uncompressed ``/DeviceRGB`` resource entry: the
    colour space appears as ``/DeviceRGB cs`` plus ``rg``/``RG`` (or ``k``/``K``)
    operators inside Flate-compressed content streams.  Numeric operands are
    required in front of each operator so text-showing strings cannot produce
    false positives.
    """
    operators, spaces = set(), set()
    try:
        for page in reader.pages:
            contents = page.get_contents()
            datas = []
            if contents is None:
                continue
            if hasattr(contents, "get_data"):
                datas.append(contents.get_data() or b"")
            else:
                for item in contents:
                    getter = getattr(item, "get_data", None)
                    if getter:
                        datas.append(getter() or b"")
            for data in datas:
                text = data.decode("latin-1", "replace")
                stripped = re.sub(r"\([^)]*\)", "()", text)
                stripped = re.sub(r"<[0-9A-Fa-f\s]*>", "<>", stripped)
                for op in re.findall(r"(?:[-\d.]+\s+){1,4}(rg|RG|k|K)(?![A-Za-z])", stripped):
                    operators.add(op)
                for op in re.findall(r"(?:[-\d.]+\s+){1,2}(g|G)(?![A-Za-z])", stripped):
                    operators.add(op)
                for space in re.findall(r"/(DeviceRGB|DeviceCMYK|ICCBased|Separation|Pattern)",
                                        text):
                    spaces.add(space)
    except Exception:  # noqa: BLE001 - best-effort evidence, never fatal here
        return sorted(operators), sorted(spaces)
    return sorted(operators), sorted(spaces)


def _check_pdf_size(pdf_entries, channels, model, drawn):
    """PDF media box must match the size the figure was drawn at."""
    if not pdf_entries:
        return _missing_check("pdf_page_size", "PDF", channels, ["pdf"])
    width_mm = drawn["width_mm"]
    height_mm = drawn.get("height_mm")
    evidence = {}
    fatal = []
    advisory = list(_canvas_drift_note(model, drawn, channels))
    for entry in pdf_entries:
        path = entry["path"]
        if not os.path.isfile(path):
            fatal.append("%s: missing file" % entry["name"])
            evidence[entry["name"]] = {"error": "file does not exist"}
            continue
        reader, err, _npages = _pdf_reader(path)
        if err:
            fatal.append("%s: skipped (%s)" % (entry["name"], err))
            evidence[entry["name"]] = {"skipped": True, "reason": err}
            continue
        try:
            box = reader.pages[0].mediabox
            page_w = float(box.width) * MM_PER_INCH / PT_PER_INCH
            page_h = float(box.height) * MM_PER_INCH / PT_PER_INCH
        except Exception as exc:  # noqa: BLE001
            fatal.append("%s: cannot read /MediaBox (%s)" % (entry["name"], exc))
            continue
        info = {"page_mm": [round(page_w, 2), round(page_h, 2)],
                "canvas_mm": [width_mm, height_mm], "canvas_source": drawn.get("source")}
        evidence[entry["name"]] = info
        tol = max(1.0, width_mm * 0.03)
        if abs(page_w - width_mm) > tol:
            fatal.append("%s: page width %.1f mm != canvas %.1f mm (tolerance %.1f mm)"
                         % (entry["name"], page_w, width_mm, tol))
        if height_mm and abs(page_h - height_mm) > max(1.0, height_mm * 0.03):
            fatal.append("%s: page height %.1f mm != canvas %.1f mm"
                         % (entry["name"], page_h, height_mm))
        if height_mm and height_mm > channels["max_height_mm"]:
            fatal.append("%s: %.1f mm tall, journal maximum is %.1f mm"
                         % (entry["name"], height_mm, channels["max_height_mm"]))
        widest = float(channels.get("width_double_mm") or channels["width_mm"])
        single = float(channels["width_mm"])
        if width_mm > widest + 1.0:
            advisory.append("%s: %.1f mm wide, the journal's widest column is %.1f mm"
                            % (entry["name"], width_mm, widest))
        elif width_mm > single + 1.0:
            info["column_fit"] = ("double column (%.1f mm; single is %.1f mm)"
                                  % (widest, single))
    problems = fatal + advisory
    if problems:
        return _check("pdf_page_size", "error" if fatal else "warn", not fatal,
                      "; ".join(problems), evidence)
    return _check("pdf_page_size", "error", True, "PDF page size matches the canvas: %s" % ", ".join(
        "%s(%s mm)" % (n, e.get("page_mm")) for n, e in evidence.items()), evidence)


def _check_eps_fonts(eps_entries, channels):
    if not eps_entries:
        return _missing_check("eps_fonts_embedded", "EPS", channels, ["eps"], optional=True)
    evidence = {}
    all_ok = True
    problems = []
    for entry in eps_entries:
        raw = _read_bytes(entry["path"]).decode("latin-1")
        begin_font = len(re.findall(r"%%Begin(?:Resource:\s*font|Font)", raw))
        inline_truetype = len(re.findall(r"%%!PS-TrueTypeFont", raw))
        fontfile = len(re.findall(r"/FontFile\d?\b", raw))
        font_types = sorted(set(re.findall(r"/FontType\s+(\d+)", raw)))
        font_names = sorted(set(re.findall(r"/FontName\s*/([A-Za-z0-9+._-]+)", raw)))[:10]
        embedded = bool(begin_font or inline_truetype or fontfile)
        evidence[entry["name"]] = {"begin_font_blocks": begin_font,
                                   "inline_truetype_fonts": inline_truetype,
                                   "fontfile_refs": fontfile,
                                   "font_types": font_types,
                                   "fonttype42": "42" in font_types,
                                   "font_names": font_names}
        if not embedded:
            all_ok = False
            problems.append("%s: no embedded font program (%%!PS-TrueTypeFont / "
                            "%%BeginFont / /FontFile); referenced fonts: %s"
                            % (entry["name"], ", ".join(font_names) or "unknown"))
    detail = "; ".join(problems) if problems else "EPS fonts embedded: %s" % ", ".join(
        "%s(%d inline TrueType, fonttypes %s)" % (n, e["inline_truetype_fonts"],
                                                  ",".join(e["font_types"]))
        for n, e in evidence.items())
    level = "error" if channels["font_embedding_required"] else "warn"
    return _check("eps_fonts_embedded", level, all_ok, detail, evidence)


CORE_FORMATS = ("svg", "pdf", "png")


def _svg_entity_colours(root):
    """entity id -> (fill, stroke), read from the ``<g id="ent:ID">`` rects."""
    out = {}
    for el in _iter_all(root):
        ident = str(_attr(el, "id") or "")
        if not ident.startswith("ent:"):
            continue
        for child in el.iter():
            if _strip_ns(child.tag) != "rect":
                continue
            fill = _attr(child, "fill")
            if fill and str(fill).lower() not in ("none", "#ffffff"):
                out[ident[4:]] = (str(fill).upper(),
                                  str(_attr(child, "stroke") or "").upper())
                break
    return out


def _attr_ci(el, *names):
    """Case-tolerant attribute lookup (renderers emit data-* or dataX variants)."""
    for name in names:
        value = _attr(el, name)
        if value is not None:
            return value
    lowered = {_strip_ns(k).lower(): v for k, v in el.attrib.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _svg_series_links(root):
    """``<g id="series:N">`` -> declared colour and its legend/entity linkage.

    Chart figures have no ``ent:`` boxes; the renderer links each data series to
    the legend entry (and optionally the entity) it was coloured from, which is
    the machine-discoverable form of the legend<->colour mapping.
    """
    out = []
    for el in _iter_all(root):
        ident = str(_attr(el, "id") or "")
        if not ident.startswith("series:"):
            continue
        color = _attr_ci(el, "data-color", "data-colour")
        out.append({"id": ident,
                    "color": str(color).upper() if color else None,
                    "legend": _attr_ci(el, "data-legend", "data-legend-id"),
                    "entity": _attr_ci(el, "data-entity", "data-entity-id"),
                    "name": _attr_ci(el, "data-name")})
    return out


def _svg_relation_colours(root):
    """relation type -> stroke colour, from ``<g id="rel:ID" data-rel-type=...>``.

    ``line_style`` legend entries name a relation type rather than an entity, so
    their swatch must be matched against the edges actually drawn.
    """
    out = {}
    for el in _iter_all(root):
        ident = str(_attr(el, "id") or "")
        if not ident.startswith("rel:"):
            continue
        rel_type = _attr_ci(el, "data-rel-type")
        if not rel_type:
            continue
        for child in el.iter():
            for attr in ("stroke", "fill"):
                value = _attr(child, attr)
                if value and str(value).upper() not in ("NONE", "#FFFFFF"):
                    out.setdefault(str(rel_type), str(value).upper())
                    break
            if str(rel_type) in out:
                break
    return out


def _check_svg_legend_colors(svg_entries, model, channels):
    """Advisory: every coloured legend item must map to a colour really drawn.

    Resolution order per legend item (first match wins):
      1. a ``series:N`` group declaring ``data-legend="<item id>"`` (chart figures);
      2. an ``ent:<id>`` box whose label/value matches the legend ``value``
         (relationship schematics), or a series declaring that ``data-entity``;
      3. an unambiguous unique colour match between the swatch and one series.
    A mapping that cannot be resolved at all is still reported (advisory), so the
    gap stays visible instead of silently passing.
    """
    if not svg_entries:
        return _missing_check("svg_legend_color_map", "SVG", channels, ["svg"])
    legend = (model or {}).get("legend") or []
    entities = (model or {}).get("entities") or []
    if not legend:
        return _check("svg_legend_color_map", "warn", True,
                      "N/A: model declares no legend to cross-check",
                      {"applicable": False})
    evidence = {}
    mismatches = []
    unresolved = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            unresolved.append("%s: %s" % (entry["name"], err))
            evidence[entry["name"]] = {"error": err}
            continue
        entity_colours = _svg_entity_colours(root)
        series_links = _svg_series_links(root)
        relation_colours = _svg_relation_colours(root)
        legend_colours = {}
        for el in _iter_all(root):
            ident = str(_attr(el, "id") or "")
            if not ident.startswith("lg:"):
                continue
            colours = []
            for child in el.iter():
                for attr in ("fill", "stroke"):
                    value = _attr(child, attr)
                    if value and str(value).upper() not in ("#FFFFFF", "#F5F8FB", "NONE"):
                        colours.append(str(value).upper())
            if colours:
                legend_colours[ident[3:]] = colours[0]
        swatch_counts = {}
        for colour in legend_colours.values():
            swatch_counts[colour] = swatch_counts.get(colour, 0) + 1
        pairs = []
        for item in legend:
            if not isinstance(item, dict):
                continue
            value = item.get("value")
            if value in (None, ""):
                continue
            item_id = str(item.get("id"))
            swatch = legend_colours.get(item_id)
            if not swatch:
                continue
            # Collect every drawn colour this legend entry could describe, then
            # accept the pair if ANY declared target carries the swatch colour.
            # (A label can legitimately collide with a relation type name, so a
            # single first-match strategy would produce false mismatches.)
            candidates = []
            for series in series_links:
                if series.get("legend") == item_id and series.get("color"):
                    candidates.append(("series.data-legend", series["id"],
                                       (series["color"], series["color"])))
            rel_colour = relation_colours.get(str(value))
            if rel_colour:
                candidates.append(("rel.data-rel-type", "rel:%s" % value,
                                   (rel_colour, rel_colour)))
            matches = [e for e in entities if isinstance(e, dict)
                       and str(value).lower() in str(e.get("label") or "").lower()]
            for entity in matches[:2]:
                entity_id = str(entity.get("id"))
                colours = entity_colours.get(entity_id) or (None, None)
                if colours[0] or colours[1]:
                    candidates.append(("entity.label", entity_id, colours))
                    continue
                for series in series_links:
                    if series.get("entity") == entity_id and series.get("color"):
                        candidates.append(("series.data-entity", entity_id,
                                           (series["color"], series["color"])))
                        break
            same = [s for s in series_links if s.get("color") == swatch]
            if len(same) == 1 and swatch_counts.get(swatch) == 1:
                candidates.append(("unique series colour", same[0]["id"], (swatch, swatch)))
            if not candidates:
                unresolved.append("%s: legend %s (%s) has no drawn colour to match "
                                  "(no series.data-legend, no relation of that type, no "
                                  "entity box)" % (entry["name"], item_id, value))
                continue
            hit = None
            for candidate in candidates:
                colours = [str(c).upper() for c in candidate[2] if c]
                if swatch in colours:
                    hit = candidate
                    break
            chosen = hit or candidates[0]
            matched = hit is not None
            pairs.append({"legend": item_id, "value": value, "swatch": swatch,
                          "target": chosen[1], "drawn": list(chosen[2]),
                          "via": chosen[0], "match": matched,
                          "candidates": [{"via": c[0], "target": c[1], "drawn": list(c[2])}
                                         for c in candidates]})
            if not matched:
                mismatches.append("%s: legend %s swatch %s but drawn candidates are %s"
                                  % (entry["name"], item_id, swatch,
                                     "; ".join("%s=%s" % (c[1], list(c[2])) for c in candidates)))
        evidence[entry["name"]] = {"pairs": pairs, "checked": len(pairs),
                                   "legend_colours": legend_colours,
                                   "unresolved": unresolved}
    if mismatches or unresolved:
        detail = "; ".join(mismatches + unresolved)[:600]
        if mismatches:
            detail += " (advisory: legend/figure colour mapping belongs to the model gate)"
        return _check("svg_legend_color_map", "warn", not mismatches, detail, evidence)
    total = sum(e.get("checked", 0) for e in evidence.values())
    if total:
        return _check("svg_legend_color_map", "warn", True,
                      "legend swatch colours match the drawn colours: %s"
                      % ", ".join("%s(%d pairs)" % (n, e.get("checked", 0))
                                  for n, e in evidence.items()), evidence)
    swatches = sum(len(e.get("legend_colours") or {}) for e in evidence.values())
    return _check("svg_legend_color_map", "warn", True,
                  ("legend glyph colours present but none could be resolved to a drawn "
                   "colour" if swatches else
                   "N/A: the SVG draws no coloured legend glyph (nothing to cross-check)"),
                  evidence)


def _num_or(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _path_points(d):
    """Parse an SVG path ``d`` into a point list (M/L only, as render_svg emits)."""
    numbers = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", str(d or ""))
    if len(numbers) < 4 or len(numbers) % 2:
        return None
    coords = [float(v) for v in numbers]
    return list(zip(coords[0::2], coords[1::2]))


def _svg_relation_geometry(root):
    """Per ``rel:<id>`` group: declared heads plus the drawn polyline and tips."""
    out = {}
    for el in _iter_all(root):
        ident = str(_attr(el, "id") or "")
        if not ident.startswith("rel:"):
            continue
        polyline = None
        arrow = None
        tee = None
        for child in el.iter():
            if _strip_ns(child.tag) != "path":
                continue
            d = str(_attr(child, "d") or "")
            points = _path_points(d)
            if not points:
                continue
            fill = str(_attr(child, "fill") or "").lower()
            closed = d.strip().upper().endswith("Z")
            if fill == "none" and len(points) >= 2 and not closed:
                if len(points) == 2 and _num_or(_attr(child, "stroke-width"), 0) >= 1.5:
                    tee = points            # short thick bar = tee head
                elif polyline is None or len(points) > len(polyline):
                    polyline = points
            elif closed and len(points) == 3:
                arrow = points              # tip first, per render_svg._head
        out[ident] = {"id": ident,
                      "head_start": _attr_ci(el, "data-head-start"),
                      "head_end": _attr_ci(el, "data-head-end"),
                      "direction": _attr_ci(el, "data-direction"),
                      "rel_type": _attr_ci(el, "data-rel-type"),
                      "polyline": polyline, "arrow": arrow, "tee": tee}
    return out


def _svg_entity_centres(root):
    centres = {}
    for el in _iter_all(root):
        ident = str(_attr(el, "id") or "")
        if not ident.startswith("ent:"):
            continue
        for child in el.iter():
            if _strip_ns(child.tag) != "rect":
                continue
            try:
                centres[ident[4:]] = (float(_attr(child, "x")) + float(_attr(child, "width")) / 2.0,
                                      float(_attr(child, "y")) + float(_attr(child, "height")) / 2.0)
            except (TypeError, ValueError):
                pass
            break
    return centres


def _check_svg_edge_direction(svg_entries, model, channels):
    """A drawn head must sit at the end the model calls the target (error level).

    Direction inversion is the failure mode the challenge names fatal
    ("inhibition drawn as activation, upstream/downstream inverted"), and this is
    the only gate that can see it in the *artifact* rather than in the model: for
    every relation the model marks ``forward``, the arrow/tee tip must be nearer
    the ``to`` node than the ``from`` node.  The redraw consumes the same
    ``head_end`` field, so a passing master implies the PDF/PNG/EPS carry the
    same orientation.  Defence in depth over CONTRACT 5.2 (the structural gate
    owns direction): if a hand-edited SVG or a future renderer change moves a
    head, the export gate refuses to pass it silently.

    Deliberately tolerant of legitimate shapes -- the check only ever compares
    the head at each declared end with that end's node:

    * ``head_end="none"`` / ``head_start="none"`` (association, containment):
      no tip to compare, never a violation;
    * ``direction="bidirectional"``: each end's head is checked against its own
      node, so two heads pass;
    * routed feedback arcs: only the tip's distance to the two node centres
      matters, never the polyline's shape.
    """
    if not svg_entries:
        return _missing_check("svg_edge_direction", "SVG", channels, ["svg"])
    relations = [r for r in ((model or {}).get("relations") or []) if isinstance(r, dict)]
    if not relations:
        kind = str(((model or {}).get("figure") or {}).get("kind") or "")
        return _check("svg_edge_direction", "error", True,
                      "N/A: model declares no relations to orient" +
                      (" (kind=%s)" % kind if kind else ""), {"applicable": False})
    evidence = {}
    violations = []
    advisory = []
    for entry in svg_entries:
        root, err = _parse_svg(entry["path"])
        if err:
            advisory.append("%s: %s" % (entry["name"], err))
            evidence[entry["name"]] = {"error": err}
            continue
        centres = _svg_entity_centres(root)
        geometry = _svg_relation_geometry(root)
        checked = []
        for rel in relations:
            rid = str(rel.get("id"))
            geo = geometry.get("rel:%s" % rid)
            if not geo:
                continue
            source, target = str(rel.get("from")), str(rel.get("to"))
            src_c, dst_c = centres.get(source), centres.get(target)
            if not src_c or not dst_c:
                continue

            def _dist(point, centre):
                return ((point[0] - centre[0]) ** 2 + (point[1] - centre[1]) ** 2) ** 0.5

            def _tip(side):
                if side == "end":
                    if geo["arrow"]:
                        return geo["arrow"][0]
                    if geo["tee"]:
                        return ((geo["tee"][0][0] + geo["tee"][1][0]) / 2.0,
                                (geo["tee"][0][1] + geo["tee"][1][1]) / 2.0)
                elif geo["polyline"]:
                    return geo["polyline"][0]
                return None

            declared_end = str(geo.get("head_end") or "none").lower()
            declared_start = str(geo.get("head_start") or "none").lower()
            record = {"id": rid, "direction": rel.get("direction"), "from": source, "to": target,
                      "head_end": declared_end, "head_start": declared_start}
            if declared_end in ("arrow", "tee"):
                tip = _tip("end")
                if tip is None:
                    violations.append("%s: %s declares head_end=%s but no head geometry was "
                                      "drawn (direction is not visible)" % (entry["name"], rid,
                                                                            declared_end))
                else:
                    d_to, d_from = _dist(tip, dst_c), _dist(tip, src_c)
                    record["tip_to_target_mm"] = round(d_to, 2)
                    record["tip_to_source_mm"] = round(d_from, 2)
                    if d_to >= d_from:
                        violations.append("%s: %s head_end=%s but the head is nearer the SOURCE "
                                          "(%s %.1f mm vs %s %.1f mm)"
                                          % (entry["name"], rid, declared_end, source, d_from,
                                             target, d_to))
            if declared_start in ("arrow", "tee"):
                tip = _tip("start")
                if tip is None:
                    violations.append("%s: %s declares head_start=%s but no head geometry"
                                      % (entry["name"], rid, declared_start))
                else:
                    d_from, d_to = _dist(tip, src_c), _dist(tip, dst_c)
                    record["start_tip_to_source_mm"] = round(d_from, 2)
                    if d_from >= d_to:
                        violations.append("%s: %s head_start=%s but the head is nearer the TARGET"
                                          % (entry["name"], rid, declared_start))
            if str(rel.get("direction") or "") == "none" and (
                    declared_end in ("arrow", "tee") or declared_start in ("arrow", "tee")):
                advisory.append("%s: %s is direction=none but carries a head"
                                % (entry["name"], rid))
            checked.append(record)
        evidence[entry["name"]] = {"relations": checked, "checked": len(checked)}
        if not checked:
            advisory.append("%s: no relation geometry could be matched to the model"
                            % entry["name"])
    kind = str(((model or {}).get("figure") or {}).get("kind") or "")
    if not any(e.get("checked") for e in evidence.values()) and kind == "chart":
        # A chart figure draws categories and series, not relations: nothing to
        # orient.  Mirrors how svg_provenance/pdf_text treat chart figures.
        return _check("svg_edge_direction", "error", True,
                      "N/A: kind=chart draws no relation geometry to orient",
                      {"applicable": False, "evidence": evidence})
    if violations:
        return _check("svg_edge_direction", "error", False,
                      "; ".join(violations)[:600] + " (fatal class: upstream/downstream "
                      "inverted or feedback drawn backwards)", evidence)
    if advisory:
        return _check("svg_edge_direction", "warn", True,
                      "edge direction: %s" % "; ".join(advisory)[:400], evidence)
    return _check("svg_edge_direction", "error", True,
                  "edge direction OK (heads at the model's target end): %s"
                  % ", ".join("%s(%d relations)" % (n, e.get("checked", 0))
                              for n, e in evidence.items()), evidence)


def _check_coverage(entries, channels):
    """Requested vs produced.  Missing core formats are errors; extras are warnings."""
    present = {e.get("format") for e in entries if os.path.isfile(e["path"])}
    expected = [f for f in channels["formats"] if f in ("svg", "pdf", "png", "tiff", "eps")]
    missing = [f for f in expected if f not in present]
    fatal = [f for f in missing if f in CORE_FORMATS]
    detail = ("missing requested format(s): %s%s" % (
        ", ".join(missing),
        " (core formats missing: %s -- a journal submission cannot be completed without "
        "these)" % ", ".join(fatal) if fatal else
        " (all core formats present; the missing ones are optional extras)")
        if missing else "all requested formats present: %s" % ", ".join(sorted(present)))
    return _check("format_coverage",
                  "warn" if (missing and not fatal) else "error", not missing, detail,
                  {"requested": expected, "present": sorted(present), "missing": missing,
                   "missing_core": fatal})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def check_artifacts(paths, spec, *, model=None) -> dict:
    """Run the real compliance checks over the exported artifacts.

    ``paths`` accepts a list of paths, a ``{format: path}`` dict (the shape
    ``export_all()["formats"]`` can be reduced to), a list of ``export_all``
    format entries, or a directory.  Missing and corrupt artifacts are reported
    as failed checks; the function itself always returns a dict.
    """
    channels = _spec(spec)
    entries = _normalise_paths(paths)
    groups = _by_format(entries)
    drawn = _drawn_canvas_mm(groups.get("svg") or [], model, channels)

    checks = []
    checks.append(_check_coverage(entries, channels))
    checks.append(_check_nonempty(entries, channels))
    checks.append(_check_svg_layers(groups.get("svg") or [], channels))
    checks.append(_check_svg_editable(groups.get("svg") or [], channels))
    checks.append(_check_svg_provenance(groups.get("svg") or [], model, channels))
    checks.append(_check_svg_legend_colors(groups.get("svg") or [], model, channels))
    checks.append(_check_svg_edge_direction(groups.get("svg") or [], model, channels))
    checks.append(_check_line_width(groups.get("svg") or [], channels))
    checks.append(_check_raster_dpi(groups.get("png", []) + groups.get("tiff", []),
                                    channels, model, drawn))
    checks.append(_check_raster_opens(groups.get("png", []) + groups.get("tiff", []), channels))
    checks.append(_check_pdf_opens(groups.get("pdf") or [], channels))
    checks.append(_check_pdf_fonts(groups.get("pdf") or [], channels))
    checks.append(_check_pdf_size(groups.get("pdf") or [], channels, model, drawn))
    checks.append(_check_pdf_text(groups.get("pdf") or [], model, channels,
                                  groups.get("svg") or []))
    checks.append(_check_eps_fonts(groups.get("eps") or [], channels))
    checks.append(_check_color_space(entries, channels))

    errors = [c for c in checks if not c["ok"] and c["level"] == "error"]
    warnings = [c for c in checks if not c["ok"] and c["level"] == "warn"]
    result = {
        "schema_version": SCHEMA_VERSION,
        "created_utc": common.now_utc(),
        "ok": not errors,
        "checks": checks,
        "canvas_used": drawn,
        "summary": {
            "total": len(checks),
            "passed": len([c for c in checks if c["ok"]]),
            "failed_errors": [c["id"] for c in errors],
            "failed_warnings": [c["id"] for c in warnings],
            "artifacts": {e["name"]: e.get("format") for e in entries},
        },
        "spec": {k: channels[k] for k in ("dpi", "min_line_width_pt", "min_text_pt",
                                          "color_space", "font_embedding_required",
                                          "width_mm", "max_height_mm", "formats")},
    }
    return result
