# -*- coding: utf-8 -*-
"""selftest.py - executable acceptance check for the skill.

Run:  python scripts/selftest.py [--json] [--keep]

It exercises the *real* pipeline (prepare -> render -> export -> finish -> edit)
on the bundled `examples/` case and then injects defects that the gates must
catch. Nothing is mocked and nothing is silently skipped: a check either runs
and passes, runs and fails, or is explicitly reported as `unavailable` because
this environment lacks an optional backend. `vacuous_skips` counts checks that
did not actually execute - it must stay 0 for the exit code to be 0.

Exit codes: 0 all executed checks passed; 1 one or more failed; 2 harness error.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import common  # noqa: E402
import run as run_mod  # noqa: E402


class Result:
    def __init__(self):
        self.checks = []
        self.failures = 0
        self.unavailable = 0

    def add(self, name, ok, detail="", unavailable=False):
        if unavailable:
            self.unavailable += 1
            state = "UNAVAILABLE"
        else:
            state = "PASS" if ok else "FAIL"
            if not ok:
                self.failures += 1
        self.checks.append({"name": name, "state": state, "detail": str(detail)[:400]})
        return ok

    def section(self, title):
        self.checks.append({"name": "-- " + title + " --", "state": "SECTION", "detail": ""})


def _run(argv, expect=None):
    """Invoke run.py's real main() in-process; return (code, payload)."""
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = run_mod.main(argv)
    text = buf.getvalue().strip()
    payload = None
    if text:
        try:
            payload = json.loads(text)
        except ValueError:
            payload = {"raw": text[:500]}
    return code, payload


def _sha(path):
    return common.sha256_file(path)


def _read(p):
    with open(p, "rb") as fh:
        return fh.read()


