# 抽取规则（extraction_rules.md）

本文件规定 `scripts/ingest.py` 与 `scripts/model.py` 的抽取口径，以及 Agent 在
`prepare` 与 `render` 之间必须做的人工裁决。**它是门禁的实现说明**：`validate_model`
的每条错误码在这里都能找到对应规则。修改本文件必须同时改代码并重跑
`work/dev/ingest-model/smoke.py`。

---

## 1. 定位符（locator）约定

| 材料类型 | locator | 含义 |
|---|---|---|
| 文本 / metadata | `L12` | 第 12 行（1 起算，`source_inventory.units[].line`） |
| 文本（范围） | `L12-L18` | 第 12–18 行；`find_quote` 会把该范围的各单元并入查找 |
| 表格 | `table:<列名>` | 该列的**表头与全部单元格**；不写列名时按整表匹配 |
| PDF | `p3` | 第 3 页（按 `/Type /Page` 出现次序推断） |

**PDF 的分层降级（诚实优先）**：优先用 `pypdf`（若可导入）；否则用**标准库兜底**——
只解未压缩与 `FlateDecode` 的内容流，只取 `Tj`/`TJ` 的字符串（十六进制串按 UTF-16BE 解）。
**不解码**：LZW/DCT/JPX 等滤波、加密 PDF、Type0/CID 自定义编码、扫描件图像层——
这些一律记 warning 并跳过，绝不猜测内容。任何 PDF 只要有文字层被兜底解出，就会记
`extractors[].status="partial"` **并写一条 warning**，Agent 引用前必须核对覆盖度。
| 图 | `fig:1` | 图内编号（当前不自动产生单元） |

`source_inventory.units` 对文本**逐行**建单元（非空行），因此一个跨多行的引文只要
落在同一文件里就能命中：`find_quote` 依次尝试 *精确 locator → locator 范围 →
整文件 → 整表 → 指定列*。命中即算通过；**绝不因为 locator 粒度粗就放行不存在的文字**。

`case.json` / `task.md` / `environment/resources.yaml` 的 `kind`/`role` 是 `metadata`，
**不得当作科学正文**：`draft_model` 不从 metadata 抽取实体或关系（只用它生成标题）。
metadata 行仍进入 `source_inventory`，因此可以被 `quote` 引用（例如任务书里逐字给出的
图题），但实体/数值的门禁会优先依赖材料文件。

## 2. 引文匹配（quote）——宽松归一化，绝不做模糊匹配

`normalise_text()` 做四件事，然后做**子串**查找：

1. 全角 ASCII（U+FF01–FF5E）→ 半角；
2. 标点归并：`。→.`、`、→,`、`《》→<>`、`【】→[]`、`“”‘’→"'`、
   各种破折号（`‐‑‒–—―−`）→`-`、`…→.`、`·•・→.`、`×→x`；
3. 去掉**所有**空白（含 U+3000、U+00A0）——这正是"容忍 CJK 空格/断行"的实现；
4. `casefold()`（大小写不敏感）。

只做**归一化后的精确子串**匹配。**禁止**编辑距离、同义词、词干化、"意思相近"等模糊
匹配：把 `抑制` 匹配成 `促进` 会让反幻觉门禁失效。归一化后的 `TRPM7` 命中
`trpm7`，但 `TP53` 不会命中 `TP63`。

**引文取法必须逐字**：`draft_model` 用子句/行切片，禁止在引文里加省略号 `…`
（那会让引文在原文件中找不到）。需要截断时用**原文字符串的前缀切片**。

## 3. 生物动词词典与方向判定

`ingest.VERB_LEXICON`（唯一实现，本表是它的文档）：

| 关系 `type` | 线索动词 |
|---|---|
| `activation` | 激活、促进、诱导、上调、磷酸化、增强、激动、活化 / activate(s), promot(e|es), induc(e|es), upregulat(e|es), phosphorylat(e|es), enhanc(e|es) |
| `inhibition` | 抑制、阻断、下调、去乙酰化、负调控、沉默、敲低、拮抗 / inhibit(s), suppress(es), block(s), downregulat(e|es), repress(es), deacetylat(e|es), knockdown |
| `containment` | 包含、属于、构成、组成、分为、归入、包括 / contain(s), consist(s), compris(e|es), belong(s) |
| `causation` | 导致、引起、因此、从而、致使、造成 / caus(e|es), lead(s) to, result(s) in, thereby |
| `sequence` | 上游、下游、随后、进而、接着、之后、先于 / upstream, downstream, subsequently, followed by |
| `membership` | 属于、归入、归类、成员 / belong(s) |
| `association` | 关联、相关、结合、相互作用、互作 / interact(s), associat(e|es), bind(s) |
| 双向（`direction`） | 双向、相互、互相、互为 / bidirectional, mutual |

