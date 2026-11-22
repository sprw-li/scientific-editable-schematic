# scientific-editable-schematic — 安装与使用说明

科研示意图 / 机制图 / 流程图 / 数据驱动图表的**来源可溯 + 可编辑 + 合规导出**流水线。
本文件讲安装、依赖、字体、参数、边界与维护；接口与五道门禁见 `SKILL.md`，字段合同见 `references/`。

## 1. 安装

平台会把本目录安装到 `/skills/weekly-skill`。本地验证时把 `SKILL` 指向本目录即可：

```bash
export SKILL=/skills/weekly-skill

python "$SKILL/scripts/run.py" prepare --input /input --work /app/work --output /app/output
# Agent 依材料修订 /app/work/figure_model.json（草稿在 figure_model.draft.json）
python "$SKILL/scripts/run.py" render  --work /app/work --output /app/output
python "$SKILL/scripts/run.py" export  --work /app/work --output /app/output --journal nature
python "$SKILL/scripts/run.py" finish  --work /app/work --output /app/output
```

子命令、参数与退出码：

| 子命令 | 关键参数 | 退出码 |
|---|---|---|
| `prepare` | `--input` `--work` `--output` | 0 就绪 / 2 输入或 JSON 错误 / 3 无可解析材料（`needs_human`） |
| `render` | 同上 + `--model` | 0 通过门禁 / 2 模型缺失 / 3 环境 / 4 存在错误级问题 |
| `export` | 同上 + `--journal` `--dpi` `--width-mm` `--formats` | 0 合规 / 2 配置 / 3 后端缺失 / 4 合规检查失败 |
| `edit` | 同上 + `--ops` | 0 已重绘重导 / 2 ops 非法 / 4 编辑后引入不可核验元素 |
| `finish` | 同上 + `--strict` | 0 汇总 / 2 输入错误 / 3 `--strict` 下非 `ok` |

每个子命令 **stdout 只有一个 JSON**，人类可读日志走 stderr；不要只看退出码。

## 2. 依赖

**核心路径只依赖 Python 3.8+ 标准库**（`json`/`csv`/`xml`/`hashlib`/`zipfile`/`re`/`math`）。
以下第三方库**按可用性探测**，缺失时对应格式标 `unavailable` 并写明原因，绝不用占位文件冒充：

| 库 | 用途 | 缺失时 |
|---|---|---|
| `matplotlib` | PDF/EPS/PNG 矢量与位图导出（`pdf.fonttype=42` 保证字体内嵌且可编辑） | PDF/EPS 标 `unavailable` |
| `Pillow` (PIL) | TIFF/PNG、DPI 与色彩空间元数据、栅格校验 | TIFF 标 `unavailable` |
| `pypdf` | 打开 PDF、抽取文本、检查字体是否内嵌 | PDF 检查降级为 `warn` 并注明未能验证 |
| `lxml` | 可选加速；未安装时用标准库 `xml.etree` | 无影响 |

外部命令（可选，全部走 `subprocess` 参数数组、`shell=False`）：
`rsvg-convert` / `inkscape`（优先用它把主 SVG 直接栅格化，保真度最高）、`pdffonts` / `pdfinfo`（交叉核对 PDF）、
`gs`（PDF→预览）。探测结果写入 `/app/work/environment.json` 与 `export_report.json.tools`。

安装示例（离线环境请用平台预置，不要联网）：

```bash
pip install matplotlib pillow pypdf        # 仅本地开发需要
```

## 3. 字体

- SVG 里文字是**真 `<text>`**，`font-family` 用**栈式回退**（默认 `DejaVu Sans, Liberation Sans, Arial`），
  按 `figure.style.font_stack` 覆盖，不内嵌二进制字体文件（换字体=改一个属性，不用重画）。
- PDF 走 matplotlib 时设 `pdf.fonttype=42`（TrueType 内嵌）与 `ps.fonttype=42`，避免期刊侧缺字。
  `checks.json` 的 `pdf_fonts_embedded` 会逐个 `/Font` 条目核对 `/FontFile*`。
- 中文字形需要系统里有覆盖 CJK 的字体（如 `Noto Sans CJK` / `Source Han Sans`）。没有时：
  PDF 可能出现豆腐块，`pdf_text_extractable` 仍可通过（文本层是对的），但请在 `limitations` 里写明；
  建议把 `font_stack` 显式写成环境里实际存在的字体名，例如 `["Source Han Sans CN", "DejaVu Sans"]`。
