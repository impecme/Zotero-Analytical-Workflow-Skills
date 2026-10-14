# llm-for-zotero 全文缓存衔接

此适配只改变“全文从哪里获取”，不改变元数据/批注提取、精读模板、知识整理、正式归档路径、双向链接和验证要求。不读取插件聊天历史，不把模型回答当作论文原文，不修改插件设置或启动后台服务。

## 输入和优先级

1. 已有有效的正式 Fulltext：按现有增量规则复用，不重新处理。
2. 尚需全文：用 Zotero 父条目 `zotero_key` 和选定的 `pdf_key` 检查插件缓存。多个 PDF 必须明确选择；不能取第一个或按标题猜。
3. 插件缓存缺失、未完成、不合格：使用原有可访问转换能力；没有转换能力则报告 `FULLTEXT_DEFERRED`。身份无法解析时停止，不能转换另一个附件来绕过问题。

仓库中的 `tools/prepare_fulltext.py` 提供可重复执行的准备入口（Python 3.11+，标准库）。在仓库目录运行：

```sh
python tools/prepare_fulltext.py --key ABCD1234 --pdf-key EFGH5678 --output /path/to/new-staging-run
```

数据目录来自 `--data-dir`、既有 `config.toml` / `ZOTERO_DATA_DIR` 或平台发现；省略 `--output` 时使用既有 `archive_root`。不新增必填配置。`--mineru`、`--method`、`--timeout` 在回退时传给原 `run_mineru_production.py`；缓存复用不需要 MinerU 已安装或服务正在运行。

## 缓存协议与检查

依据 llm-for-zotero 3.9.11 的缓存结构（不是对所有版本的兼容承诺）：

```text
<Zotero data>/llm-for-zotero-mineru/<attachment numeric ID>/
  full.md
  manifest.json
  _llm_source.json
  content_list.json       # 可选
  images/ 或其他图片子目录
```

附件数字 ID 只用于在当前数据库定位缓存。`_llm_source.json` 的 `kind=llm-for-zotero/mineru-cache-source`、`version=1`，以及 `attachmentId`、`attachmentKey`、`parentItemKey`、`sourceFilename` 必须与当前数据库和 PDF 一致。数字 ID 不用作跨设备身份。

- 有 `_llm_write_pending.json`、空全文、缺失/无效来源或 manifest 时拒绝复用。
- `parsedAt` 必须包含时区，且不早于 PDF 修改时间；只有 `recordedAt` 或 `restoredAt` 不足以证明原始解析时间。无法判断则保守回退。
- 这是时效启发式，不是源 PDF 哈希证明。插件来源记录没有提供源 PDF 的 SHA-256；保留修改时间的 PDF 替换仍需人工检查或重新转换。运行记录中的 `sha256` 只是本次读取的 PDF 哈希。
- 校验 Markdown 图片、manifest / content list 中的资源路径；缺图、空文件、外部图片、越界路径和链接目录拒绝复用。无法识别的 Markdown 图片语法也回退，不静默丢图。
- 复制前后校验缓存文件哈希、写入标记和 PDF 哈希，拒绝处理过程中发生变化的缓存。

## 输出及正式归档

成功复用时返回 `PLUGIN_CACHE_REUSED`，在新暂存目录生成 `raw/`（保持全文字节与资源相对路径）和 `production-status.json`。记录来源、父/附件 Key、缓存文件哈希及检查限制。此状态只表示全文材料已准备，**不等于论文入库完成或全文证据已经人工核验**。

不覆盖已有输出；不在 Zotero 数据目录暂存；不写 Zotero 数据库、PDF 或插件缓存。失败回退时保持原 MinerU runner 的成功/失败状态和退出码，并在已有运行状态文件中补充缓存拒绝原因。

随后仍由 Fulltext Archiver 检查原文前、中、后、页数和图片，按既有规则写入 `03fulltext/<collection>/<zotero_key>.md`，整理图片并修复相对链接。`manifest.json` 或 `content_list.json` 的页码不能未经 PDF 核验就升级为可靠映射，默认仍是 `page_mapping: unknown`。

若插件已移除 Markdown 图片嵌入但 manifest 保留图片，归档时需同时检查、保留这些资源；不能只复制 `full.md`。不改变后续 Note/Fulltext 配对、模板、Knowledge 决策和校验流程。不自动双向同步缓存与研究库。