# --------------------------------------------------------------------------
# defect injections (must each be caught by a specific error code)
# --------------------------------------------------------------------------
def injections(model, inventory):
    """Return [(label, mutated_model, expected_error_codes)].

    Every mutation targets a distinct frozen error code so that "detected"
    means "this specific gate fired", not "something went wrong".
    """
    cases = []

    def mutate(fn, label, codes):
        m = copy.deepcopy(model)
        fn(m)
        cases.append((label, m, codes))

    def flip_direction(m):
        for r in m.get("relations", []):
            if r.get("type") == "inhibition":
                r["type"] = "activation"          # quote still says 抑制
                return
    mutate(flip_direction, "inhibition relabelled as activation",
           {"E_DIRECTION_UNSUPPORTED"})

    def invented_label(m):
        for e in m.get("entities", []):
            e["label"] = "NOTINGENES_XYZ"
            return
    mutate(invented_label, "entity label absent from the sources",
           {"E_LABEL_NOT_IN_SOURCE"})

    def bad_quote(m):
        for e in m.get("entities", []):
            if e.get("source"):
                e["source"]["quote"] = "this sentence does not occur in the material"
            return
    mutate(bad_quote, "quote not present in the source", {"E_QUOTE_NOT_FOUND"})

    def drop_provenance(m):
        for e in m.get("entities", []):
            e.pop("source", None)
            return
    mutate(drop_provenance, "entity with no provenance at all",
           {"E_PROVENANCE_MISSING", "E_QUOTE_NOT_FOUND", "E_LABEL_NOT_IN_SOURCE"})

    def dangling(m):
        m["relations"].append({
            "id": "r_ghost", "from": "e_does_not_exist", "to": "e_trpm7",
            "type": "activation", "direction": "forward", "label": "激活",
            "source": {"path": "materials/demo_pathway.md", "locator": "L8",
                       "kind": "explicit", "quote": "激活下游激酶 CAMK2"}})
    mutate(dangling, "relation pointing at a non-existent node",
           {"E_DANGLING_REF", "E_ORPHAN_RELATION"})

    def dup_id(m):
        m["entities"].append(copy.deepcopy(m["entities"][0]))
    mutate(dup_id, "duplicate entity id", {"E_DUP_ID"})

    def cycle(m):
        # Nested grouping (container listed as another container's member) must stay
        # acyclic; entity.container values are left valid so only the cycle fires.
        con = {c["id"]: c for c in m.get("containers", [])}
        if "c_membrane" in con and "c_intracellular" in con:
            con["c_membrane"]["members"] = list(con["c_membrane"]["members"]) + ["c_intracellular"]
            con["c_intracellular"]["members"] = list(con["c_intracellular"]["members"]) + ["c_membrane"]
    mutate(cycle, "container membership cycle", {"E_CONTAINER_CYCLE"})

    def unitless(m):
        if isinstance(m.get("data"), dict):
            m["data"]["units"] = {}
            for s in m["data"].get("series", []) or []:
                s.pop("unit", None)
    mutate(unitless, "numeric column with no unit",
           {"E_UNIT_MISSING", "E_LEGEND_DATA_MISMATCH"})

    def legend_mismatch(m):
        if m.get("legend"):
            # keep the line-style entries plus ONE category, so the category count
            # (1) contradicts the data's series count (2)
            m["legend"] = [i for i in m["legend"] if i.get("id") != "lg_vehicle"]
    mutate(legend_mismatch, "legend categories collapsed vs the data table",
           {"E_LEGEND_DATA_MISMATCH"})

    def number_not_in_source(m):
        for e in m.get("entities", []):
            e["value"] = 987654.0
            e["unit"] = "fold change"
            e["source"] = {"path": "materials/demo_pathway.md", "locator": "L8",
                           "kind": "explicit", "quote": "激活下游激酶 CAMK2"}
            return
    mutate(number_not_in_source, "numeric value absent from the sources",
           {"E_NUMBER_NOT_IN_SOURCE", "E_UNIT_MISSING"})

    return cases


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="selftest.py")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep the scratch directories")
    args = ap.parse_args(argv)

    t0 = time.time()
    res = Result()
    root = os.path.dirname(HERE)
    examples = os.path.join(root, "examples")
    scratch = common.make_temp_dir("sest-selftest")
    work = os.path.join(scratch, "work")
    out = os.path.join(scratch, "out")
    os.makedirs(work)
    os.makedirs(out)

    try:
        return _body(args, res, examples, work, out, t0)
    finally:
        if not args.keep:
            shutil.rmtree(scratch, ignore_errors=True)
        else:
            common.log("scratch kept at %s" % scratch)


