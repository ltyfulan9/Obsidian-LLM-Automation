# Windows 与 macOS 定时运行

先在目标机器安装本工具到持久的 Python 环境，并手动成功运行 `knowledge sync`。调度配置使用该环境的 Python 绝对路径；不是运行仓库中的相对脚本，所以从其他工作目录也能执行。

## macOS：launchd

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
Get-ScheduledTaskInfo -TaskName 'Personal Knowledge Daily'
```

也可在任务计划程序中导入 XML，选择能访问源目录和各 CLI 认证的账户。需要推送时在生成命令中加入 `--push`。Windows 生成器为带空格的路径进行参数引用，并设置错过计划后可启动与禁止重叠实例。

## 时区与日志

调度时间采用操作系统本地时间；资料归档日期采用知识库配置中的 `timezone`。跨机器同步时建议两台机器显式使用同一归档时区。

macOS 标准输出与错误写入 `.knowledge/scheduler.out.log`、`.knowledge/scheduler.err.log`。两端都可通过 `knowledge status --workspace ...` 查看最近一次成功完成的结果。发生失败时以调度器退出码及错误输出为准；旧的 last-run 不代表本轮成功。

生成命令只写配置，不会自动注册或启用任务。CI 会在 macOS/Windows 上测试 Python 逻辑及调度文件结构；这与在每台用户机器实际注册并运行任务是两种验证。
