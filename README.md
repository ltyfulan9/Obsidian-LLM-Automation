# Obsidian LLM · Personal Knowledge

把明确选择的本机笔记和 AI 对话整理成**有出处、能查找、可复盘**的知识库。支持 Windows/macOS、Python 3.10+，默认离线摘录。公共仓库只放工具和虚构示例，真实资料使用独立工作区。

[安装与快速开始](docs/quickstart.md) · [虚构演示](examples/demo-wiki/Home.md) · [产品定义](docs/product.md) · [三轮迭代](docs/iterations.md)

## 先用虚构资料试用

[安装并激活 Python 环境](docs/quickstart.md#安装)后，选择一个新目录：

```sh
knowledge demo --workspace "$HOME/KnowledgeDemo"
knowledge doctor --workspace "$HOME/KnowledgeDemo"
knowledge search --workspace "$HOME/KnowledgeDemo" '园艺' --format text
```

演示生成园艺/观星资料、日期/主题页、导图、虚构承诺与回填。不会读取你的资料、调用模型或上传文件；重复目录拒绝覆盖。用 Obsidian 或 Markdown 阅读器打开返回的 `Home.md`。

## 接入自己的资料

```sh
knowledge init --workspace "$HOME/PersonalWiki"
knowledge source markdown "$HOME/MyNotes" --workspace "$HOME/PersonalWiki" --name notes
knowledge doctor --workspace "$HOME/PersonalWiki"
knowledge sync --workspace "$HOME/PersonalWiki"
```

来源只读。工作区须在公共源码之外，且不能被来源目录包含。支持 Markdown、Codex/Claude Code 本机会话及明确导出的聊天；不会自动登录云端账户或读取隐藏推理、工具结果。[来源与范围](docs/sources.md)。

## 每天查找、行动、复盘

```sh
knowledge search --workspace "$HOME/PersonalWiki" '观察' --kind markdown --format text
knowledge checkin --workspace "$HOME/PersonalWiki" --done '完成可核实事项' --lesson '下一次尝试'
knowledge task --workspace "$HOME/PersonalWiki" list --status open --format text
knowledge review --workspace "$HOME/PersonalWiki"
```

首页连接日期、主题、来源、导图和手写 `Notes/`。确认任务时写预计结果，完成时回填实际结果；复盘回链到具体事件。AI 提议不会自动成为承诺，未记录的日期是未知。[任务与复盘](docs/personal-workflow.md)。

搜索采用关键词 AND，按标题→主题→摘要→结构化记录→正文命中排序，再按日期倒序，最多 50 条；显示片段、出处和实际整理方式。`--since/--until` 按记录活动日期筛选，`--kind` 按类型筛选，不做语义检索。任务列表支持状态及 `--overdue` 筛选；默认 JSON，可选 `--format text`。[操作细节](docs/quickstart.md#日常使用)。

## 状态与恢复

```sh
knowledge status --workspace "$HOME/PersonalWiki" --format text
knowledge backup --workspace "$HOME/PersonalWiki" --output "$HOME/knowledge-state.zip"
knowledge restore --workspace "$HOME/RecoveredWiki" --input "$HOME/knowledge-state.zip" --dry-run
```

`status` 区分最近尝试与最近完整成功。恢复先校验，只允许新目录；移除 `--dry-run` 才写入。备份可能含私人正文，应妥善保存。[备份与恢复](docs/backup.md)。

## 可选模型、发布和调度

| 能力 | 使用方式与边界 |
| --- | --- |
| AI 归纳 | `sync --engine codex` 或 `claude`；模型沿用 CLI 配置或 `engine.model`。默认 `extract` 仅为本地摘录，页面明确标注 |
| 私有 GitHub | 配好工作区的 `main`、私有 `origin` 和 gh 认证，再 `doctor --publish`、`sync --push`；不强推或自动 rebase |
| 定时运行 | 生成 Windows/macOS 配置后在目标机器注册；生成配置不等于任务已启用 |
| Magpie 小结 | 需登记 Library 集成；默认最近 7 天、gzip 不超过 64 KiB |

默认诊断不联网或调用模型；`doctor --publish` 才检查 GitHub。选用外部模型会发送所选正文；不加 `--push` 不发布到 GitHub。Jev 未接入。

[AI 设置与首次使用](docs/quickstart.md) · [同步范围](docs/sync-scope.md) · [调度](docs/scheduling.md) · [Magpie](docs/magpie.md) · [排错](docs/workflow.md)

## 验证与开发

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
```

[跨平台 CI](https://github.com/ltyfulan9/Obsidian-LLM-Automation/actions) · [验证记录](docs/validation.md) · [架构](docs/architecture.md) · [更新记录](CHANGELOG.md) · [旧版归档脚本](docs/legacy-windows.md)
