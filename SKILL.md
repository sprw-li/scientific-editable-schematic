---
name: scientific-editable-schematic
description: >-
  Generate or edit a source-bound, publication-ready scientific schematic (mechanism /
  relationship / flowchart / data-driven chart) from real case materials, and deliver a
  layered editable SVG master plus journal-compliant PDF/PNG/TIFF/EPS exports, with
  per-element provenance, direction and hierarchy checks, legend-to-data consistency,
  and a source-preserving change log. Use when a figure must be traceable to its source
  materials and remain editable afterwards, not merely look pretty.
---

# 科研示意图生成与编辑（scientific-editable-schematic）

把「来源材料」变成「可继续编辑的图稿」再变成「能投出去的导出件」，并且**让每一步都能被独立复核**。

本 Skill 不套模板、不生成插画。它的核心主张是：**图由一份带引文溯源的实体—关系—数据模型驱动**。
模型是可编辑源文件的真身，SVG/PDF/PNG 只是它的投影；改数据或改标签后重跑即可同步，不需要重画。
任何在图中出现、但来源材料里找不到逐字支持的基因名、浓度、时间点或单位，都会被门禁拦下。

## 什么时候用

- 给定文字描述 / 数据表 / PDF / 草图，要产出机制图、关系示意图、流程图或数据驱动图表；
- 已有的图需要**保留来源地修改**（改标签、改配色、改某个数据点），并要留下改动记录；
- 要求「可编辑源文件 + 目标期刊合规导出件」同时交付，且能被审稿人逐元素追溯。

不适用（本 Skill 明确不负责）：统计检验与统计方法选择、海报/封面版式设计、艺术插画与图像美化、论文正文与文献综述写作。

## 快速开始（三步 + 一次裁决）

```bash
export SKILL=/skills/weekly-skill          # 平台安装位置

# 1) 盘点材料：清单 / 来源单元 / 草稿模型 / 待裁决项
python "$SKILL/scripts/run.py" prepare \
    --input /input --work /app/work --output /app/output

# 2) Agent 读 /app/work/REVIEW_BATCH.json 与 figure_model.draft.json，
#    依据材料逐项修订，写出 /app/work/figure_model.json（真实科学判断在这一步）
python "$SKILL/scripts/run.py" render --work /app/work --output /app/output

# 3) 真实导出 + 期刊合规检查
python "$SKILL/scripts/run.py" export --work /app/work --output /app/output \
    --journal nature --dpi 600

# 4) 汇总（result.json 保留原 output_contract 全部字段）
python "$SKILL/scripts/run.py" finish --work /app/work --output /app/output
```

可选：来源保留式编辑（改标签/配色/数据点后重绘重导，并写 change_log.json）：

```bash
python "$SKILL/scripts/run.py" edit --work /app/work --output /app/output \
    --ops /app/work/edit_ops.json
```

`prepare` 之后**不要**直接 `render` 就交货。`prepare` 只给草稿；草稿的每个不确定判断都写在
`REVIEW_BATCH.json` 的 `must_decide` 与 `figure_model.draft.json` 的 `uncertainty` 里，必须由 Agent
用材料裁决。直接用草稿渲染时 `render` 会在 stderr 明确警告，`finish` 会把 `status` 降级并写入 limitations。

### Agent 在 prepare 与 render 之间必须裁决的事

草稿是**关键词扫描的骨架，不是科研模型**（实测：机制类案例会产出数十个 `Core`/`Drawing`/色值一类的伪实体）。
以下各项不做，图稿即使渲染成功也是错的：

| 必须裁决 | 判据 |
|---|---|
| 实体集合 | 只保留材料里真实存在的基因/蛋白/过程/处理组；删掉从版式或说明文字里刮出来的伪实体 |
| **`kind=chart` 的实体** | 应为**数据分类**（如三个物种），不要用材料散文里的名词；图表本身不画实体框，留着它们只会造成图例与图不一致 |
| 关系方向 | 抑制/激活、上游/下游按材料动词判定（词表见 `references/extraction_rules.md`） |
| 分组 | 依据材料明写的模块划分；不要把包含关系画成并列 |
| 图例口径 | 分类数 = 数据分类数；颜色/标记与数据系列一一对应 |
| 单位 | 数值列必须有单位；数据表优先于旧图注/任务书，冲突时以表为准并记入 `uncertainty` |
| 数值 | 图里出现的每个数都要能在材料中逐字找到 |

`REVIEW_BATCH.json` 的 `must_decide[]` 会把这些问题连同证据与默认值列出来。

## 输入

