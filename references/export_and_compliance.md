# 导出与合规（`export.py` / `compliance.py`）

> 本文件说明 Skill 的第四道门禁：**真实导出 + 期刊合规检查**。接口冻结在
> `work/CONTRACT.md` §4.6；本文件只描述实现与判据，接口以合同为准。

## 0. 一句话原则

**只产出真实文件，只报告真实结论。** 工具缺失、几何缺失、色彩空间无法满足时，产物条目记
`status="unavailable"`（后端缺失）或 `status="failed"`（渲染失败）并写明 `error`；
**绝不写占位文件、绝不把 SVG 改名成 `.pdf`、绝不把"没检查"写成"通过"**。

## 1. 冻结 API

```python
# export.py
available_tools() -> dict
export_all(model, layout, svg_text, out_dir, spec, *, work_dir=None) -> dict
journal_preset(name) -> dict

# compliance.py
check_artifacts(paths, spec, *, model=None) -> dict
```

### 1.1 `available_tools()`

每次调用都**重新探测**（编译环境可能与作者机不同），返回：

| 键 | 内容 |
|---|---|
| `modules` | 逐模块 `{available, version}`：matplotlib / PIL / pypdf / lxml / numpy / cairosvg / svglib / reportlab / PyPDF2 / PyMuPDF |
| `external_tools` | rsvg-convert / inkscape / gs / magick 的 `{available, path, version}`（走 `common.which` + `common.tool_version`） |
| `svg_rasterisers` | 实际可用的 SVG 直接栅格化器（cairosvg → rsvg-convert → inkscape 优先级） |
| `pdf_inspector` | `pypdf`，缺失时退 `PyMuPDF`，都缺失为 `None` |
| `usable` | 每种格式实际会被谁产出（`svg` / `pdf` / `eps` / `png` / `tiff`） |
| `notes` | 人类可读的降级说明 |

PyMuPDF **只做存在性探测、不 import**：某些构建在 import 时向 **stdout** 打印弃用告警，会污染
`run.py` 「stdout 单 JSON」的契约。

### 1.2 `export_all()`

返回 `{"formats":[{format,path,rel,bytes,sha256,dpi,color_space,producer,status,error,...}],
"tools":{...}, "render":{...}, "warnings":[...], "ok":bool, "canvas":{...}, "spec":{...}}`。

- `svg`：把传入的 `svg_text` **逐字节写出**（`producer="passthrough (byte-identical master source)"`；
  测试用 sha256 断言相等），不经过 matplotlib 往返。
- `pdf`/`eps`/`png`：matplotlib 从 **model+layout 几何重绘**（容器、normal/tee 箭头、节点、图例、
  坐标轴），不是把 SVG 光栅化。`pdf.fonttype=42`、`ps.fonttype=42`、`svg.fonttype='none'`。
  **重绘逐字段采用 layout 的样式**，与主 SVG 逐项一致：`nodes[].fill/stroke/line_h_mm/lines`、
  `edges[].points_mm/color/width_pt/stroke/head_start/head_end/label_pos_mm/label_w_mm`、
  容器 `#F5F8FB`/`#8C97A3`(rx 2.2)、图例 `items[].color/kind/marker/glyph_*`/`text_x_mm`、
  图表 `chart.plot/x.ticks/y.ticks/bar/series[].points`。几何常量（箭头 4.4×2.1 uu、tee 4.2 uu、
  虚线 2.6/1.8 uu）与 `render_svg.py` 同源，保证 PDF/PNG 与 SVG 是同一张图。
  只有 layout **没给**字段时才退回 model 调色板/直线连接，并在 `warnings` 里写明降级。
- `tiff`：Pillow 写入，LZW 压缩 + 显式 `dpi=(dpi,dpi)`；`spec.color_space=="CMYK"` 时写 **真 4 通道
  CMYK TIFF**。
- `spec.formats` 里出现本模块不认识的格式 → 该条目 `status="unavailable"`，
  `error="unsupported export format ..."`，不静默丢弃（例如 `xps`）。

**尺寸**：`figsize` 由 `canvas.width_mm/25.4` 决定；PNG 保存前临时把尺寸设为
`px/dpi`（`px = round(mm/25.4*dpi)`），因此像素**恰好**是所需值（180 mm @300 dpi → 2126×1417 px），
导出后恢复英寸尺寸，使矢量件的物理尺寸仍精确。

