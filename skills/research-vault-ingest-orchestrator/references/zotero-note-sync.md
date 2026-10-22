# Zotero 原生精读子笔记

精读文件通过身份、模板及 Note/Fulltext 校验后，将其正文转换为 Zotero **原生子笔记**，放在 `zotero_key` 对应论文下。Obsidian Markdown 是唯一主稿，Zotero 提供内置阅读副本；不是 Markdown 链接附件，也不是双向同步。

## 执行

安装 `PyYAML markdown-it-py mdit-py-plugins`，运行：

```text
python tools/sync_analytical_note.py --vault <vault_root> --note <absolute_note_path> --auth-file <local_auth_json> --keys-file <Zotero_profile/localAPIKeys.json>
```

仅使用已有本地写入授权；也可从环境变量 `ZOTERO_API_KEY` 读取密钥。禁止将密钥写入命令、日志或仓库。默认匹配已授权的 `Codex：` 应用，其他应用身份需显式指定 `--app-name-prefix`；不能随意借用无关应用授权。

实现支持 Zotero Desktop 本地用户库 `127.0.0.1:23119/api/users/0`。其他API/组库使用各自受支持能力，不能改为远端地址并发送本地凭证。授权或能力缺失时标为 `ZOTERO_NOTE_SYNC_DEFERRED`，恢复后只重试同步，不重跑解析和阅读。

## 内容转换与显示验证

- 去除YAML元数据，保留标题、列表、引用、代码和表格正文；不改写事实或原文引用。
- `$...$`行内公式生成 `span.math`，`$$...$$`块公式生成 `pre.math`，使用Zotero原生数学节点，不将公式当普通文本或粘贴渲染后的KaTeX HTML。代码中的美元符号保持代码。
- Markdown表格转换为原生HTML表格；先处理Wikilink别名中的管道符，避免误拆列。
- 顶部包含“在 Obsidian 中打开主稿”和单向同步提示；Wikilink转换为Obsidian入口，Zotero/PDF及网络链接保留。主稿路径移动后重新同步入口。
- 当前不自动导入嵌入图片；遇到Markdown图片或Obsidian嵌入时停止并明确待处理，不能静默删图或声称显示完整。
- 转换器或渲染依赖变化时，在用户当前Zotero笔记编辑器中核对代表性表格、行内和块公式；批次检查表格行列、公式数量与解析错误。可使用本机随附编辑器的独立渲染验证，报告实际验证范围。

Mermaid 流程图在 Obsidian 主稿中保留为 `mermaid` 代码块；当前转换器将其保留为 Zotero 原生笔记中的源码代码块，不渲染成图。正文照常同步，保留“在 Obsidian 中打开主稿”入口，并在交付中明确图形显示限制；不能为了双端兼容改成文本框图，也不能宣称已导入流程图图片。此规则不改变去重和冲突保护。

## 去重、冲突与回执

原生笔记使用管理标签 `research-vault-analytical-note`。以父条目key加该标签或已记录的原生笔记key查找；无命中创建、唯一命中更新、多命中停止。不得按相似标题覆盖人工笔记。

写入后读回parentItem和HTML；回执位于 `01knowledge/.meta/zotero-note-sync/<zotero_key>.json`，记录 `mode: native_note`、`note_key`、主稿及原生正文哈希、公式/表格数量。忽略编辑器自动添加的表格分组、列表/单元格段落包装、链接rel和schema版本等序列化差异，但保留实际内容比较。

重复运行不得创建新子笔记。主稿更新时更新同一子笔记；若Zotero端正文也变化，默认报 `ZOTERO_NOTE_SYNC_CONFLICT`，保留人工修改。只有用户明确要求以主稿覆盖时使用 `--overwrite-managed-note`，覆盖前仍保存旧笔记备份。无可信回执且已有不同内容时同样停止，不能猜测。

## 从旧Markdown链接附件迁移

先创建/更新原生笔记并读回成功，再将**带管理标签且准确指向当前主稿**的旧链接附件标记 `deleted=1`，仅移入Zotero回收站，不删除磁盘原稿、PDF或无关手工附件。原附件记录备份在回执目录的 `backups/`。需要暂留链接可用 `--keep-linked-files`。

原生写入失败时不处理旧链接；原生成功但旧链接迁移失败时保留部分状态，重跑只补迁移。已有全文和精读的历史论文只补此阶段。原PDF/图片待补等其他状态不因原生笔记创建而变成完整入库。用户未指定全库时不自动迁移无关历史条目。

完成条件：唯一原生子笔记、正确父项、正文读回及显示检查通过；默认迁移时还需确认旧受管链接已回收。正文可在Zotero内阅读，不再调用系统Markdown应用。Obsidian入口仍需要本地Vault；Zotero账户同步状态由其自身配置决定，不能仅凭本地写入宣称已同步云端。
