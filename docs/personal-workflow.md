# 每日沉淀与长期复盘

目标是让改进有据可查：保存学到了什么、承诺了什么、实际发生了什么，再用后续结果检验改变。系统不提供人格分数，也不宣称能判断一个人是否完美。

[虚构复盘演示](../examples/demo-wiki/Review.md) · [承诺与结果演示](../examples/demo-wiki/Tasks.md) · [每日记录演示](../examples/demo-wiki/Daily/2026-01-06.md)

## 每天怎么用

系统的日常采集仍使用 `knowledge sync`。它从明确配置的笔记和对话增量整理来源卡片、日期日记和主题 Wiki，同时刷新复盘。每天 21:00 的 Windows/macOS 任务可以继续调用这个命令，详见[调度配置](scheduling.md)。

自动采集只能观察文件内容，无法知道你现实中是否完成了某件事。用一分钟回填完成事项、阻碍和教训，默认日期采用工作区时区：

```sh
knowledge checkin --workspace ~/PersonalWiki \
  --done '完成原型验收' \
  --blocked '等待测试环境' \
  --lesson '下次先验证依赖，再承诺交付日期'
```

Windows PowerShell 请把命令放在同一行，或使用反引号续行；`--workspace` 替换为实际本地路径。三个文本选项都可重复。重复运行会按完全相同的文字去重并合并当天回填。补录使用 `--date YYYY-MM-DD`；更正整天记录使用 `--replace`，它会替换当天全部三个列表，未提供的类别也会清空。未来日期不接受为已发生的观察。

回填属于本人陈述，页面会标注；聊天里的计划、AI 的建议和实际完成结果分别保存。只有你显式执行 `task add` 的事项才是确认承诺。确认时可写截止日期和可验收的预计结果：

```sh
knowledge task --workspace ~/PersonalWiki add '交付阅读工具原型' --due 2026-12-10 --expected '导入一个样本并展示搜索结果'
knowledge task --workspace ~/PersonalWiki list
knowledge task --workspace ~/PersonalWiki list --status open --overdue --format text
```

返回稳定的任务 ID。同一天、同标题、同参数的重复添加不会产生重复任务；同一天同标题但参数不同会提示冲突。要关联原始依据，可在添加时传 `--source SOURCE_CARD_ID`，对应已有 `Sources/ID.md`。

用返回的 ID 更新状态；完成必须说明实际结果，改期、取消和重新打开必须说明原因：

```sh
knowledge task --workspace ~/PersonalWiki finish TASK_ID --outcome '样本导入与搜索验收通过'
knowledge task --workspace ~/PersonalWiki defer TASK_ID --due 2026-12-12 --reason '测试环境没有准备好'
knowledge task --workspace ~/PersonalWiki cancel TASK_ID --reason '目标改变，取消这项交付'
knowledge task --workspace ~/PersonalWiki reopen TASK_ID --reason '恢复目标，继续执行'
```

这些是不同的状态操作，按实际情况选择。可用 `--date` 补录，事件不能早于同任务最近一次事件。关闭的任务必须先重新打开才能再次修改状态；改期的新日期必须晚于原截止。预计结果保留原始表述，实际结果单独回填，不由 AI 自动猜测。若原承诺本身写错，可取消并说明原因，重新创建正确承诺。

## 复盘如何“挑错”

打开 `Review.md`，或运行：

```sh
knowledge review --workspace ~/PersonalWiki
knowledge review --workspace ~/PersonalWiki --as-of 2026-01-11
knowledge search --workspace ~/PersonalWiki '等待测试环境'
```

最近七天统计回填天数、新增承诺和当前状态为完成且关闭日期在窗口内的承诺。完成的确认承诺会直接展示预计结果、实际结果与完成变更链接，不需要再重复填写一次 check-in。截至当日仍打开的承诺包含更早建立的事项。无回填日期标为“未知”，不算失败；不凭缺少记录计算完成率。

目前明确实现三条规则：

| 触发条件 | 呈现的证据 | 如何解释 |
| --- | --- | --- |
| 截止日期已过且任务仍打开 | 任务 ID、记录的截止日期 | 先核对是否忘记回填，不直接断定拖延 |
| 同任务近 28 天改期至少两次 | 每次变更的日期、原因与锚点 | 提问范围、估计或依赖是否变化，不推断性格 |
| 同一项自报阻碍近 28 天至少三天出现 | 每天的回填链接 | 仅完全相同文字归组；需本人核对是否同因 |

每条发现区分记录事实、待核对问题和可选的小实验。建议不会自动成为你的承诺。选择一项你认同的改变，写明预计结果并尝试一周，再回填实际结果。已完成事项也保留在复盘，避免只剩负面记录。

`Reviews/YYYY-Www.md` 保存有个人记录的各周及本周视图，按 ISO 周编号。历史周以该周周日为截止；本周以今天为截止。后续完成不计入之前的周。它们是可重建视图，补录或更正历史事实会更新历史页，不是不可改写的审计快照。规则不做语义归因，也不能发现所有行为问题。

## 模型、搜索与自动化

资料摘要可选 `extract`、Codex 或 Claude CLI，模型沿用本机 CLI 配置或显式指定的 `engine.model`。**本页的任务状态和复盘规则不调用模型**，不会因服务中断停止工作，也不使用 Jev。`knowledge search` 是不区分大小写的关键词 AND 匹配，覆盖原始资料、摘要、每日回填、承诺及实际结果。按标题、主题、摘要、结构化记录、正文的命中优先级排序，再按日期和文件稳定排序，最多 50 条；这不是向量或语义搜索。

`search --format text` 显示来源、整理方式、命中字段与片段；`--since`、`--until` 限定记录活动日期的闭区间，`--kind` 限定记录类型。任务按该窗口内创建/事件活动过滤，只检索窗口内的实际结果与原因；截止日期不作为筛选日期，后来的完成结果不会进入历史窗口。`task list` 可用 `--status` 与 `--overdue` 筛选，今天截止不算已逾期；列表可选 `--format text`，其他任务操作保留 JSON 返回。

计划任务调用 `sync` 时，会在新资料整理后从已有回填和事件重新计算复盘；没有新增资料也会刷新截止状态。`checkin` 和 `task` 保存后立即重建页面。它们不自动向网络发送数据，需执行 `publish`，或等待带 `--push` 的下次同步。Magpie 仍只携带有体积限制的 AI 对话摘要，不夹带全部任务和行为记录；完整生成页只走可选的私有知识库发布。

原始笔记只读。个人状态保存在忽略的 `.knowledge/catalog.sqlite3`，生成页包含可阅读的结果、原因与依据。GitHub 上的 Markdown 不是数据库的完整操作状态备份；迁移机器时应单独安全备份 `.knowledge/`，不要把它加入公共 Git。

若事实已保存但页面刷新失败，CLI 会明确提示已保存。先处理生成页人工编辑冲突，再运行 `knowledge build`，不需要重复模型调用。手写内容放 `Notes/`。公共工具仓库及演示只包含虚构内容；真实资料使用独立工作区，发布目标必须为私有。
