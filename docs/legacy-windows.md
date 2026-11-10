# 旧版 Windows 原文件归档流程

`automation/nightly-windows.ps1` 保留用于原始文件归档兼容；v0.2 的跨平台知识库应使用 `knowledge` CLI。两套状态与配置不可混用，也不应同时管理同一目录。

旧脚本在其上一级目录的 `.local-state/` 中读取 `config.json`，配置结构见根目录 `config.legacy.example.json`。可通过 `OBSIDIAN_LLM_STATE_DIR` 指定其他状态目录。

旧流程检查私有 GitHub 目标，比较 Markdown 哈希，按需调用 Codex 更新 `projects/learning/journal/profile` 内容，然后镜像源库可收录文件到 `原始笔记/`，保留旧归档，提交并推送。首次基线不会全量整理。

该脚本没有 v0.2 的多源会话适配、日期/主题双索引、导图生成或跨平台 Python 核心。使用时需要在独立的私有备份库中提供适合旧流程的规则和索引。模型沿用旧脚本内配置，应先确认可用性。

旧流程的隐私守卫测试仍可在 Windows 运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\tests\privacy-guard.ps1'
```