**判定规则（`E_DIRECTION_UNSUPPORTED`）**：从 `source.quote`（引文为空时退化为该单元的
全部文字）里抽取线索集合，然后

- 只要断言的 `type` 出现在线索里 → 通过；
- `type ∈ {activation, inhibition, containment, causation, sequence}` 且线索集非空、
  却不包含断言的 `type` → **错误**（例：来源写"抑制 CASP3"，模型写 `activation` → 报错。
  这是本题最重的失分形态）；
- `association` / `membership` 不参与该判定（弱语义，线索可有可无）；
- 引文里**完全没有任何线索动词** → 不报错（无法证伪），但 Agent 应补一条更具体的引文；
- `direction="bidirectional"` 要求引文里出现双向线索；引文出现双向线索而
  `direction="forward"` → 同样报错。

**一句话多动词时取"夹在两个不同实体之间的那个动词"**（`cue_pos` 选择）：例如
`活化的 CREB 促进 BCL2 转录` 中的 `活化` 只是状态形容词，真正的动词是 `促进`。
`draft_model` 用"能同时在该位置之前/之后各留一个不同实体"的线索位置作为主谓位置；
一个都不满足时退化为最左（`containment` 用最右，因为模式是 `组名 + 包含 + 成员…`）。

## 4. 实体与关系抽取（`draft_model` 的启发式）

- **实体**：材料文本里的拉丁符号（基因/蛋白/化合物，如 `TRPM7`、`2-APB`、`OGD/R`）+
  表格中低基数非数值列的取值（`category`）+ 受控的中文名词（`…模块/通路/过程/因子/组/样本/细胞`，
  且不含虚词与动词线索）。metadata 与 markdown 标题不参与抽取。
- **关系**：在子句里找线索动词与实体，子句先按 `。；!?` 与**全角/半角逗号**切分；
  只有 1 个实体时，用同一单元内**前一个**实体作主语（`进而激活 CAMK2` ⇒ 上一句的 TRPM7）。
  同一实体对 + 同一 `type` 只保留一条。
- **包含关系**：`<组名>包含/归入/分为 <成员…>` 生成 `containers`，成员是子句里的全部实体；
  组的成员若在后续被证明不是实体（中文散文候选），会被剔除，成员为空的组被丢弃。
- **图例与数据**：表格的第一个 key 列做分类，数值列做 y，另一个 key 列做 x；每个分类一条
  `category` 图例，颜色与 `data.series[].color` **同源同序**；存在激活/抑制关系时补一条
  `line_style` 图例。
- **单位**：表头括号（`dose (mg/mL)`）→ `data.units`；表头无单位时找紧随表头的单位行，
  再从单元格里识别常见单位。**找不到就留空并写 uncertainty**，绝不自造单位。

**草稿不是答案。** 每个启发式结论都必须同时写进 `model["uncertainty"]`（`where`/`issue`/`action`），
真正无法机器裁决的问题进 `REVIEW_BATCH.json` 的 `must_decide`（最多 12 条，含候选与建议默认值）。
宁可交一个标了 `unsupported`/`derived` 的诚实元素，也不要编一条引文。

## 5. 溯源等级（`source.kind`）

| kind | 要求 | 门禁行为 |
|---|---|---|
| `explicit` | `path`+`locator`+**非空逐字 `quote`**，且 quote 能在该来源命中 | 全量校验（标签、数值、单位、方向） |
| `derived` | `path`+`locator`+`derived_from[]`（列出综合了哪些来源）；有 quote 则同样必须命中 | 同上；`derived_from` 为空 → `E_PROVENANCE_MISSING` |
| `unsupported` | 显式声明"无来源" | 标签/数值/方向不再断言，降级为 `W_UNSUPPORTED_STYLE` 警告；**不得**当作证据展示 |

`E_PROVENANCE_MISSING` 还覆盖：没有 `source` 对象、`path` 为空、`locator` 为空
（schema 要求 `path`+`locator`+`kind`）、`path` 不在 `source_inventory` 里、
`kind` 不在枚举内。

## 6. 门禁清单（`validate_model`）

**错误级**