**图例/三角标记/线宽**：线宽取自 `model.figure.style.line_widths_pt`，低于
`spec.min_line_width_pt` 时**抬到下限并记 warning**（不静默违规）。

**字体**：逐条文本用 `font_manager.findfont` + `ft2font.get_char_index` 真实探测字形覆盖，
拉丁栈不覆盖 CJK 时切到已安装的 CJK 字体（Microsoft YaHei / SimHei / Noto Sans CJK…），
避免 PDF/PNG 出现缺字方块（例：标题「OGD/R 下 TRPM7–…」在 DejaVu Sans 下会缺字）。

**数据图**：优先使用 `layout["chart"]`（`plot{x,y,w,h}` + `x/y.ticks` + `series[].points[]`），
其次 `layout["panels"]`（需含 x/y/w/h）。layout 未分配绘图区时**不发明几何**，只记 warning
"the data chart was NOT drawn (refusing to invent geometry)"。数据只画 `model.data.series` 里的值。
**柱状图基线**：条形从 `chart.bar.baseline`（默认 0，经 `y.ticks` 的值→位置映射成 mm；无映射时退回 plot 底边）
向两侧生长——正值向上、负值向下，与渲染器把 0 留在值域内、`data-baseline="0"` 的做法一致；
`test_negative_bars.py` 用含负值的模型验证（2/2 负值柱向下、0 个塌缩成细条）。

**PNG 栅格化优先级**：cairosvg → rsvg-convert → inkscape → matplotlib 重绘。用了哪个写进
`producer`，并校验像素尺寸，不符则回退 matplotlib 并记 warning。

**输出位置**：`spec["subdir"]`/`spec["stem"]` 可显式指定；否则若 `<out_dir>/figures/` 下恰有一个
`.svg` 主源文件（`run.py render` 的产物），就**沿用它的目录与文件名主干**，使
`figures/<stem>.{svg,pdf,png,tiff,eps}` 同名同处，`run.py finish` 能在 `figures/` 下登记全部产物。

### 1.3 附带助手：`locator_form_report(source)`（非冻结 API）

`compliance.locator_form_report(svg_path_or_text)` 校验 SVG 里**每一个** `data-prov` 的形式，
返回与渲染侧 `work/dev/layout-render/prov_form_scan.py` **逐元素可对齐**的结构，便于两侧 diff 而非逐文件比对：

```json
{"checked": 382,
 "src_kind_histogram": {"explicit": 174, "derived": 206, "unsupported": 2},
 "nonconformant": [
   {"element_id": "cnt:bad", "data_prov": "figure.legend#frame",
    "path": "figure.legend", "locator": "frame", "src_kind": "explicit",
    "problem": "locator 'frame' not in L12|L12-L18|p3|table:col|fig:1",
    "severity": "error"}],
 "ok": false}
```

`severity`：`explicit` → `error`；`derived`/`unsupported` → `warn`；合规记录 `problem=null, severity=null`。
`ok` 仅在存在 `severity=="error"` 时为 false。`check_artifacts` 的 `svg_provenance` 用同一份记录，
其 `evidence[<svg>].locator_format_errors / locator_format_advisories / provenance_records_checked` 直接给出该结构。
实测：example 53 / case-b 180 / gold-case-a 36 / grammar 19 / dense30 94 = **382 个属性，0 不合规**，
与 layout-render 的 394 属性 / 0 不合规（7 个夹具，多出的部分含 case-c）结论一致。

### 1.4 `journal_preset(name)`
`nature|science|cell|ieee|generic`（另有 `nat/sci/cell_press/cellpress/iee/default` 别名），
返回**副本**（可安全改动）。每个数值都带 `source`（依据出处）与逐字段 `field_basis`：
能公开核对的写"published guideline (...)"，不确定的写
`"conservative default (verify against journal guidelines)"`（取更严格的一侧）。
未知名字 `die(..., CONFIG)`（exit 2），不静默回退。

