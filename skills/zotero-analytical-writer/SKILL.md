---
name: zotero-analytical-writer
description: "使用 Zotero metadata、批注和可访问的全文证据，按当前 Vault 模板创建或更新中文精读笔记，并确保 Zotero 链接、公式与原文引用真实可追溯。"
---

# Zotero Analytical Writer

## Canonical template

Resolve `vault_root` from the user-specified Vault or the current agent workspace that contains the target Note. For every Note creation or content update, first read the current Vault's own 精读模板 when it exists. Otherwise use the bundled fallback at `../../templates/论文精读模板.md`. The selected template is the structural authority for this task. Start a new Note from it; update an existing Note in place rather than introducing a parallel structure. All output paths must be real paths relative to `vault_root`, never machine-specific examples.

Keep the visible section order exactly as follows:

`基本信息 → 一句话摘要 → 研究对象 → 研究方法（方法概述 → 方法分析） → 数据来源 → 研究结论 → 关联精读笔记 → 我的判断`

Keep the template's table, field labels, heading levels, and frontmatter fields. Replace every retained placeholder with verified content; remove unused optional formula blocks, surplus finding/quote pairs, and placeholder related-note links. Do not add legacy headings such as `研究对象与问题`, `整体流程`, `数据与证据定位`, `局限与后续问题`, or `Zotero信息`. Put limitations only in `方法局限`、`数据局限` and `我的判断`.

## 职责与语料顺序

Writer 只负责分析层：`metadata + annotations + MinerU Fulltext + 必要时 PDF → 中文 analytical note`。

- Fulltext 是原文证据，分析笔记是中文理解层；不得把二者混为一谈。
- 仍保留现有的 `theme`、`study_area`、`data_source`、`methodology`、`core_variable`、`key_finding`、`relevance`、中文逻辑重构、学术垃圾过滤、公式防乱码、Zotero URI 和 Dataview 刷新逻辑。
- 不负责 PDF→MinerU；缺全文时交给 `zotero-fulltext-archiver`，不要自行伪造原文。
- 若已有正式 Fulltext，先复用并校验，不因 Note 模板修整而重新运行 MinerU。

## Knowledge handoff contract

The Analytical Note is the structural-library layer for later Knowledge synthesis; it is not a substitute for the Knowledge Page template. Preserve machine-readable fields and make the following handoff explicit whenever the Note will feed Knowledge:

- distinguish author-reported findings, methods, limitations, and the writer's interpretation;
- retain the exact `zotero_key`, `note_path`, `fulltext_path`, formulas, quotations, and PDF/Fulltext entry points;
- record which conclusions were checked against Fulltext and which remain Note-only;
- never mark a Knowledge claim as `fulltext_verified` merely because the Note contains a summary;
- if a field or conclusion cannot be located in the Note or Fulltext, write “未在当前材料中定位到可核验原文”，not a reconstructed quote or inferred page number.

When a later Knowledge task asks for “all papers”, the Knowledge Maintainer must read the Note's structured fields and the linked Fulltext independently; the Writer must not collapse the two layers into a single unsupported summary.

## Frontmatter 与稳定身份

Keep the template frontmatter (`title`、`aliases`、`tags`、`created`、`source`、`author`、`year`、`theme`、`study_area`、`data_source`、`methodology`、`core_variable`、`key_finding`、`relevance`) and replace its placeholders with verified values. Add the following identity and navigation fields after the template fields when the values are known:

```yaml
type: literature-note
zotero_key: "Q22PFLNV"
pdf_key: "4RMSR7ZR"
doi: "..."
collection: "创新经济地理"
note_path: "02vault/创新经济地理/论文标题.md"
fulltext_path: "03fulltext/创新经济地理/Q22PFLNV.md"
```

New Analytical Notes are written only to `02vault/<collection>/<paper>.md`; new Fulltext records are written only to `03fulltext/<collection>/<zotero_key>.md`. Historical `note/` and `论文库/` files may be read during migration, but are never destinations for new files. Historical `fulltext/` links may be resolved as a read fallback; normalize a path only when updating that same Note.

## 原文引用规则

- “主要发现 + 原文引用”中的原文必须真实出现在 MinerU Fulltext 或 Original PDF。
- 严禁根据中文摘要反向生成英文 quote；定位不到时写“未在当前全文中定位到可核验原句”。
- 引用要保留必要上下文，检查否定、条件、稳健性限定、假设和局限。
- PDF 页码只有在可靠映射或实际 PDF 验证后才写入 `zotero://open-pdf/...?...page=` 或写入“PDF 第 n 页”；否则保留 Fulltext 链接并写“PDF 页码未验证”。不能因为 Fulltext 的 `page_mapping: unknown` 就猜页码，也不能因为页码未知而阻止通过原 PDF 直接核验引文。
- 结论区每一条“主要发现”都要紧邻至少一条真实原文引用；先在 MinerU Fulltext 定位，再在 Original PDF 核对上下文、否定、条件、稳健性和页码。找不到原句时明确写“未在当前全文中定位到可核验原句”，不得反向生成 quote。

