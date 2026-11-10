# Obsidian LLM · Personal Knowledge

把你明确选择的本机笔记和 AI 对话整理成**有出处、能查找、可复盘**的个人知识库。按日期回顾，按主题复用；把本人确认的承诺与实际结果分开保存。

Python 3.10+，支持 Windows、macOS。默认本地摘录，不需要模型密钥；真实资料保存在独立工作区，公共仓库只包含工具和虚构示例。

[安装与首次使用](docs/quickstart.md) · [查看虚构知识库](examples/demo-wiki/Home.md) · [查看虚构复盘](examples/demo-wiki/Review.md) · [产品定义与三轮验收](docs/product.md)

## 先用虚构资料试一遍

在本仓库[安装并激活独立 Python 环境](docs/quickstart.md#1-安装到独立环境)后，选择一个新目录：

```sh
knowledge demo --workspace "$HOME/KnowledgeDemo"
knowledge doctor --workspace "$HOME/KnowledgeDemo"
knowledge search --workspace "$HOME/KnowledgeDemo" '园艺'
```

演示用园艺与观星资料生成来源卡片、日期页、主题 Wiki、导图、一个承诺和一条每日回填。它不读取你的资料，不调用模型，也不上传文件。同一个演示目录重跑会拒绝覆盖。

命令返回 `Home.md` 的位置。用 Obsidian 打开这个目录，从首页进入；在 `Notes/` 查看手写指南。诊断默认显示可读结果，自动化可用 `doctor --format json`。完整步骤见[快速开始](docs/quickstart.md)。

## 换成自己的资料

另建真实工作区，将 `MyNotes` 替换成实际来源目录：

```sh
knowledge init --workspace "$HOME/PersonalWiki"
knowledge source markdown "$HOME/MyNotes" --workspace "$HOME/PersonalWiki" --name notes
knowledge doctor --workspace "$HOME/PersonalWiki"
knowledge sync --workspace "$HOME/PersonalWiki"
```

来源只读。工具只采集明确配置且匹配规则的文件，工作区不能放在公共工具仓库内，也不能放在某个来源目录内部。来源添加只登记路径，`sync` 才读取内容。

| 资料或操作 | 能得到什么 |
| --- | --- |
| Obsidian / Markdown | 带来源的资料卡片与日期、主题视图 |
| Codex / Claude Code 本机会话 | 用户与助手正文的小结；跨日按配置时区拆分 |
| 明确导出的聊天文件 | Markdown、通用 JSON/JSONL 和 Claude 会话导出适配 |
| 日期与主题 | `Daily/`、`Timeline.md`、`Wiki/`，连接同一份来源证据 |
| 导图 | Mermaid 思维导图、关系图和 Obsidian Canvas |
| 每日回填与确认承诺 | `Tasks.md` 的预计/实际结果、变更历史及 `Review.md` 的证据复盘 |

原生客户端日志格式可能变化，不自动读取云端账户；隐藏推理、工具输出、图片和 PDF 不作为正文导入。详见[来源范围](docs/sources.md)与[到底同步什么](docs/sync-scope.md)。

## 选择 AI 归纳

默认 `extract` 是原文摘录和有限关键词分类，页面明确标注“未经语义归纳”。它适合先核验范围与流程，不能当作模型理解。

需要语义摘要时，先安装并认证对应 CLI，再按次选择：

```sh
knowledge sync --workspace "$HOME/PersonalWiki" --engine codex
knowledge sync --workspace "$HOME/PersonalWiki" --engine claude
```

长期默认项在本地 `.knowledge/config.json` 的 `engine.name` 中设置。模型沿用本机 CLI 配置，或通过 `engine.model` 指定；引擎名称不保证实际供应商或模型身份。外部模型会通过该 CLI 配置的服务处理正文。长文本分段整理再合并；失败会明确报错，不把摘录冒充 AI 成果。

## 每天怎么用

```sh
knowledge sync --workspace "$HOME/PersonalWiki"
knowledge search --workspace "$HOME/PersonalWiki" 'Python'
knowledge checkin --workspace "$HOME/PersonalWiki" --done '完成可核实事项' --lesson '下一次尝试'
knowledge task --workspace "$HOME/PersonalWiki" add '我确认执行的承诺' --expected '可验收结果'
knowledge review --workspace "$HOME/PersonalWiki"
```

讨论过不等于做完。完成承诺时用返回的 ID 回填 `task finish TASK_ID --outcome '实际结果'`；AI 提议不会自动成为承诺。复盘依据明确的日期记录和本地规则，不调用模型或给人格打分。缺少记录标为未知。[每日沉淀与复盘规则](docs/personal-workflow.md)。

搜索当前采用关键词匹配，最多返回 50 条；不要把它当作向量或语义检索。`build` 可以从已保存摘要重建视图，不再调用模型。手写知识放 `Notes/`，生成器不会改写；直接编辑生成页会触发保护，详见[故障修复](docs/workflow.md#错误恢复)。

## 发布与自动化分别配置

普通同步只更新本地。需要 GitHub 发布时，把真实工作区配置为自己的私有仓库、`main` 分支和 `origin`，再通过 GitHub CLI 登录：

```sh
knowledge doctor --workspace "$HOME/PersonalWiki" --publish
knowledge sync --workspace "$HOME/PersonalWiki" --push
```

默认诊断不访问网络；只有显式 `--publish` 才核验发布目标。发布命令在读取来源前和发送前检查私有状态，只暂存允许的文件，不强推、不自动 rebase。[发布边界](docs/sync-scope.md)。Git 上的 Markdown 是阅读产物，不是 SQLite 中全部运行状态的替代品。

| 需要的能力 | 当前方式与边界 |
| --- | --- |
| Windows/macOS 定时同步 | 生成原生调度配置，再在目标机器注册；生成配置不等于启用任务 |
| Magpie 携带压缩对话小结 | 需先登记 Library 集成；默认最近 7 天、gzip 不超过 64 KiB |
| 失败后重试发布 | `knowledge publish`，无需重新调用模型 |
| 检查工作区 | `knowledge doctor` 诊断；实际运行结果仍需单独核验 |

[调度与安装](docs/scheduling.md) · [Magpie 接入](docs/magpie.md) · [流水线与本地状态](docs/workflow.md)。Jev 暂未接入。

## 验证与开发

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
python -m examples.build_demo
```

CI 在 Linux、Windows、macOS 和 Python 3.10/3.12 上运行同一套测试。模拟测试、真实 CLI、模型调用和系统调度各自记录，不相互代替。

[Actions](https://github.com/ltyfulan9/Obsidian-LLM-Automation/actions) · [验证记录](docs/validation.md) · [架构与失败语义](docs/architecture.md) · [更新记录](CHANGELOG.md)

旧版 Windows 原文件归档脚本保留在 `automation/`，与新工作区分别管理；参阅[旧版说明](docs/legacy-windows.md)。