| 预设 | 单栏 mm | 双栏 mm | 光栅 dpi | min 线宽 pt | 色彩 | 最大高 mm | 依据 |
|---|---|---|---|---|---|---|---|
| nature | 89 | 183 | 300 | 0.5★ | RGB | 247★ | Nature 图稿规范：89/183 mm、300–600 dpi、5–7 pt 文字（★ 为保守值） |
| science | 55 | 120（全页 183） | 300 | 0.5★ | RGB | 240★ | Science 图稿规范：55/120/183 mm、≥300 dpi |
| cell | 85 | 174 | 300 | 0.5★ | RGB | 240★ | Cell Press 图稿规范：85/174 mm、≥300 dpi |
| ieee | 88.9 | 181.8 | 300 | 0.5★ | RGB | 240★ | IEEE：3.5 in/7.16 in、≥300 dpi（线画 600 dpi） |
| generic | 180 | 180 | 300 | 0.5 | RGB | 240 | `conservative default (verify against journal guidelines)` |

★ 标注的字段在 `field_basis` 里逐条写为保守默认值。**不编造引用**：不确定就取更严格的值并标注。

## 2. `check_artifacts(paths, spec, *, model=None)`

`paths` 接受：路径列表、`{format: path}`、`export_all()["formats"]` 那样的条目列表、或一个目录。
返回 `{"checks":[{id,level,ok,detail,evidence}], "ok":bool, "summary":{...}, "spec":{...},
"canvas_used":{width_mm,height_mm,source}}`。

`ok = 所有 level=="error" 的检查都 ok`；`level=="warn"` 只作提示，不否决提交。

### 2.1 「请求尺寸」vs「实际绘制尺寸」（`canvas_used`）

布局可以**合法地放大画布**（`layout.stats.canvas_adjusted`，最多 ×2），此时 `model.figure.canvas`
只是**请求尺寸**。因此物理尺寸类判据（`raster_dpi` 的像素↔物理换算、`pdf_page_size` 的
`/MediaBox`）一律以**实际绘制尺寸**为准，取值优先级：

1. `spec["canvas"]` / `spec["layout_canvas"]`（调用方显式传布局画布，最权威）；
2. 渲染主 SVG 的根 `width`/`height`（渲染器就是按它画的）；
3. `model.figure.canvas`（仅在没有任何产物可参照时兜底）。

请求尺寸与绘制尺寸不一致时，只在 `raster_dpi` / `pdf_page_size` 里记 **advisory**（`level="warn"`、
`ok=true`，写明「requested … drawn …」），不否决投稿——图变大不等于违规；但**像素真的不够**
（例如画布放大而光栅没放大）仍然判 error。

