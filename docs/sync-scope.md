# 到底同步什么？能同步 AI 对话小结吗？

**可以。** 本工具将明确配置的 Codex、Claude Code 或聊天导出资料整理成来源小结，按日期和主题写入个人知识库，再按需推送到私有 GitHub。Magpie 的“同步与备份”是另一条配置备份流程。

## 两条同步流程

| 流程 | 主要内容 | 不等于什么 |
| --- | --- | --- |
| Magpie 同步与备份 | 供应商配置、各 agent 模型选择、资源库等；可选同步用量和登录信息 | 不是个人知识 Wiki，也不能把用量统计当作聊天内容 |
| 本项目的知识同步 | 笔记/对话小结、要点、决策、待办、日期页、主题 Wiki、时间线、导图、手写 Notes | 不导出 API Key、认证配置、隐藏推理或工具结果 |

Magpie 通过本机口令加密备份，GitHub 保存密文。截图中“用量”一项说明记录时间、token、模型和费用，不含对话内容；它不是对话摘要功能。具体开关以安装版本为准。[Magpie 官方同步说明](https://github.com/yetone/magpie/blob/main/docs/reference.md#keeping-machines-in-sync)。

通过 Magpie 使用 Codex / Claude Code 时，本工具仍从这些客户端已落地的本机会话文件读取正文；不读取供应商配置、不解密 Magpie 备份，也不需要复制它的 Key 或同步口令。

## 知识库会发布哪些内容

| 文件 | 内容 | 默认发布到私有 GitHub |
| --- | --- | --- |
| `Sources/` | 每份资料的小结、要点、明确决定、未解决问题与来源引用 | 是 |
| `Daily/` | 按日期聚合笔记、对话小结、本人回填与承诺变更 | 是 |
| `Tasks.md` | 本人确认的承诺、预计/实际结果、日期与改期原因 | 是 |
| `Review.md`、`Reviews/` | 七天统计、近 28 天模式提示、按周回看与依据链接 | 是 |
| `Wiki/` | 跨日期聚合主题及证据 | 是 |
| `Timeline.md`、`Home.md` | 日期与主题导航 | 是 |
| `Maps/` | Mermaid 思维导图、关系图、Obsidian Canvas | 是 |
| `Sync.md` | 从配置生成的实际同步范围 | 是 |
| `Notes/` | 你的手写补充，生成器不改写 | 是 |
| `Archive/` | 可选的规范化正文 | 否；`include_raw: true` 才启用 |
| `.knowledge/` | 本机路径、配置、正文及个人操作状态数据库、锁与状态 | 否 |

“发布”仅在 `knowledge publish` 或 `knowledge sync --push` 时发生，普通 `sync` 只处理本地。完整会话正文不默认放进 Git；摘要本身仍可能含私人信息，目标必须保持私有。

每日回填和确认承诺需显式提供；工具不会把 AI 提议直接记成已承诺或已完成。见[每日沉淀与复盘](personal-workflow.md)。Magpie 的压缩小包仍只包含最近的 AI 对话摘要，不包含这些个人行为记录。

## 无需执行采集即可预览范围

```sh
knowledge plan --workspace ~/PersonalWiki
```

该命令只读本机配置，不读源笔记或聊天正文、不调用模型、不上传文件。来源只显示别名、类型、日期和筛选规则，不展示本机绝对路径。生成后的 `Home.md` 也有“查看同步范围”入口。

## 自动整理最近 7 天开始的对话

```sh
knowledge source codex ~/.codex/sessions --workspace ~/PersonalWiki --name codex --recent-days 7
knowledge source claude ~/.claude/projects --workspace ~/PersonalWiki --name claude --recent-days 7
knowledge sync --workspace ~/PersonalWiki --engine claude
```

`--recent-days 7` 以配置时区计算含当天的 7 个自然日，并持久保存为 `since` 起始日期。以后仍接收这个日期之后的新内容；它不是每天滚动丢弃旧知识。已登记同名来源时，在本地配置中调整 `since`，无需重复添加。

默认 `extract` 只是原文摘录与有限分类。需要 AI 语义归纳时，将本机配置的 `engine.name` 设为 `codex` 或 `claude`，并确认该 CLI 能正常调用模型。持续运行只对内容或引擎配置变化的资料重新摘要。

## 每 30 分钟执行

```sh
# macOS；Python 路径按本机环境填写
knowledge schedule --workspace ~/PersonalWiki --platform macos --interval-minutes 30 --output ~/Library/LaunchAgents/io.personal.knowledge.daily.plist
```

```powershell
# Windows；路径为示例
knowledge schedule --workspace 'C:\Notes\PersonalWiki' --platform windows --interval-minutes 30 --output 'C:\Notes\knowledge-task.xml'
```

需要自动发布时加 `--push`；否则自动任务只更新本地。以上命令只生成调度文件，注册与停用方式见[调度说明](scheduling.md)。计算机需要开机，客户端 CLI 认证及源目录需要可访问。

公共仓库的[演示 Wiki](../examples/demo-wiki/Home.md)与[同步范围页](../examples/demo-wiki/Sync.md)全部来自虚构资料。它们用于验证流程，不代表已经读取或同步任何人的真实对话。