- 字号以 **pt** 存储（`figure.style.font_sizes_pt`），渲染时按画布单位换算；最小字号不要低于 5 pt。

## 4. 画布、单位与分辨率

- 画布尺寸用 **mm**（`figure.canvas.width_mm/height_mm`），因为期刊按毫米栏宽排版：
  `--journal nature` 默认单栏 89 mm、双栏 183 mm（`--width-mm` 可覆盖）。
- SVG 用户单位约定：**1 用户单位 = 1 mm × 画布缩放**，具体换算写在 `references/layout_and_svg.md`；
  用 `width="…mm" height="…mm" viewBox="…"` 让 SVG 在 Inkscape/Illustrator 里打开即为真实物理尺寸。
- 位图 DPI：`--dpi` 覆盖预设（彩色照片 300、线条图 600–1200 常见）。`checks.json` 的 `raster_dpi`
  同时核对**元数据 DPI**与**像素尺寸 ÷ 物理尺寸**，只对上一个不算过。
- 最小线宽：`line_width_min` 按预设（Nature 系建议 ≥0.25 pt 描边、≥0.5 pt 数据线），单位统一 pt。

## 5. 期刊预设

`python "$SKILL/scripts/run.py" export --journal {nature|science|cell|ieee|generic}`。
预设字段含 `width_mm` / `dpi` / `min_line_width_pt` / `font_embedding_required` / `color_space` / `max_height_mm`
与 `source`（依据说明）。**预设里的数值是可核对的通行要求或保守默认值**；`source` 会明确写是前者还是后者。
投稿前请用目标期刊当期 author guidelines 复核一遍，并把它写进 `references/export_and_compliance.md`。

## 6. 常见失败与处置

| 现象 | 原因 | 处置 |
|---|---|---|
| `render` 返回 4，`E_QUOTE_NOT_FOUND` | 模型里的 `quote` 在材料中找不到 | 用 `source_inventory.json` 的实际文本替换；不要改成模糊匹配 |
| `E_LABEL_NOT_IN_SOURCE` | 引入了材料里没有的基因名/处理组/时间点 | 删掉该实体，或把材料里真正支持的说法补进 `quote` |
| `E_DIRECTION_UNSUPPORTED` | 抑制被写成激活、上下游颠倒 | 按材料动词改 `type`；`references/extraction_rules.md` 有词表 |
| `E_LEGEND_DATA_MISMATCH` | 图例分类数 ≠ 数据分类数，或颜色对不上 | 以**数据表**为准重算图例；旧图注/任务书与表冲突时记入 `uncertainty` |
| `E_TEXT_OVERFLOW_EST` | 标签太长撑破节点 | 缩短标签或加宽画布；`W_LONG_LABEL` 会先给警告 |
| `export` 返回 4 且 `raster_dpi` 假 | DPI 不足或像素尺寸与物理尺寸不符 | 提高 `--dpi`，或检查 `--width-mm` |
| `pdf_fonts_embedded` 假 | 用了 Type3/未内嵌字体 | 确认 `pdf.fonttype=42`；换用带完整字形的字体 |
| `formats_unavailable` 非空 | 环境缺 matplotlib/Pillow | 如实记录；投 PDF-only 期刊时 SVG+PDF 已足够 |

## 7. 边界（本 Skill 明确不做）

- 不做统计检验与统计方法选择（只忠实呈现已给数据的映射）；
- 不做海报/封面版式、艺术插画、图像美化（不做照片级渲染与风格迁移）；
- 不做论文正文与文献综述写作；
- 不联网检索补数据：材料里没有的事实不会被补进来，只会进 `uncertainty`/`limitations`。

## 8. 维护

- 版本：`manifest.json` 的 `version`；模型合同版本：`schemas/figure_model.schema.json` 的 `schema_version`。
- 改动纪律：接口（`run.py` 子命令/退出码、模型 schema、产物路径）一旦变更，必须同步 `SKILL.md`、
  `references/`、`scripts/selftest.py`，并让 `selftest.py` 重新通过。
- 自测：`python "$SKILL/scripts/selftest.py"`（正例真跑 + 注入缺陷必须被检出，`vacuous_skips` 必须为 0）。
- 结构自检（本地工具）：`py -3 _shared/tools/validate_skill_submission.py <submission-dir>`。
- 已知限制：CJK 字体是否可用取决于运行环境；PDF 文本抽取依赖 `pypdf`；EPS 由 matplotlib 输出，
  不含 `<text>` 语义但仍保留矢量与字体引用，可编辑性以 SVG 主源文件为准。