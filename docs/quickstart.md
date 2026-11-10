# 快速开始

## 安装

需要 Python 3.10+。在源码仓库内创建独立环境；运行时无第三方 Python 依赖。

Windows PowerShell：

```powershell
git clone https://github.com/ltyfulan9/Obsidian-LLM-Automation.git
cd Obsidian-LLM-Automation
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

macOS：

```sh
git clone https://github.com/ltyfulan9/Obsidian-LLM-Automation.git
cd Obsidian-LLM-Automation
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

安装可能联网；下列演示和默认诊断离线运行。

## 试用虚构知识库

```sh
knowledge demo --workspace "$HOME/KnowledgeDemo"
knowledge doctor --workspace "$HOME/KnowledgeDemo"
knowledge search --workspace "$HOME/KnowledgeDemo" '园艺' --kind markdown --format text
```

选择新目录。演示只用虚构资料，不读取私人文件、调用模型或上传；重复目录拒绝覆盖。用 Obsidian 打开返回的 `Home.md`，依次查看来源、日期、主题、Tasks、Review 和 Notes 指南。搜索文本显示片段、`demo-notes` 来源与“本地摘录”标记。

`doctor` 默认文本，可加 `--format json`；退出 `0` 表示未发现阻碍，`1` 表示需处理。它不验证真实模型推理或系统任务执行。

## 配置真实来源

另建工作区，把 `MyNotes` 换成实际目录：

```sh
knowledge init --workspace "$HOME/PersonalWiki"
knowledge source markdown "$HOME/MyNotes" --workspace "$HOME/PersonalWiki" --name notes
knowledge doctor --workspace "$HOME/PersonalWiki"
knowledge sync --workspace "$HOME/PersonalWiki"
```

来源只读，不能包含工作区。默认 `extract` 是本地摘录，不是 AI 总结。更多本机会话/导出格式见[来源说明](sources.md)。手写内容放 `Notes/`；生成页有编辑保护。

需要 AI 时先认证对应 CLI，再用 `sync --engine codex` 或 `claude`。长期默认在 `.knowledge/config.json` 的 `engine.name` 设置，模型沿用 CLI 或 `engine.model`，外部服务会处理所选正文。

## 日常使用

```sh
knowledge checkin --workspace "$HOME/PersonalWiki" --done '完成可核实事项' --lesson '下次尝试'
knowledge task --workspace "$HOME/PersonalWiki" add '我确认执行的承诺' --expected '可验收结果'
knowledge task --workspace "$HOME/PersonalWiki" list --status open --format text
knowledge task --workspace "$HOME/PersonalWiki" finish TASK_ID --outcome '实际结果与证据'
knowledge review --workspace "$HOME/PersonalWiki"
```

将 `TASK_ID` 换成返回的 ID。复盘显示窗口内完成且截至当日仍为完成的任务结果，回链到完成事件；不需要重复创建每日回填。AI 建议不自动成为承诺。[完整任务操作](personal-workflow.md)。

任务列表支持 `--status all|open|done|cancelled`（默认 `all`）与 `--overdue`；逾期只包含仍打开且已过截止日期的任务。筛选和任务的 `--format text` 仅用于 `list`，默认输出 JSON。

搜索支持 `--kind markdown|codex|claude|export|checkin|task`、包含两端的 `--since/--until YYYY-MM-DD` 和 `--format text`：

- 空格分隔关键词采用不区分大小写的 AND，只检索内容，不检索来源别名/路径/ID。
- 标题→主题→摘要→结构化记录→正文命中优先，再按日期倒序及路径稳定排列，最多 50 条；不做同义词或语义检索。
- 资料按资料日，回填按回填日；任务按创建/变更活动日筛选，截止日期不参与，窗口之后的结果/原因不参与匹配。

## 发布、调度与恢复

配好真实工作区的 Git `main`、私有 `origin` 和 gh 认证后：

```sh
knowledge doctor --workspace "$HOME/PersonalWiki" --publish
knowledge sync --workspace "$HOME/PersonalWiki" --push
knowledge status --workspace "$HOME/PersonalWiki" --format text
```

不加 `--push` 不发布到 GitHub；显式 `--publish` 诊断才检查目标。先手动跑通，再按[调度说明](scheduling.md)注册系统任务；[Magpie](magpie.md)单独接入。

`status` 区分最近尝试与最近成功。[备份和恢复](backup.md)保留运行状态；[排错](workflow.md#错误恢复)说明失败后的修复路径，不要删除状态目录绕过保护。
