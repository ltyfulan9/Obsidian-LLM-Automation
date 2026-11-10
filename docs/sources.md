# 资料来源与对话导入

## 支持范围

| 类型 | 内容 | 导入方式 |
| --- | --- | --- |
| `markdown` | Obsidian Markdown 或普通 Markdown | 配置一个目录或文件 |
| `codex` | 本机 Codex rollout JSONL | 配置 sessions 目录或指定会话文件 |
| `claude` | 本机 Claude Code 会话 JSONL | 配置 projects 目录或指定会话文件 |
| `export` | Markdown、通用 JSON/JSONL、Claude 导出会话数组 | 将手动导出文件放到指定目录 |

不会扫描账户、联网下载聊天记录或读取认证配置。Claude 网页版和桌面聊天导出需手动提供；Claude Code 本机会话适配不代表可直接读取 Claude Desktop 的所有聊天。Codex 云端且未落地为本机文件的会话也需要先导出。

本机常见目录如下；实际位置可被客户端配置改变，先确认目录中确实有 JSONL：

- Codex：`~/.codex/sessions`，归档会话可单独配置 `~/.codex/archived_sessions`。
- Claude Code：`~/.claude/projects`，使用 `CLAUDE_CONFIG_DIR` 时按实际目录配置。

## 明确配置导入范围

```sh
knowledge source codex ~/.codex/sessions --workspace ~/PersonalWiki --name codex
knowledge source claude ~/.claude/projects --workspace ~/PersonalWiki --name claude
knowledge source markdown ~/Notes --workspace ~/PersonalWiki --name notes
knowledge source export ~/ChatExports --workspace ~/PersonalWiki --name exports
```

可重复使用 `--include`、`--exclude`，匹配相对路径 glob。例：`--include '2026/11/*'`。目录名因工具和版本而异，按实际文件结构填写。添加命令只登记来源；`sync` 才读取内容。

原生适配器只读取 user/assistant 正文。Codex 优先使用 message response items，仅在没有它们时回退到 legacy message events，避免重复。Claude Code 跳过 sidechain/subagents；两者均不收录系统/开发者指令、工具结果、图片和隐藏推理块。

这些 JSONL 是客户端内部格式，可能随版本变化。实现与合成测试覆盖当前识别的字段，不能保证所有未来版本。出现不兼容时可先使用通用导出格式；中间损坏的 JSONL 行会报错，正在写入的最后一条不完整行会留待下次导入。

## 日期与主题

添加对话源时可指定 `--recent-days 7`，按配置时区计算含当天的 7 个自然日，并在本地配置中保存固定 `since` 日期。之后持续导入这个起点之后的新内容，不滚动删除旧知识。可通过 `knowledge plan` 在读取正文前预览来源和日期范围。

- Markdown 优先采用 `date: YYYY-MM-DD` 或文件名中的日期，再回退到文件修改时间。
- 对话按每条消息时间戳换算到配置时区，跨日拆成多个日期资料；无时间戳时回退到文件修改时间。
- `timezone` 默认 `local`。可设 `+08:00`、`UTC` 或 IANA 名称；Windows 缺少 IANA 数据时安装 `tzdata` 或使用固定偏移。
- Markdown 支持行内 `tags: [主题一, 主题二]`；AI 引擎可根据正文归纳主题。默认摘录引擎使用标签和有限关键词分类，能力与语义归纳不同。
- 标准化相对路径和来源别名保留在来源卡片中。原路径含私人信息时仅留在私有知识工作区。

## 通用 JSON 示例

```json
{
  "id": "example-conversation",
  "messages": [
    {"role": "user", "content": "虚构示例：如何组织学习笔记？", "timestamp": "2026-01-05T10:00:00Z"},
    {"role": "assistant", "content": "保留日期、主题和来源。", "timestamp": "2026-01-05T10:01:00Z"}
  ]
}
```

支持会话数组、`messages` 或 Claude 导出的 `chat_messages`；纯 JSONL 也可每行写一个带 role/content 的消息。导入同一会话的不同导出文件会视作不同来源，不进行跨文件的模糊去重。

## 模型接入依据

- Codex 使用 `exec --output-schema --output-last-message`，结构化返回后由 Python 校验与写文件；[OpenAI 官方 CLI 参考](https://developers.openai.com/codex/cli/reference/)。
- Claude Code 使用 `-p --output-format json --json-schema` 并检查 `structured_output`；[Claude Code 程序化运行文档](https://code.claude.com/docs/en/headless)。
- 原生会话适配属于本项目基于本机字段观察实现的读取器，不是上述官方 CLI 输出接口的稳定性承诺。