| 码 | 触发条件 |
|---|---|
| `E_PROVENANCE_MISSING` | 见 §5 |
| `E_QUOTE_NOT_FOUND` | `explicit` 引文为空，或引文在指定来源（含整文件/整表回退）里找不到 |
| `E_LABEL_NOT_IN_SOURCE` | 实体/容器/图例标签（去掉 `（…）` 等装饰后的核心）在**整个** source_inventory 里都不出现 |
| `E_DIRECTION_UNSUPPORTED` | §3 |
| `E_UNIT_MISSING` | 数值列既不在 `data.units` 也不在每个 `series.unit`；或实体数值无 `unit` |
| `E_LEGEND_DATA_MISMATCH` | 图例 `category` 条数 ≠ 数据分类数；某 series 无对应图例项；图例色 ≠ series 色 |
| `E_ORPHAN_RELATION` | 关系的 `from`/`to` 不是已定义实体（箭头悬空） |
| `E_DUP_ID` | 同一命名空间内 id 重复（entities / relations / containers / legend / panels 各自判定） |
| `E_CONTAINER_CYCLE` | 容器成员里嵌套容器并形成环（含自环） |
| `E_DANGLING_REF` | `entity.container` 指向不存在的容器；`container.members` 既不是实体也不是嵌套容器 |
| `E_NUMBER_NOT_IN_SOURCE` | 标签/标题/图例/数值里出现的数字（含数据表单元格）在 inventory 中找不到（字符串命中或数值相等） |
| `E_CONTRACT_KEY_MISSING` | 缺顶层必填键、`figure.{id,kind,canvas}`、元素必填键、用例外的枚举值、或 `kind="chart"` 却没有任何 `data.rows`/`data.series` |

**警告级**：`W_AMBIGUOUS_LEVEL`（关系指向的层级 ≤ 起点层级）、`W_LONG_LABEL`
（标签 > 40 字符，标题 > 80）、`W_NO_PANEL_ID`、`W_COLOR_NOT_IN_PALETTE`、
`W_UNSUPPORTED_STYLE`（含 `kind=unsupported`）、`W_EMPTY_LEGEND`（有 series 无图例）。

`strict=False` 是**草稿档**：结构性/溯源错误照报，但 `E_LABEL_NOT_IN_SOURCE`、
`E_NUMBER_NOT_IN_SOURCE`、`E_UNIT_MISSING`、`E_LEGEND_DATA_MISMATCH` 延到 Agent 修订后再查。
`render` 必须用默认 `strict=True`。

## 7. `auto_fix` 的边界

只做四件事，且每件都写进 `uncertainty`（并打 stderr 日志）：
① 补缺失 id（由 label slug 生成，冲突则加序号）；② 去重 id（改**后出现**的那个，
既有引用仍指向原 id，不被静默改指）；③ 悬空引用**直接丢弃**该关系/成员/容器引用；
④ 溯源错误降级为 `kind="unsupported"`。

**绝不**：发明来源、补造引文、改动 `type`/`direction`、把 `unsupported` 升格为 `explicit`。

## 8. Agent 如何填 `REVIEW_BATCH.json`

1. 读 `materials[]`（每段 ≤600 字符，总计 ≤24000；截断项在 `limits.truncated_segments`，
   被截断时**直接读原文件**，不要凭空补全）。
2. 逐条回答 `must_decide[]`，每条都要落到具体 `quote`；`suggested_default` 只是默认值，
   材料与之冲突时以材料为准。
3. 把答复写回 `figure_model.draft.json` 并另存为 `/app/work/figure_model.json`
   （**不要覆盖草稿**，便于对比）。
4. 自检：对 `figure_model.json` 跑 `strict` 校验，把 `figure_issues.json` 里的错误级问题清空。
5. 拿不准的元素标 `unsupported`/`derived` 并在 `uncertainty[]` 里写明，**不要**删掉诚实的不确定项。

## 9. 本地验证

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONDONTWRITEBYTECODE='1'
& $PY work\dev\ingest-model\smoke.py     # 期望 exit 0：86 项全绿
```
覆盖：示例输入全链路、`expected_model.json` 0 错 0 警、15 条注入缺陷逐一命中对应错误码、
图表案例（表头单位 / 图例-数据一致 / 草稿直接过 strict 校验）、缺失单位不被编造、
引文归一化语义（全角/半角、CJK 空格、大小写宽容；不同词与近似基因名**必须**拒绝）、
垃圾模型模糊测试不崩、PDF 兜底解析与加密/不支持滤波的诚实跳过、空/缺失/坏编码输入树不崩、
`auto_fix` 不改语义、不写输入树。