| id | level | 判据（都是真读文件，不是看文件名） |
|---|---|---|
| `format_coverage` | error（缺 svg/pdf/png）/ warn（缺 tiff/eps） | `spec.formats` 与实到文件对比 |
| `artifact_nonempty` | error | `bytes>0` 且**魔数匹配扩展名**：`%PDF-`、`\x89PNG`、`II*\0`/`MM\0*`、`%!PS`、SVG 含 `<svg`。SVG 改名成 `.pdf` 在此被抓 |
| `svg_layers` | error | XML 解析后统计 `g[id^="layer:"]`（或 `data-layer`），要求 ≥6 |
| `svg_editable_text` | error | `<text>` ≥1；统计 `<image>`，**仅允许**出现在 id/`data-role` 含 `chart|raster` 的祖先组内；检测 `data-role/class` 含 text/glyph 的 `<path>` 或 `id` 以 `text:/txt:/glyph:` 开头者＝文字转路径。同时报告 `font-family` 列表 |
| `svg_provenance` | error | 统计 `data-prov` 数量 ≥ 期望值：关系示意图 = entities+relations+containers+legend；`figure.kind=="chart"` = legend+数据点数+panels（图表里实体是坐标类别，不是方框）。可寻址 id（`ent:/rel:/lg:/cnt:`）不足只作 warn。**并校验 `data-prov` 的形式**：`<相对 POSIX 路径>#<locator>`，locator ∈ `L12｜L12-L18｜p3｜table:col｜fig:1`（CONTRACT §4.7），路径不得为绝对/反斜杠/含 `..`；`data-src-kind="explicit"` 的元素形式不合法 → **error**（"我在来源里"的声明无法核验＝反幻觉核心），`derived`/`unsupported` 的形式问题 → warn（占位符，例如装饰性 legend frame）。`(none)#(none)` 仅作为无来源元素的占位接受 |
| `svg_legend_color_map` | warn（advisory） | 图例色块 ↔ 图面颜色一致性。对每个有 `value` 的图例项，收集它**可能描述**的已画颜色并逐一比对，任意一个命中即通过：① `series:N` 组声明的 `data-legend="<图例 id>"`（图表用，`data-color`）；② `rel:<id>` 组的 `data-rel-type` 与 value 同名（线型图例映射到关系色）；③ `ent:<id>` 方框的 fill/stroke（关系示意图），或声明 `data-entity` 的 series；④ 唯一颜色匹配兜底。只有**所有**候选都不等于色块时才报 mismatch，避免"实体名恰好与关系类型同名"这类假阳性；完全无法解析则记 unresolved（仍为 advisory，不静默通过）。
| `svg_edge_direction` | **error** | **方向反了没有**：解析每个 `rel:<id>` 组的 polyline 与箭头/平头几何，取其尖端（箭头三角的首点、tee 横杠中点），从 `<g id="ent:…">` 方框算节点中心；对 model 标为 `forward` 的关系，尖端必须**离 `to` 比离 `from` 更近**，`data-head-end/head-start` 声明了头却没有几何也判违规。这是赛题点名的致命失败类（「抑制画成激活、上下游颠倒 / 负反馈画反」），且是唯一能在**产物**层面看见它的判据，故按防御性纵深定为 error（CONTRACT §5.2 的结构门禁仍负责模型层判定，这里不替代而是兜底：手改 SVG 或未来渲染器改动动了箭头，导出闸门不会静默放行）。对合法形状刻意宽容：`head_end/head_start="none"`（association/containment 无头）不比较；`direction="bidirectional"` 每端各自与自己的节点比，两个头都通过；路由折返的反馈弧只看尖端到两个节点中心的距离、与折线形状无关。实测（`test_edge_direction_shapes.py` 8 种合法形状 + `test_edge_direction.py` 正例）全绿；人造"箭头插在源端"SVG 判 error 并让整闸门 `ok=false` |
| `line_width_min` | error | 解析 `stroke-width`（含 `style="stroke-width:…"`），按根 `width`(mm)/`viewBox` 或内嵌 `<metadata>` 的 canvas 求 mm/用户单位（无 viewBox 时＝1 CSS px＝1/96 in），并累乘祖先 `scale/matrix` 的尺度，换算成 pt 后要求 ≥ `spec.min_line_width_pt` |
| `raster_dpi` | error | 读**真实 DPI 元数据**（PNG `info['dpi']`/pHYs、TIFF tag 282/283/296），要求 ≥ `spec.dpi`；并用像素尺寸反推物理尺寸与**实际绘制画布**比对（容差 3%）。实测像素宽度不足也报错。元数据缺失但像素足够 → warn（物理分辨率未声明） |
| `raster_opens` | error | `PIL.Image.open` + `verify()` + 重新 `open().load()`；截断 PNG 在 verify 阶段被抓 |
| `pdf_opens` | error | `pypdf.PdfReader`，页数 ≥1、未加密；损坏 PDF 在此失败，后续 PDF 检查**跳过并写明原因** |
| `pdf_fonts_embedded` | error | 遍历每页 `/Resources /Font`（含 Form XObject 递归）；Type0 走 `/DescendantFonts`；要求每个字体有 `/FontFile`/`/FontFile2`/`/FontFile3`；无字体（纯图片）也算失败（文字不可编辑） |
| `pdf_page_size` | error | `/MediaBox` 换算 mm 与**实际绘制画布**比对（容差 3%），并检查是否超过预设 `max_height_mm` |
| `pdf_text_extractable` | error（一个都取不到）/ warn（部分缺失） | `extract_text()` 归一化空白后匹配**主 SVG 真正画出的标签**：有 SVG 时只要求它实际绘制的 `<text>` 内容出现在 PDF 中——`kind=chart` 图不会因为 ingest 草稿里那些"没有图面位置"的实体标签而被判缺失；没有 SVG 时退回 model 标签（实体/关系/图例/容器/系列名/单位/标题）。PDF 文字被转成轮廓或图片 → 一个都取不到 → error |
| `eps_fonts_embedded` | error（`font_embedding_required`）/ warn | EPS 内外嵌字体证据：`%!PS-TrueTypeFont` / `%BeginFont`/`%BeginResource: font` / `/FontFile`；缺失时列出引用到的字体名 |
| `color_space_declared` | error（显式要求 CMYK 而实为 RGB）/ warn（未声明/不一致的其它情形） | SVG：`<metadata>` 的 `color_space` 或 `sRGB` 标记；PNG/TIFF：PIL mode（CMYK 判 photometric）；PDF：未压缩标记 + **解压内容流**里的 `/DeviceRGB`/`/DeviceCMYK`/`ICCBased` 与 `rg/RG/k/K` 算子（要求算子前有数字操作数，避免正文字符串误报）；EPS：`setrgbcolor`/`setcmykcolor` |

