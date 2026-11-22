# 结果合同（`result.json`）

`run.py finish` 写出的 `/app/output/result.json` 是**一次运行的回执**。它有两个不可妥协的性质：

1. **原样保留输入合同**：`/input/case.json` 里的 `output_contract` 的每一个键都必须出现且类型不变；
   只允许把空字符串占位填成本轮**真实产出**的相对路径，不得增删键、不得把 object/list 拍平成标量。
2. **不夸大**：`status` 只有 `ok|partial|needs_human` 三态；没产出的东西不写、产不出的写清原因。

## 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | str | 固定 `"1.0"` |
| `case_id` | str | **必须与输入一致**（取自 `case.json`，缺失时回退 `task.md` 标题 slug） |
| `status` | enum | `ok` = 门禁全过且导出合规；`partial` = 有产物但存在错误级问题或合规失败；`needs_human` = 材料不足/无法解析，需人工提供材料或裁决 |
| `output_contract` | object | **原合同的逐键映射**（key 不变，值为真实产物相对路径） |
| `required_fields_present` | object | `required_fields` 里每个键是否存在 |
| `missing_required_fields` | list | 仍为空的必需键（`status` 应相应降级） |
| `artifacts` | list | `[{key,path,bytes,sha256,exists}]`，每个交付件的真实大小与哈希 |
| `sources` | list | `[{path,locator,sha256}]`：实际被引用到的来源单元（来自 `source_inventory.json`） |
| `source_unit_count` / `table_count` | int | 材料规模 |
| `uncertainty` | list | `[{where,issue,action}]`：模型的未决点 + 门禁报出的溯源疑点 |
| `limitations` | list | 明确的能力边界/未完成项（缺格式、缺字体、草稿未复核、未解错误码） |
| `checks` | object | `export_ok`、逐项 `export_checks`、`model_errors`、`model_warnings`、`formats_ok`、`formats_unavailable` |
| `audit` | object | `skill`、`skill_path`、`stage`、`written_utc`、`model_file_used`、`model_sha256`、`output_dir`、`work_dir`、`deterministic` |

## 三种状态的判定（冻结）

```
无任何来源单元且无表格                      -> needs_human
有错误级模型/布局问题，或导出检查不过，或核心产物缺失 -> partial（核心产物也缺则 needs_human）
其余                                        -> ok
```

`--strict` 下：`finish` 在 `status != "ok"` 时返回 3（供 CI/自测使用）。

## 与输出合同键的匹配规则

键名到产物的映射是**保守**的（`run.py:_CONTRACT_HINTS`）：只有键名里出现
`svg/pdf/png/tiff/eps/source/model/editable/changelog/export/report/check/result` 这类明确记号时才填，
每个产物按 token 优先匹配一次；**认不出的键保留原值**，不会被猜成某个路径。
若合同点名了 `pdf`/`tiff`/`eps` 而环境缺后端，该键保持空字符串，同时 `status` 降级并把原因写进 `limitations`。

## 示例（示意，非正式案例结果）

```json
{
  "schema_version": "1.0",
  "case_id": "example-relationship-schematic",
  "status": "ok",
  "output_contract": {
    "editable_source": "figure_model.json",
    "figure_svg": "figures/figure.svg",
    "figure_pdf": "figures/figure.pdf",
    "result_json": "result.json"
  },
  "artifacts": [
    {"key": "model", "path": "figure_model.json", "bytes": 8123, "sha256": "…", "exists": true}
  ],
  "sources": [{"path": "materials/demo_pathway.md", "locator": "L8", "sha256": "…"}],
  "uncertainty": [],
  "limitations": [],
  "checks": {"export_ok": true, "model_errors": 0, "model_warnings": 1,
             "formats_ok": ["svg", "pdf", "png"], "formats_unavailable": []},
  "audit": {"skill": "scientific-editable-schematic", "stage": "finish",
            "written_utc": "2026-01-01T00:00:00Z", "deterministic": true}
}
```