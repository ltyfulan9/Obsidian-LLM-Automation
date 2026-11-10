# Windows 与 macOS 定时运行

先在目标机器的持久 Python 环境安装本工具，手动成功运行一次 `knowledge sync`。调度使用该环境的 Python 绝对路径，不依赖启动时的工作目录。生成配置与安装任务是两个步骤；下面均以每天本地时间 21:00 为例。

## macOS：launchd

需要每 30 分钟运行时，生成命令加入 `--interval-minutes 30`；省略时按每日 `--hour` / `--minute`。首次收录范围与后续增量见[同步说明](sync-scope.md)。

在 Mac 上生成配置，下面的 Python 路径按实际虚拟环境替换：

```sh
knowledge schedule --workspace ~/PersonalWiki --platform macos --hour 21 --minute 0 --python "$HOME/.venvs/knowledge/bin/python" --output ~/Library/LaunchAgents/io.personal.knowledge.daily.plist
plutil -lint ~/Library/LaunchAgents/io.personal.knowledge.daily.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.personal.knowledge.daily.plist
```

需要自动同步私有 GitHub 时，在生成命令中加入 `--push`。启动时使用登录用户的 GitHub/Codex/Claude 认证。launchd 的 PATH 往往不同于终端；生成器包含 Homebrew 常用路径，其他 CLI 路径可在本机配置的 `engine.command` 或 plist 的 PATH 中指定。

手动触发和停用：

```sh
launchctl kickstart gui/$(id -u)/io.personal.knowledge.daily
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/io.personal.knowledge.daily.plist
```

## Windows：任务计划程序

在 Windows 上生成 XML；路径为示例：

```powershell
knowledge schedule --workspace 'C:\Notes\PersonalWiki' --platform windows --hour 21 --minute 0 --output 'C:\Notes\knowledge-task.xml'
Register-ScheduledTask -TaskName 'Personal Knowledge Daily' -Xml (Get-Content -LiteralPath 'C:\Notes\knowledge-task.xml' -Raw -Encoding UTF8)
Start-ScheduledTask -TaskName 'Personal Knowledge Daily'
Get-ScheduledTaskInfo -TaskName 'Personal Knowledge Daily'
```

选择能访问源目录与 CLI 认证的账户；也可在任务计划程序导入 XML。需要发布时生成命令加 `--push`。配置已设置错过计划后可启动与禁止重叠实例。停用使用 `Disable-ScheduledTask -TaskName 'Personal Knowledge Daily'`。

## 时区与日志

调度时间采用操作系统本地时间；资料归档日期采用知识库配置中的 `timezone`。跨机器同步时建议两台机器显式使用同一归档时区。

两端生成的任务都调用 `sync --log`，将每轮结果追加到 `.knowledge/scheduler.jsonl`：成功时记录处理计数，失败时记录阶段、确认保存点和安全错误代码。macOS 另保留 `.knowledge/scheduler.out.log` 和 `.knowledge/scheduler.err.log`。这些本地状态均不提交 Git。

```sh
knowledge status --workspace "你的知识库目录" --format text
knowledge doctor --workspace "你的知识库目录"
```

先看 `last_attempt`，再看独立保留的最后成功结果。正在运行时等待结束；失败或中断时按确认保存点及 `next_step` 重试，不删除锁文件绕过保护。`last_run` 的旧成功不代表本轮成功，生成的 Markdown 也不是实时状态面板。

安装后至少手动触发一次，并同时核对系统任务状态/退出结果与本工具的最新尝试。电脑需要开机，来源与认证需要可访问。`status`/默认 `doctor` 不查询系统任务是否安装，也不验证模型推理或联网发布；需要核验私有发布入口时显式运行 `doctor --publish`。

生成命令只写配置，不会自动注册或启用任务。CI 会在 macOS/Windows 上测试 Python 逻辑及调度文件结构；这与在每台用户机器实际注册并运行任务是两种验证。
