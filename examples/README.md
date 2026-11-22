# `examples/` — 最小调用示例（**示例，不是正式案例答案**）

本目录只为一件事存在：**说明接口与完整使用流程**。这里的所有材料都是为演示而构造的示意输入，
其中的通路、数值与图注**不得**当作任何正式案例的结果或答案；正式案例由平台提供。

## 内容

| 路径 | 说明 |
|---|---|
| `case.json` | 一个最小 `case.json`：`case_id`、`output_contract`（4 个键）、`figure`（`relationship_schematic`，180×120 mm） |
| `materials/demo_pathway.md` | 示意材料：一段机制描述 + 模块分组 + 图例口径 |
| `materials/expression.csv` | 示意数据表：`group,gene,fold_change` |
| `expected_model.json` | 示意**模型**（不是渲染结果）：演示 `schemas/figure_model.schema.json` 的完整形状与逐元素溯源绑定 |

`expected_model.json` 里每条 `source.quote` 都能在 `materials/demo_pathway.md` 的对应行逐字找到，
这正是 `validate_model` 会核对的那件事——示例因此同时充当「最小可核验样例」。

## 跑通它（示例输出标注为 example）

```bash
export SKILL=/skills/weekly-skill
WORK=$(mktemp -d); OUT=$(mktemp -d)

# 1) 盘点示例材料
python "$SKILL/scripts/run.py" prepare \
    --input "$SKILL/examples" --work "$WORK" --output "$OUT"

# 2) 用示例模型替代草稿（真实使用时这一步是 Agent 依材料修订 figure_model.json）
cp "$SKILL/examples/expected_model.json" "$WORK/figure_model.json"

# 3) 渲染 → 导出 → 汇总
python "$SKILL/scripts/run.py" render --work "$WORK" --output "$OUT"
python "$SKILL/scripts/run.py" export --work "$WORK" --output "$OUT" --journal generic --dpi 300
python "$SKILL/scripts/run.py" finish --work "$WORK" --output "$OUT"
```

预期产物（全部为**本轮真实生成**）：

- `$OUT/figure_model.json` — 可编辑模型
- `$OUT/figures/figure.svg` — 7 个命名图层、文字是 `<text>`、每个元素带 `data-prov`
- `$OUT/figures/figure.pdf` / `.png`（环境有 matplotlib/Pillow 时）
- `$OUT/checks.json`、`$OUT/export_report.json`、`$OUT/result.json`

## 示意输出

下面的片段是 `figures/figure.svg` 在示例输入下的**结构示意**（节选，标注为 example）：

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="180mm" height="120mm" viewBox="0 0 1800 1200">
  <metadata>{ "case_id": "example-relationship-schematic", "skill": "scientific-editable-schematic", ... }</metadata>
  <g id="layer:background"><title>background</title> ... </g>
  <g id="layer:containers"><title>containers</title>
    <rect id="cont:c_membrane" data-prov="materials/demo_pathway.md#L15" .../>
  </g>
  <g id="layer:edges"><title>edges</title>
    <path id="rel:r_bcl2_casp3" data-rel-type="inhibition" data-direction="forward"
          data-prov="materials/demo_pathway.md#L10" marker-end="url(#tee)" .../>
  </g>
  <g id="layer:nodes"><title>nodes</title>
    <g id="ent:e_trpm7" data-src-kind="explicit" data-prov="materials/demo_pathway.md#L8"> ... </g>
  </g>
  <g id="layer:labels"><title>labels</title>
    <text font-family="DejaVu Sans, Liberation Sans, Arial" font-size="7">TRPM7</text>
  </g>
  <g id="layer:legend"><title>legend</title> ... </g>
  <g id="layer:annotations"><title>annotations</title><text>A</text></g>
</svg>
```

（真实输出会包含完整坐标、配色与全部元素；此处仅示层级、可编辑文字与溯源属性。）