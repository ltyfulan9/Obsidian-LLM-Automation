# 从虚构演示到自己的知识库

先用离线演示验证流程，再选择真实来源。两者使用独立目录，不需要把私人资料放进工具仓库。

## 1. 安装到独立环境

需要 Python 3.10+。以下从源码安装，运行时没有第三方 Python 依赖。

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

安装可能需要访问 Python 包源；接下来的演示与默认诊断不需要网络或模型。

## 2. 用虚构资料走完一遍

下面两条命令在已激活的环境中运行；Windows 和 macOS 都可使用。选一个尚未使用的新目录：

```sh
knowledge demo --workspace "$HOME/KnowledgeDemo"
knowledge doctor --workspace "$HOME/KnowledgeDemo"
```

演示包含园艺与观星资料、一个虚构承诺和一条虚构每日回填。它不读取你的笔记或真实聊天，不调用模型，不推送 GitHub。命令返回首页位置和下一步；用 Obsidian 打开该目录，从 `Home.md` 进入，也可直接用 Markdown 阅读器查看。

试着完成以下操作：

1. 从首页进入日期页和主题页，再打开来源卡片。
2. 打开 `Tasks.md` 比较预计与实际结果入口，打开 `Review.md` 查看记录边界。
3. 阅读 `Notes/` 中的演示指南，了解手写内容应放哪里。
4. 查找虚构资料：

```sh
knowledge search --workspace "$HOME/KnowledgeDemo" '园艺' --kind markdown --format text
```

文本结果会显示命中片段、`demo-notes` 来源及“本地摘录”标记，打开返回的来源卡片可继续查证。同一个演示目录再次运行 `demo` 会拒绝覆盖，已有资料不会被重置。要重新试用，换一个新目录。

`doctor` 默认显示可读诊断，退出码 `0` 表示没有发现阻碍，`1` 表示存在需要处理的阻碍。它不代替实际同步、模型推理或系统任务执行。脚本可使用结构化结果：

```sh
knowledge doctor --workspace "$HOME/KnowledgeDemo" --format json
```

## 3. 建立自己的工作区

保留演示目录，另建真实知识工作区。将 `MyNotes` 替换为实际笔记目录；来源目录不能包含输出工作区：

```sh
knowledge init --workspace "$HOME/PersonalWiki"
knowledge source markdown "$HOME/MyNotes" --workspace "$HOME/PersonalWiki" --name notes
knowledge doctor --workspace "$HOME/PersonalWiki"
knowledge sync --workspace "$HOME/PersonalWiki"
```

默认采用 `extract` 本地摘录，页面明确标注“未经语义归纳”。这适合先检查来源范围、日期和生成结果，不表示已完成 AI 总结。来源只读，完整正文默认保存在被 Git 忽略的本地状态中。

需要导入 Codex、Claude Code 或聊天导出时，再按[来源说明](sources.md)登记明确目录。需要 AI 归纳时，再选择[摘要引擎](../README.md#选择-ai-归纳)并验证对应 CLI。

## 4. 开始每天使用

```sh
knowledge checkin --workspace "$HOME/PersonalWiki" --done '完成一个可核实事项' --lesson '下一次尝试'
knowledge task --workspace "$HOME/PersonalWiki" add '我确认执行的承诺' --expected '可验收结果'
knowledge task --workspace "$HOME/PersonalWiki" list --status open --format text
knowledge review --workspace "$HOME/PersonalWiki"
```

任务命令返回 ID；完成时把下面的 `TASK_ID` 替换为实际 ID：

```sh
knowledge task --workspace "$HOME/PersonalWiki" finish TASK_ID --outcome '实际结果与证据'
knowledge task --workspace "$HOME/PersonalWiki" list --status done --format text
knowledge review --workspace "$HOME/PersonalWiki"
```

复盘显示截至当日仍为完成、且完成日期处于窗口内的承诺结果，在 `Review.md` 的“做成了什么”回链到完成变更。每日回填与任务结果保持独立。讨论过不等于做完，AI 建议不会自动成为本人承诺。也可以在演示目录中先完成虚构任务来体验这个闭环。

任务列表支持 `--status all|open|done|cancelled`，默认 `all`；`--overdue` 只列出已过截止日期且仍打开的任务，取消、完成及未来截止的任务不会混入。任务的筛选与 `--format text` 仅适用于 `list`；不指定格式时保持 JSON 输出。完整操作见[每日沉淀与复盘](personal-workflow.md)。

### 找回某段日期里的内容

```sh
knowledge search --workspace "$HOME/PersonalWiki" '观察' --kind markdown --format text
```

- 以空格分隔的多个关键词采用 AND 匹配，不区分大小写。只检索明确的内容字段；来源别名、文件路径、ID 和方法名不是关键词内容。
- 标题命中优先于主题，再依次是摘要、结构化要点/个人记录、正文；同级按记录日期倒序，最后按输出路径稳定排列。最多返回 50 条，不做同义词扩展或语义检索。
- 用 `--since YYYY-MM-DD`、`--until YYYY-MM-DD` 指定包含两端的日期窗口；开始日期晚于结束日期会报错。
- `--kind` 可选 `markdown`、`codex`、`claude`、`export`、`checkin` 或 `task`。
- 资料按资料日筛选，回填按回填日筛选；任务按创建或变更活动日期筛选，并只搜索窗口内事件的结果/原因。截止日期不是活动日期，窗口之后才记录的完成结果不会参与旧窗口匹配。

没有结果时先检查关键词、类型与日期窗口；未命中不等于不存在相关语义。默认 JSON 结果保留程序接口，可读输出使用 `--format text`。

## 5. 按需增加发布与定时运行

普通 `sync` 只更新本地。发布前需要把真实工作区配置成 Git 仓库、`main` 分支及自己的私有 GitHub `origin`，并完成 GitHub CLI 登录。只有显式检查发布目标时才访问 GitHub：

```sh
knowledge doctor --workspace "$HOME/PersonalWiki" --publish
knowledge sync --workspace "$HOME/PersonalWiki" --push
```

检查通过不能替代实际推送成功。先完成一次手动同步，再按[Windows/macOS 调度说明](scheduling.md)生成并注册任务。生成调度文件不会隐式启用后台任务。Magpie 是另一个可选传输入口，见[接入说明](magpie.md)。

出现故障先查看诊断和[修复路径](workflow.md#错误恢复)，不要删除状态目录或生成清单绕过保护。