约定：**请求了但没给**该格式的产物 → 该检查 `ok=false` 且 level 取决于该格式是否核心；
**根本没请求**该格式 → `ok=true, level="warn"`, `evidence.applicable=false`（不用假通过骗分）。
缺失文件、损坏文件都走"检查失败+detail"，**不抛异常**（`check_artifacts` 永不因输入崩溃）。
若 `spec` 是**字符串预设名**而名字不存在 → `SkillError(CONFIG=2)`（配置错误要显式报，不静默降级为 generic）。

## 3. 色彩空间：能做到什么、不能做什么（如实说明）

- **RGB**：全格式真实可产出（matplotlib PDF/EPS 是 DeviceRGB；PNG/TIFF 是 RGB）。
- **CMYK**：本机后端里**只有 Pillow 能写 CMYK**，因此 `spec.color_space=="CMYK"` 时：
  - TIFF → 真 4 通道 CMYK（`Image.convert("CMYK")`），条目带
    `color_conversion="naive_rgb_to_cmyk_without_icc"` 与 warning：**未附 ICC**，付印前需用印刷 profile 再转换；
  - PDF/EPS（matplotlib）与 PNG（PNG 规范不含 CMYK）**仍是 RGB** → 条目照实写 `color_space="RGB"`，
    `color_note` 说明原因；`check_artifacts` 的 `color_space_declared` 判 **error**（显式要求 CMYK 即硬要求）。
  - 未安装 Pillow 时 CMYK TIFF 记 `unavailable`，不伪造。
- **对"要求 CMYK 的期刊"的诚实口径（重要）**：本 Skill **不会**静默声称满足 CMYK 要求。若案例/期刊
  要求 CMYK，导出报告与 `result.json.limitations[]` 必须把"PDF/EPS/PNG 只能交付 DeviceRGB"写成
  **已知限制**，并把 `color_space_declared` 记为 error/limitation；未声明 `color_space="CMYK"` 时，
  `color_space_declared` 保持 **warn**（模型声明 RGB、产物也是 RGB，属一致而非违规）。
  即：**默认 RGB 走 warn，显式 CMYK 无法完全满足走 error + limitation**，不做隐式降级。

## 4. 已知限制 / 边界（不做假承诺）

1. **DPI 元数据量化**：PNG pHYs / TIFF XResolution 以"像素/米"存整数，300 dpi 往返成
   299.9994 dpi（≈0.002%），检查用 `max(0.1, dpi*0.001)` 容差，远小于任何真实欠分辨率。
2. **没有 SVG 直接栅格化器时**，PNG 是 matplotlib 重绘图，而非主 SVG 的像素级复制；
   `producer` 会写明走了哪条路。装上 cairosvg/rsvg-convert/inkscape 即自动优先使用。
3. **CJK 字形依赖系统字体**：目标机没有 CJK 字体时，PDF/PNG 里的中文会缺字；
   报告里会记 font_stack 与警告，SVG 主源文件仍保留可编辑 `<text>`。