## 精读分析要求（融入既有模板）

以下要求增强既有 Note 的分析内容，不新增笔记类型、独立 Paper Card、章节、表格字段或 frontmatter 字段。使用当前模板已有段落、列表或单元格承载；原文证据、中文分析与 Knowledge 的职责边界保持不变。新建精读时执行；更新时仅应用于本次涉及的分析内容及其依赖结论，不自动重写无关历史笔记。

### 关键设计是否必要 → 方法分析

- 对支撑核心结论的设计选择、假设或方法步骤，说明它解决什么问题，以及移除或替换后可能影响什么。区分作者明确说明的理由与分析者推断，不将推断写成作者真实的研究动机或研究历程。
- 用原文中的消融、对照、敏感性分析或理论论证判断该设计的必要性，并给出可核验的章节、图表或公式定位。没有相应检验时写明“当前材料未见对应检验，必要性尚不能确认”；不能把“作者采用了它”当作“它不可缺少”的证据。
- 将解释融入“方法分析”；证据不足等局限仍只写入既有“方法局限”或“我的判断”。按论文实际证据选择检验方式，不强行要求所有论文都有算法消融实验。

### 关键公式的数值算例 → 方法分析中的既有公式说明

- 对理解核心方法所必需且可可靠还原的公式，先说明用途、符号含义、单位及适用的维度/形状，再用一组简短具体数值演示代入、计算和结果解释，检查算术、量纲与适用条件。
- 自设数值明确标为“教学示例，非论文实验数据”；若使用论文数值则提供来源。保留公式与分析假设的区别，不把演示结果写入作者发现、`key_finding` 或已核验的 Knowledge 事实。
- 没有关键公式、公式残缺或无法可靠还原时不强造算例；在相关内容处说明不适用或材料不足。复杂公式可在明确简化条件下演示关键部分，但不得声称已复现完整方法或实验。

### 主张—证据—缺口 → 研究结论与我的判断

- 起草核心发现前，核对每条主张对应的实验、比较、图表、数据或理论论证，检查支持范围与缺口。区分“原文确实这样表述”与“所给证据足以支持该表述”，引用作者结论本身不能替代证据检查。
- 在“研究结论”已有发现说明中写清主张及对应证据定位，继续保持每条“主要发现”紧邻真实“原文引用”的现有配对格式。保持相关性、因果性、适用条件和不确定性措辞与证据强度一致。
- 将尚未排除的替代解释、缺失对照、外推边界等分析放入既有“方法局限”“数据局限”或“我的判断”，并对应到具体发现，区分作者自述局限与分析者判断。区分“论文未报告”与“当前提供材料不足以核验”，不能因未提供附录就断言作者未做检验。
- 主张与证据的对应关系用于内部核对并融入上述既有内容，不另建矩阵文件、平行笔记或新的模板章节。

## 内容与格式约束

- `theme` 概括研究问题；`study_area`、`data_source`、`methodology`、`core_variable`、`key_finding`、`relevance` 必须来自真实材料，不复制大段摘要。
- 过滤作者地址、单位、邮编、邮箱、基金号和排版垃圾；数据与方法缺失时如实说明。
- 公式仅在原文可靠时保留；乱码或残片不强行解释，也不为占位符生成符号拆解。
- 写入前检查 YAML、美元符号配对、`zotero://select/...` 和 PDF/Fulltext 入口。
- 写入前检查标题层级、模板占位符是否清除、结论是否成对、公式是否闭合，以及 `fulltext_path` 与 Note↔Fulltext 双向入口是否存在。
- 写入前核对关键设计判断的依据、适用公式算例的计算与示例标记、核心主张的证据对应及缺口归属；确认分析推断和教学数值没有混入作者报告的事实，且未改变既有模板结构。
- `关联精读笔记` 只保留与研究问题、方法或结论存在直接关系的真实 Note；没有可确认的关联时，保留章节说明但移除示例链接。

## 写入与索引

1. 先判定是新建还是更新指定 Note；两种情况都先读取当前 Vault 模板或仓库随附模板。更新时允许重排正文以匹配模板，但不得改变稳定身份或制造重复 Note。
2. 在基本信息区的链接行加入 `全文 Markdown：[[03fulltext/<collection>/<zotero_key>]]`（路径存在时），并保留可验证的 Zotero 入口。
3. 新建论文笔记时才刷新四个根 Dataview 索引；更新既有 Note 不触发全库批量重写，但若标题、路径或索引字段变化，定向刷新受影响索引。

## 精读原生子笔记同步到 Zotero

通过 Note/Fulltext 身份和内容校验后，使用仓库 `tools/sync_analytical_note.py` 把 Obsidian 精读 Markdown 转换为对应父论文的原生子笔记。遵循 `research-vault-ingest-orchestrator/references/zotero-note-sync.md` 的去重、既有授权和读回规则。每次新建或更新精读后都检查；历史完整条目缺原生子笔记时只补同步。同步失败记录 `ZOTERO_NOTE_SYNC_DEFERRED`，保留已完成阅读但不报全流程成功。不自动批量处理无关历史论文。