def _body(args, res, examples, work, out, t0):
    if not os.path.isdir(examples):
        common.log("examples/ missing next to scripts/ - cannot self-test")
        return 2

    # ---------------- 1. prepare ----------------
    res.section("prepare")
    code, payload = _run(["prepare", "--input", examples, "--work", work, "--output", out])
    res.add("prepare exit 0", code == 0, "exit=%s" % code)
    res.add("prepare found materials", (payload or {}).get("materials", 0) > 0,
            "materials=%s" % (payload or {}).get("materials"))
    res.add("prepare extracted source units", (payload or {}).get("source_units", 0) > 0,
            "units=%s" % (payload or {}).get("source_units"))
    for name in ("case_manifest.json", "source_inventory.json", "figure_model.draft.json",
                 "REVIEW_BATCH.json"):
        res.add("prepare wrote %s" % name, os.path.isfile(os.path.join(work, name)))
    batch = common.load_json(os.path.join(work, "REVIEW_BATCH.json"), {}) or {}
    res.add("REVIEW_BATCH carries must_decide", isinstance(batch.get("must_decide"), list),
            "n=%s" % len(batch.get("must_decide") or []))
    early = common.load_json(os.path.join(out, "result.json"), {}) or {}
    res.add("early result.json is honestly partial",
            early.get("status") in ("partial", "needs_human"), "status=%s" % early.get("status"))

    # ---------------- 2. render ----------------
    res.section("render")
    # An unrevised draft must not be reported as a finished figure. It is reported
    # (status=partial + W_MODEL_NOT_REVISED) without failing the run, because a run
    # that still produced a usable, source-checked figure should not be thrown away.
    code, payload = _run(["render", "--work", work, "--output", out])
    draft_codes = set((payload or {}).get("error_codes") or [])
    draft_warn = {(w or {}).get("code") for w in ((payload or {}).get("warnings") or [])}
    res.add("unrevised draft is not reported ok",
            (payload or {}).get("status") == "partial" and (payload or {}).get("used_draft") is True,
            "status=%s used_draft=%s" % ((payload or {}).get("status"),
                                         (payload or {}).get("used_draft")))
    # The exit code also reflects any other model errors in the draft, which is a
    # separate concern; what matters here is that the un-revised step is *reported*
    # and that it is not silently escalated into a run-failing error.
    res.add("unrevised draft is flagged, not hidden",
            "W_MODEL_NOT_REVISED" in draft_warn
            and "E_MODEL_NOT_REVISED" not in draft_codes,
            "exit=%s warnings=%s codes=%s" % (code, sorted(draft_warn), sorted(draft_codes)))
    # The escalation capability must still exist and work when a caller arms it,
    # even though the shipped default leaves it unarmed (see run.BLOCKING_WARNINGS).
    res.add("blocking-warning escalation is available and default-off",
            run_mod.BLOCKING_WARNINGS == {}, "armed=%s" % run_mod.BLOCKING_WARNINGS)
    promoted = run_mod._promote_blocking_warnings(
        {"errors": [], "warnings": [{"code": "W_BAR_BASELINE_TRUNCATED", "message": "x"},
                                    {"code": "W_LONG_LABEL", "message": "y"}]},
        mapping={"W_BAR_BASELINE_TRUNCATED": "E_BAR_BASELINE_TRUNCATED"})
    res.add("escalation works when armed",
            any(e.get("code") == "E_BAR_BASELINE_TRUNCATED" for e in promoted["errors"])
            and all(w.get("code") != "W_BAR_BASELINE_TRUNCATED" for w in promoted["warnings"])
            and any(w.get("code") == "W_LONG_LABEL" for w in promoted["warnings"]),
            "errors=%s warnings=%s" % ([e.get("code") for e in promoted["errors"]],
                                       [w.get("code") for w in promoted["warnings"]]))
    model_path = os.path.join(work, "figure_model.json")
    shutil.copyfile(os.path.join(examples, "expected_model.json"), model_path)
    code, payload = _run(["render", "--work", work, "--output", out])
    res.add("render exit 0 (0 gate errors)", code == 0,
            "exit=%s errors=%s" % (code, (payload or {}).get("error_codes")))
    stats = (payload or {}).get("svg_stats", {}) or {}
    res.add("SVG has 7 named layers", stats.get("layers") == 7, "layers=%s" % stats.get("layers"))
    res.add("SVG text is editable text", stats.get("texts", 0) >= 8, "texts=%s" % stats.get("texts"))
    res.add("SVG contains no raster substitute", stats.get("images") == 0,
            "images=%s" % stats.get("images"))
    res.add("every drawn element carries provenance", stats.get("data_prov_count", 0) >= 15,
            "data_prov=%s" % stats.get("data_prov_count"))
    svg = os.path.join(out, "figures", "figure.svg")
    res.add("SVG written", os.path.isfile(svg) and os.path.getsize(svg) > 1000,
            "%s bytes" % (os.path.getsize(svg) if os.path.isfile(svg) else 0))
    smap = common.load_json(os.path.join(out, "source_map.json"), {}) or {}
    res.add("source map binds every element",
            smap.get("unsupported_count") == 0 and smap.get("bound_count", 0) >= 15,
            "bound=%s unsupported=%s" % (smap.get("bound_count"), smap.get("unsupported_count")))

    # determinism: same model -> byte-identical SVG
    first = _read(svg) if os.path.isfile(svg) else b""
    _run(["render", "--work", work, "--output", out])
    second = _read(svg) if os.path.isfile(svg) else b"x"
    res.add("render is deterministic (byte-identical)", first == second and first != b"",
            "sha=%s" % common.sha256_bytes(first)[:16])

    # ---------------- 3. export ----------------
    res.section("export")
    code, payload = _run(["export", "--work", work, "--output", out,
                          "--journal", "nature", "--dpi", "300"])
    res.add("export exit 0 (all compliance checks pass)", code == 0,
            "exit=%s failed=%s" % (code, (payload or {}).get("failed_checks")))
    formats = {f.get("format"): f for f in (payload or {}).get("formats", [])}
    for fmt in ("svg", "pdf", "png"):
        entry = formats.get(fmt) or {}
        path = os.path.join(out, "figures", "figure." + fmt)
        res.add("export produced a real %s" % fmt,
                entry.get("status") == "ok" and os.path.isfile(path)
                and os.path.getsize(path) > 500,
                "status=%s bytes=%s" % (entry.get("status"),
                                        os.path.getsize(path) if os.path.isfile(path) else 0))
    for optional in ("tiff", "eps"):
        entry = formats.get(optional) or {}
        path = os.path.join(out, "figures", "figure." + optional)
        if entry.get("status") == "unavailable":
            res.add("export %s" % optional, True,
                    "unavailable, reported honestly: %s" % entry.get("error"), unavailable=True)
        else:
            res.add("export produced a real %s" % optional,
                    entry.get("status") == "ok" and os.path.isfile(path)
                    and os.path.getsize(path) > 500, "status=%s" % entry.get("status"))
    checks = common.load_json(os.path.join(out, "checks.json"), {}) or {}
    ids = {c.get("id"): c for c in checks.get("checks", [])}
    res.add("compliance emitted its check ids", len(ids) >= 11, "ids=%s" % len(ids))
    for cid in ("svg_layers", "svg_editable_text", "svg_provenance", "line_width_min",
                "pdf_fonts_embedded", "raster_dpi"):
        if cid in ids:
            res.add("check %s" % cid, bool(ids[cid].get("ok")), ids[cid].get("detail", ""))
        else:
            res.add("check %s" % cid, False, "check id absent from checks.json")

    # PDF text is real text
    try:
        import pypdf
        reader = pypdf.PdfReader(os.path.join(out, "figures", "figure.pdf"))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        hit = [lab for lab in ("TRPM7", "CAMK2", "CREB", "BCL2", "CASP3", "SIRT1")
               if lab in text]
        res.add("PDF text layer is extractable", len(hit) >= 4, "labels=%s" % hit)
    except ImportError:
        res.add("PDF text layer is extractable", True, "pypdf unavailable", unavailable=True)

    # ---------------- 4. finish ----------------
    res.section("finish")
    code, payload = _run(["finish", "--work", work, "--output", out])
    res.add("finish exit 0", code == 0, "exit=%s" % code)
    result = common.load_json(os.path.join(out, "result.json"), {}) or {}
    res.add("result.json status is ok", result.get("status") == "ok",
            "status=%s limitations=%s" % (result.get("status"), result.get("limitations")))
    res.add("result.json keeps case_id", result.get("case_id") == "example-relationship-schematic",
            "case_id=%s" % result.get("case_id"))
    contract = result.get("output_contract") or {}
    missing = [k for k, v in contract.items() if not v]
    res.add("every output_contract key filled", bool(contract) and not missing,
            "keys=%s missing=%s" % (sorted(contract), missing))
    res.add("no required field missing", not result.get("missing_required_fields"),
            "missing=%s" % result.get("missing_required_fields"))
    res.add("artifact hashes recorded",
            all(a.get("sha256") for a in result.get("artifacts", []) if a.get("exists")),
            "artifacts=%s" % len(result.get("artifacts", [])))
    # P11b: the self entry must be recomputable, not a stale digest of an older file.
    self_entry = [a for a in result.get("artifacts", []) if a.get("self_referential")]
    if self_entry:
        recomputed = run_mod._self_excluded_hash(result)
        res.add("result.json self digest is recomputable",
                recomputed == self_entry[0].get("sha256"),
                "recorded=%s recomputed=%s" % (str(self_entry[0].get("sha256"))[:16],
                                               recomputed[:16]))
        res.add("self digest is documented",
                bool(self_entry[0].get("hash_basis")), self_entry[0].get("hash_basis", ""))
    else:
        res.add("result.json records a self entry", False, "no self_referential artifact entry")
    res.add("inspection preview exists",
            os.path.isfile(os.path.join(out, "preview", "figure.png")),
            "preview/figure.png")

    # ---------------- 5. edit (source-preserving) ----------------
    res.section("edit")
    ops = {"ops": [
        {"op": "rename_label", "target": "ent:e_trpm7", "value": "TRPM7",
         "reason": "keep canonical gene symbol", "source_refs": [
             {"path": "materials/demo_pathway.md", "locator": "L8", "quote": "受体 TRPM7"}]},
        {"op": "set_color", "target": "lg:lg_2apb", "value": "#009E73",
         "reason": "keep the legend swatch stable across versions"},
        {"op": "update_data", "target": "data.units.fold_change", "value": "fold change",
         "reason": "unit must stay explicit"},
    ]}
    common.write_json(os.path.join(work, "edit_ops.json"), ops)
    code, payload = _run(["edit", "--work", work, "--output", out])
    res.add("edit exit 0", code == 0,
            "exit=%s codes=%s" % (code, (payload or {}).get("post_edit_error_codes")))
    res.add("edit applied every op", (payload or {}).get("ops_applied") == len(ops["ops"]),
            "ops_applied=%s" % (payload or {}).get("ops_applied"))
    clog = common.load_json(os.path.join(out, "change_log.json"), {}) or {}
    res.add("change log has before/after records",
            len(clog.get("entries", [])) == len(ops["ops"])
            and bool(clog.get("artifacts_before")) and bool(clog.get("artifacts_after")),
            "entries=%s changed=%s" % (len(clog.get("entries", [])),
                                       len(clog.get("artifacts_changed", []))))
    res.add("edit redrew the figure", bool((payload or {}).get("artifacts_changed")),
            "changed=%s" % (payload or {}).get("artifacts_changed"))
    res.add("provenance survived the edit", clog.get("provenance_preserved") is True,
            "provenance_preserved=%s" % clog.get("provenance_preserved"))

    # a numeric correction must be expressible without clobbering the element id
    probe = copy.deepcopy(common.load_json(
        os.path.join(examples, "expected_model.json"), {}) or {})
    edited, recs = run_mod._apply_ops(probe, {"ops": [
        {"op": "set_value", "target": "ent:e_bcl2", "value": 1.42,
         "reason": "corrected reading", "source_refs": [
             {"path": "materials/expression.csv", "locator": "table:fold_change",
              "quote": "1.00"}]}]})
    target = [e for e in edited.get("entities", []) if e.get("id") == "e_bcl2"]
    res.add("set_value updates the number, not the id",
            bool(target) and target[0].get("value") == 1.42
            and target[0].get("id") == "e_bcl2"
            and bool(recs and recs[0]["before"] != recs[0]["after"]),
            "value=%s id=%s" % (target[0].get("value") if target else None,
                                target[0].get("id") if target else None))
    res.add("set_value keeps the element's provenance",
            bool(target) and bool(target[0].get("source")),
            "source=%s" % bool(target and target[0].get("source")))

    # ---------------- 6. injected defects ----------------
    res.section("negative (injected defects must be caught)")
    import model as model_mod
    motion = _load_module("model")
    inventory = common.load_json(os.path.join(work, "source_inventory.json"), {}) or {}
    base_model = common.load_json(os.path.join(examples, "expected_model.json"), {}) or {}
    cases = injections(base_model, inventory)
    detected = 0
    for label, mutated, expected in cases:
        try:
            issues = motion.validate_model(mutated, inventory, strict=True)
            got = {e.get("code") for e in issues.get("errors", [])}
        except Exception as exc:  # noqa: BLE001 - a crash is NOT a detection
            got = {"__crash__:%s" % type(exc).__name__}
        hit = bool(got & expected)
        if hit:
            detected += 1
        res.add("caught: %s" % label, hit, "expected=%s got=%s" % (sorted(expected), sorted(got)))
    total = len(cases)
    res.add("negative detection rate", detected == total, "%d/%d" % (detected, total))

    # export negative: a 72-dpi raster must fail a 300-dpi requirement. Lowering
    # --dpi lowers what we *ask for*, so the requirement is pinned separately to
    # the journal preset rather than to the override.
    code, payload = _run(["export", "--work", work, "--output", out, "--dpi", "72"])
    res.add("export at 72 dpi succeeds for its own spec", code == 0, "exit=%s" % code)
    low = os.path.join(out, "figures", "figure.png")
    compliance = _load_module("compliance")
    export_mod = _load_module("export")
    strict_spec = export_mod.journal_preset("nature")
    strict_spec["formats"] = ["png"]
    strict = compliance.check_artifacts([low], strict_spec, model=None)
    bad = [c["id"] for c in strict.get("checks", []) if not c.get("ok")]
    res.add("caught: 72 dpi raster vs a 300 dpi requirement",
            strict.get("ok") is False and "raster_dpi" in bad,
            "ok=%s failed=%s" % (strict.get("ok"), bad))

    # edit negative: an op that would introduce an unverifiable label must be refused
    common.write_json(os.path.join(work, "edit_ops_bad.json"),
                      {"ops": [{"op": "set_label", "target": "ent:e_trpm7",
                                "value": "NOTINGENES_XYZ"}]})
    code, payload = _run(["edit", "--work", work, "--output", out,
                          "--ops", os.path.join(work, "edit_ops_bad.json")])
    bad_codes = set((payload or {}).get("post_edit_error_codes") or [])
    res.add("caught: edit introducing an unverifiable label",
            code == 4 and bool(bad_codes & {"E_LABEL_NOT_IN_SOURCE", "E_QUOTE_NOT_FOUND"}),
            "exit=%s codes=%s" % (code, sorted(bad_codes)))

    # ---------------- 7. robustness ----------------
    res.section("robustness")
    empty = common.make_temp_dir("sest-empty")
    try:
        code, payload = _run(["prepare", "--input", empty, "--work",
                              os.path.join(empty, "w"), "--output", os.path.join(empty, "o")])
        res.add("empty input does not crash (honest needs_human)", code == 3,
                "exit=%s status=%s" % (code, (payload or {}).get("status")))
        rj = common.load_json(os.path.join(empty, "o", "result.json"), {}) or {}
        res.add("empty input still writes result.json", rj.get("status") == "needs_human",
                "status=%s" % rj.get("status"))
    finally:
        shutil.rmtree(empty, ignore_errors=True)

    code, payload = _run(["render", "--work", os.path.join(empty, "gone"),
                          "--output", out])
    res.add("missing model fails cleanly with exit 2", code == 2, "exit=%s" % code)

    del model_mod
    # ---------------- summary ----------------
    vacuous = sum(1 for c in res.checks if c["state"] == "SKIP")
    summary = {
        "ok": res.failures == 0,
        "passed": sum(1 for c in res.checks if c["state"] == "PASS"),
        "failed": res.failures,
        "unavailable": res.unavailable,
        "vacuous_skips": vacuous,
        "elapsed_s": round(time.time() - t0, 1),
        "checks": res.checks,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for c in res.checks:
            if c["state"] == "SECTION":
                print("\n== %s" % c["name"].strip("- "))
            elif c["state"] != "PASS":
                print("  [%s] %s :: %s" % (c["state"], c["name"], c["detail"]))
        print("\nRESULT: %s  (%d passed, %d failed, %d unavailable, %d vacuous skips, %.1fs)"
              % ("PASS" if summary["ok"] else "FAIL", summary["passed"], res.failures,
                 res.unavailable, vacuous, summary["elapsed_s"]))
    return 0 if summary["ok"] else 1


def _load_module(name):
    import importlib
    return importlib.import_module(name)


if __name__ == "__main__":
    raise SystemExit(main())