| 来源 | 说明 |
|---|---|
| `/input/case.json` | 案例合同：`case_id`、`output_contract`、`required_fields`、`figure`（id/kind/canvas）等。**原样保留，不增删键** |
| `/input/task.md` | 任务说明（只作 `role=metadata`，不得当科学正文） |
| `/input/**` 其它文件 | 真实材料：`.md/.txt/.csv/.tsv/.json/.tex/.pdf/.docx/.pptx/图片` 等 |

材料不足时：`prepare` 仍会写出一份 `status=needs_human` 的 `result.json` 并返回 3，**不会**用领域常识补造数据。

## 输出

`/app/output/`（正式交付；全部为本轮真实产出）

| 文件 | 作用 |
|---|---|
| `figure_model.json` | **可继续编辑的源文件**（实体/关系/图例/数据/溯源，见 `schemas/figure_model.schema.json`） |
| `figures/figure.svg` | **主源文件**：7 个命名图层、文字为真 `<text>`、每个元素带 `id` 与 `data-prov` |
| `figures/figure.pdf` `.png` `.tiff` `.eps` | 目标导出件（真实生成；不可用的格式如实标 `unavailable`） |
| `preview/figure.png` (+`preview/README.md`) | **供人工检查的渲染预览**：运行契约要求"real rendered PDF/PNG previews for inspection"，导出件在 `figures/`，这里再放一份同名 PNG 副本并以 `preview/README.md` 说明，避免评审去猜哪个文件是预览 |
| `source_map.json` | 每个图面元素 → 来源 `{path,locator,quote}` 或显式 `unsupported` |
| `change_log.json` | 来源保留式编辑的 before/after、理由与来源引用 |
| `export_report.json` / `checks.json` | 导出的真实后端、版本、DPI、字体与逐项合规检查 |
| `result.json` | **一次运行的完整回执**：含原 `output_contract` 全字段、`case_id`、`status`（`ok\|partial\|needs_human`）、`sources`、`uncertainty`、`limitations`、`audit`、`artifacts` |

`/app/work/`（中间证据，不必提交）：`case_manifest.json`、`source_inventory.json`、
`figure_model.draft.json`、`REVIEW_BATCH.json`、`figure_model.json`、`figure_issues.json`、
`layout.json`、`environment.json`、`edit_ops.json`。

## 五道门禁（判据可执行，不通过就不算完成）

1. **溯源门禁** — 每个实体/关系/图例项/标题/子图说明都必须有 `source{path,locator,quote}`，且
   `quote` 能在 `source_inventory` 的对应单元里逐字找到（空白归一化）。错误码
   `E_PROVENANCE_MISSING / E_QUOTE_NOT_FOUND / E_LABEL_NOT_IN_SOURCE / E_NUMBER_NOT_IN_SOURCE`
   —— 这是对「图里出现来源中不存在的基因名、浓度、时间点或单位」的直接拦截。
2. **方向与结构门禁** — 关系必须有 `type`（`activation|inhibition|containment|sequence|causation|association|membership`）
   与 `direction`，且与来源句中的动词线索一致：`E_DIRECTION_UNSUPPORTED`（抑制画成激活、上游下游颠倒）、
   `E_CONTAINER_CYCLE`（包含关系成环）、`E_ORPHAN_RELATION`（悬空端点）、`E_DANGLING_REF`、`E_DUP_ID`。
   绘图语法固定：激活=实线箭头，抑制=实线平头（⊥），包含=外框包裹，并列=同层不连线。
3. **图例—数据门禁** — 图例分类数 = 数据分类数，颜色/标记与数据系列一一对应，数值列必须有单位：
   `E_LEGEND_DATA_MISMATCH / E_UNIT_MISSING`。数据表是唯一权威，任务书或旧图注与表冲突时以表为准并记入 uncertainty。
4. **版式门禁** — 节点不重叠、不出画布、文字不溢出、层级不倒退：
   `E_NODE_OVERLAP / E_OUT_OF_CANVAS / E_TEXT_OVERFLOW_EST / E_LEVEL_REGRESSION`。
5. **导出门禁** — 真实检查分层数、可编辑文字、字体内嵌、位图 DPI、最小线宽、色彩空间、
   文件可解析性与 PDF 文本可抽取：见 `checks.json`，任一 `level=error` 为假即不通过。

## 异常处理（明确可预期的边界）