4. **不检查 SVG 里被 `transform` 旋转的几何一致性**，只按祖先 scale/matrix 估算线宽尺度。
5. **`pdf_text_extractable` 的部分缺失是 warn**：布局把标签换行/合并（例如相邻文本被提取器连成
   `BCL2CAMK2`）会降低命中率；判据本身是"主 SVG 画出的文本必须能在 PDF 里抽取到"，因此
   `kind=chart` 图上那些没有图面位置的草稿实体标签**不会**被算作缺失（实测 case-b：5/5，
   此前按 model 全量算是 5/17 的假警报）。一个都取不到（文字被轮廓化/位图化）才是 error；
   负例里用 PIL 生成的纯图片 PDF 会被判 error。
6. 未安装 pypdf 时 PDF 三连检查记 `unavailable/跳过`，而不是"通过"。
7. **TIFF 只从本次渲染出的光栅生成**：单独请求 `tiff`（未请求 `png`）时，会先渲染一张临时 PNG
   （`common.make_temp_dir`，用完删除），**不会**复用输出目录里上一轮遗留的 `<stem>.png`，
   避免导出与模型不同步。
8. 若产物目录里已有同名旧文件而本轮该格式失败，条目记 `failed`/`unavailable`，**不会**把旧文件当成本轮产物上报。

