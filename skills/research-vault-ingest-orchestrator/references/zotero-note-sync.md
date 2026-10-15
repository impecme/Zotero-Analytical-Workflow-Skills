# Zotero 精读文件回挂

精读笔记通过身份、模板及 Note/Fulltext 校验后，必须把该 Markdown 文件作为 `linked_file` 子附件挂到其 `zotero_key` 对应论文下。默认保留 Obsidian 文件为唯一正文，不复制出第二份可编辑总结。Zotero 附件标题为 `ResearchVault 精读：<论文标题>`，内容类型 `text/markdown`，管理标签 `research-vault-analytical-note`。

## 执行

使用仓库 `tools/sync_analytical_note.py --vault <vault_root> --note <absolute_note_path> --auth-file <local_auth_json> --keys-file <Zotero_profile/localAPIKeys.json>`。需要 PyYAML。只使用本机已经授权的本地写入 API；也可用环境变量 `ZOTERO_API_KEY`，不得把密钥写进命令、日志或仓库。默认匹配既有 `Codex：` 应用授权；其他应用身份须显式指定 `--app-name-prefix`，不可随意借用不相关授权。

本实现支持 Zotero Desktop 本地用户库 `127.0.0.1:23119/api/users/0`。其他 API 或组库必须另用其已支持的写入能力，不得把该地址替换为远端并发送本地凭证。API 不支持或无授权时记录 `ZOTERO_NOTE_SYNC_DEFERRED`，保留已完成阅读成果；恢复后只重试回挂。

## 去重与验证

以父条目 key 和管理标签定位，或复用同父条目下指向同一绝对文件路径的链接附件。唯一命中更新路径/标题；无命中创建；多命中停止并报告冲突，不删除手工附件。读回验证 parentItem、路径和类型；在 `01knowledge/.meta/zotero-note-sync/<zotero_key>.json` 保存附件 key、相对 Note 路径和当前文件 SHA256。

再次执行不得新增重复附件。正文发生变化时链接仍指向同一文件，刷新回执哈希；文件重命名/移动后定向修复链接并重新核验。不能仅凭旧回执或旧 COMPLETE 状态跳过检查。回挂成功才计为更新后工作流的完整完成；历史论文缺少此步骤时只补回挂，不重跑解析、精读或知识提取。

链接附件通过系统默认应用打开 Markdown，Zotero 不一定原生渲染；Obsidian 的图片、公式和 Wikilink 保持原样。链接文件不会由 Zotero 文件同步上传，跨设备需要原 Vault 文件及路径映射。用户要求 Zotero 内直接阅读或跨设备附件同步时另选原生子笔记/导出附件方案，不默认为本地文件已上传云端。