| 情况 | 行为 |
|---|---|
| 输入目录不存在 / 不可读 | `exit 3`，`result.json` 写 `needs_human`，不崩 |
| 材料无法解析出任何文本或表格 | `prepare exit 3`，草稿为空 + 写明缺什么 |
| 模型 JSON 非法 / 路径越界 | `exit 2`，stdout JSON 带 `error` |
| 模型有错误级溯源/方向/图例问题 | `render exit 4`，仍写 `figure_issues.json` 与已渲染的部分产物 |
| 导出后端缺失（如无 matplotlib） | 该格式 `status="unavailable"` + 真实原因；**绝不伪造文件**，其余格式照常产出 |
| PDF 有未内嵌字体 / 位图 DPI 不足 | `export exit 4`，`checks.json` 指出具体项 |
| 编辑操作非法（未知 op、目标不存在、重复 id） | `edit exit 2`，不产出半成品改动记录 |
| 重复运行 | 布局与渲染确定性：同输入 → 同字节 SVG（`--work` 会复用已存在的模型） |

**不能只看退出码**：每个阶段 stdout 是一个 JSON，须继续读其中的 `status` 与 `errors`。

## 目录结构

```
SKILL.md                  本文件
README.md                 安装、依赖、字体、参数、边界
manifest.json             资源清单与版本
scripts/common.py         共享件（IO/哈希/单位/依赖探测/退出码）
scripts/ingest.py         材料发现、来源单元与表格抽取、REVIEW_BATCH
scripts/model.py          草稿模型、五道门禁中的 1–3、保守 auto_fix
scripts/layout.py         确定性分层布局
scripts/render_svg.py     分层可编辑 SVG 渲染
scripts/export.py         PDF/PNG/TIFF/EPS 真实导出 + 期刊预设
scripts/compliance.py     导出合规检查
scripts/run.py            单入口编排（prepare/render/export/edit/finish）
scripts/selftest.py       自测：正例 + 注入缺陷
schemas/                  figure_model / edit_ops / review_batch 合同
references/               抽取规则、布局与 SVG 合同、导出与合规、结果合同
examples/                 最小调用示例（**示例**，非正式案例答案）
```

## 自测

```bash
python "$SKILL/scripts/selftest.py"        # 退出码 0 才算通过（含真实渲染与导出，非跳过）
```

## 门禁做什么、不做什么（两层，别混）

**第一层——机械可核验性（本 Skill 负责，可执行、有错误码）**：图里每个元素是否指得回一条逐字来源、
关系方向是否与来源动词一致、图例与数据是否逐项对应、版式是否自洽、导出件是否满足期刊参数。
这一层只能证明"**没有无依据的断言**"，**不能**证明科学结论正确。

**第二层——科学判断（Agent / LLM Judge 负责，不入本 Skill 的错误码）**：实体身份是否成立、
该不该把这个过程画进机制链条、来源之间自相矛盾时以哪个为准。
这一层按如下路径**留痕**，而不是被门禁替代：

| 判断发生在 | 记录在哪 | 谁可复核 |
|---|---|---|
| `prepare` 之后 | `REVIEW_BATCH.json` 的 `must_decide[]`（问题 + 依据 + 默认值，≤12 条） | 任何人读该文件 |
| `draft_model` 的每个猜测 | `figure_model.draft.json` 的 `uncertainty[]` | 同上 |
| Agent 的最终裁决 | Agent 自己写的 `figure_model.json`（它的 `uncertainty[]` 与每个元素的 `source.kind: explicit\|derived`） | `validate_model` 会重新核对引文 |
| Agent 对最终结果的不确定性 | `result.json` 的 `uncertainty[]` / `limitations[]` | 任何人读该文件 |
| 人工确认的修改 | `change_log.json` 的 `entries[]`（op / before / after / reason / source_refs） | 逐条 diff |

因此 `E_QUOTE_NOT_FOUND`、`E_LABEL_NOT_IN_SOURCE` 这类**阻断**的含义是"这个断言没有来源支持"，
**不是**"这个论断科学上正确"。**逐字引文核对是溯源手段，不替代科学判断**；组织方修订也明确
"scientific judgement remains native/LLM Judge"。材料自相矛盾时，正确做法是写入 `uncertainty`
并让 `status` 降级，而不是在两层之间选一个硬编。

## 边界与诚实性

- 不联网；只用 Python 3 标准库（第三方按可用性探测，缺失如实记录）。
- 科学判断由 Agent/评审负责：本 Skill 保证**可核验性**（每个图面元素都能指回来源、每处方向都有动词依据），
  不代替领域专家裁决材料本身的错误；材料自相矛盾时写入 `uncertainty` 并降级状态，而不是二选一硬编。
- 不虚构评测分数、不虚构工具版本、不把未生成的产物写进 `result.json`。