## 5. 验证证据（本地实跑，可复现）

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; $env:PYTHONIOENCODING='utf-8'
cd <repo>/work/dev/export-compliance        # 开发用夹具，不在提交包内
py -3 harness.py all      # 工具探测 / 预设 / API 形状 / 真实 renderer / 图表 / 正例 / 文本 / 负例 / run.py 集成
```

harness 覆盖（全部通过时 exit 0）：

- **正例**：示例模型 → svg+pdf+png+tiff+eps 全部 `status=ok`；SVG sha256 与输入逐字节相同；
  `check_artifacts` `ok=true`（15 项检查）；pypdf `extract_text()` 命中 TRPM7/CAMK2/CREB/BCL2/CASP3/SIRT1/Vehicle（18/18 标签）。
- **真实 renderer**：`layout.layout()` + `render_svg.render()` 的 SVG（7 层、33 `<text>`、54 `data-prov`、0 `<image>`）
  → PDF 字体全部内嵌、页码尺寸 = 绘制画布、文本可抽取；`render` 事实 = 8 节点/5 边/2 容器/1 图/4 图例项。
- **样式一致性**（`test_fidelity.py`）：导出帧里 8/8 节点的 fill/stroke 与 `layout.nodes[].fill/stroke`
  **逐色相同**（1/255 容差），且 layout 的 fill/stroke 与主 SVG 的 `ent:` rect 属性零差异，边色零差异。
- **画布语义**（`test_canvas.py`）：把 `layout.canvas.height_mm` 从 120 改成 160（模拟 `canvas_adjusted`）
  后重新渲染 → 导出全 ok、`check_artifacts.ok=true`，`raster_dpi`/`pdf_page_size` 只报
  「requested 120.0 / drawn 160.0」的 advisory；同一画布下把光栅缩到 1/4 仍判 **error**。
- **负例（各自被点名检查抓住）**：
  - 72 dpi 光栅 vs 300 dpi 要求 → `raster_dpi` error；
  - reportlab 的标准 14 号 Helvetica PDF（字体内嵌不了）→ `pdf_fonts_embedded` error（`/Helvetica` 无 FontFile）；
  - 截断到 50% 的 PNG → `raster_opens` + `raster_dpi` error；
  - SVG 改名 `.pdf` → `artifact_nonempty`（魔数不符）+ `pdf_opens` error，其余 PDF 检查标注 skipped；
  - 缺失文件 → 相应检查 `ok=false` 并写明 missing file；
  - `spec.formats=["svg","png","xps"]` → xps 条目 `unavailable` + 原因；
  - 显式 CMYK → TIFF 真 CMYK，PDF/PNG 照实记 RGB，`color_space_declared` error；
  - `layout=None`（无几何）→ 只写 SVG，pdf/png/eps 记 `unavailable`+原因，**磁盘上没有任何假文件**；
  - `svg_text=None` → svg 记 `unavailable`，pdf/png 仍真实产出。
- **run.py 集成**：`run.py export --journal nature` → exit 0、`status=ok`、`failed_checks=[]`，
  产物落在 `output/figures/figure.{svg,pdf,png,tiff,eps}`；`run.py finish` 把它们全部登记进 `result.json.artifacts`。
- **TIFF 陈旧防护**（`test_tiff_only.py`）：只请求 `tiff` 时，先放一个伪造的旧 `<stem>.png`，
  导出仍用**本次**新渲染的临时光栅生成 TIFF（旧文件未被使用也未被覆盖），且输出目录不残留临时目录。
- **鲁棒性 fuzz**（`test_fuzz.py`）：空文件/截断/随机字节 PDF/畸形 SVG/把目录当文件/spec=None/整数 spec
  都不崩溃且 `ok=false`；未知预设名 → `SkillError(2)`；`export_all` 遇到非 dict 模型、非 str 的
  `svg_text` 抛 `SkillError(2)`，遇到无几何 layout 时全部记 `unavailable` 且**磁盘上零文件**
  （逐文件校验魔数，杜绝零字节占位）。

### 5.1 与其它模块的接口观察（写给 Lead，不是本模块可自行修改的）

- **`run.py` 阻塞已解除（2026-11-23 复核）**：`common.py` 增加了 `read_json = load_json` 别名
  （`common.py:104`），`run.py --help` 与 `run.py export/finish` 现在**直接**可跑。本模块的端到端集成
  因此改为直接调用 `scripts/run.py`（不再需要 `work/dev/export-compliance/run_wrapper.py`，
  该文件仅留作历史回退）：`run.py export --journal nature` → exit 0、`status=ok`、`failed_checks=[]`、
  16 项检查全过，产物落在 `output/figures/figure.{svg,pdf,png,tiff,eps}`，`run.py finish` 全部登记。
- `render_svg.py` 的主 SVG：`width="180mm" viewBox="0 0 680.315 453.543"`（1 用户单位 = 1 CSS px = 0.75 pt），
  最小描边 0.667 用户单位 = **0.5002 pt**，刚好压在 generic 预设 0.5 pt 下限上（余量 0.0002 pt）。
  渲染侧只要再取整或 lower 一点就会让 `line_width_min` 判 error —— 建议给 ≥0.68 用户单位留余量，
  或由 Lead 明确 presets 的下限口径。
- 图表几何已在 `layout["chart"]`（`plot{x,y,w,h}` + `x/y.ticks` + `series[].points[]`），
  导出与之同几何；若 layout 不分配 plot/panel，导出不画图（只告警，绝不发明几何）。
- **图例-颜色映射（layout-render 修复 + 导出侧检查器补齐，2026-11-23 复核）**：`layout.py` 以**图例为唯一颜色权威**——
  `legend.value/label` 点到实体就给该实体上色，`line_style` 图例给对应关系类型上色，模型没给颜色的一律中性
  （`#4A5560` / `#F4F7FA`，`nodes[id].color_source == "neutral"`）；图表则把每个数据系列与图例（及实体）显式绑定：
  `series:N` 带 `data-color/data-legend/data-entity`，layout 里是 `chart.series[i].legend_id/.entity_id/.color`。
  导出侧据此把 `svg_legend_color_map` 从「只认 `ent:` 方框」扩成四路候选匹配，纯图表（无实体方框）也能解析：
  实测 case-b 数值 x 折线图 3/3 对（`series.data-legend`）、case-a 机制图 2/2 对（`rel.data-rel-type`）、
  示例条形图 4/4 对（category 走 series，line_style 走关系），全部 match=True。`test_fixture_cases.py` 覆盖。
- **描边下限**：`render_svg.MIN_STROKE_PT` 已提到 0.52 pt（最小实际描边 ≥0.693 uu），
  实测 `line_width_min` = 0.5197 pt ≥ 0.5 pt，留有余量，导出侧无需特殊处理。
- **`figure.style.color_by_kind=true`（可选）**：layout 侧在图例色之外按 kind 上色，
  调色板用尽时按固定阶梯提亮并避开已占用颜色；实测 gene `#E59B61` / protein `#DFACC8` /
  process `#61C3A8` 三组互不相同、且不与图例声称的 `#0072B2/#D55E00/#009E73/#CC79A7` 冲突，
  导出与门禁在该模式下仍全绿（`test_color_by_kind.py`）。导出侧无需分支：照旧逐字段消费
  `nodes[].fill/stroke`。
