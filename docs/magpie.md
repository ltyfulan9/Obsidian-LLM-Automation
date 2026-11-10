# Magpie：每天 21:00 同步小型对话摘要

本仓库负责采集、摘要、Wiki 和压缩。Magpie 负责自己的认证、加密与 GitHub 备份。Jev 未接入，也不需要 TypeSafe 密钥。

## 分工与大小

- Obsidian 笔记进入个人知识库；飞书尚未接入，可先导出 Markdown 再作为来源。
- `codex`、`claude`、`export` 来源的对话小结可以另外打包给 Magpie。
- 默认只带最近 7 个自然日、最多 200 条记录，gzip 上限 **64 KiB**，解压内容上限 **256 KiB**。
- 每条记录只带短标题、主题、最多 600 字符小结，以及有长度上限的要点、决定和问题。没有原始会话正文、工具输出、隐藏推理或认证配置。
- 包超出预算时从最早的记录移出，`manifest.json` 明确记录省略数量；完整知识仍在本机数据库中。
- 文件内容与 gzip 时间戳固定，同样的摘要生成同样的压缩字节，避免因打包时间造成无意义变更。

这些限制针对本项目新增的对话包。Magpie 的其他配置、技能和备份历史仍占各自空间；它的整体加密备份不承诺小于 64 KiB。

## 一次性接入资源库

Magpie 当前的加密备份携带已登记的资源库技能及其文件，不会自动携带任意外部目录或本项目数据库。因此本仓库提供一个小型、可按需查询的集成包：

`integrations/magpie/personal-chat-digest/`

将此目录复制到本机持久位置，再从 Magpie 的资源库导入一次。它带有摘要读取脚本，没有可执行的来源指令；只在你要求回顾过往对话时读取数据。不要将带私人数据的已部署副本复制回公共工具仓库。

集成依赖已登记的 `personal-chat-digest` 包和 `SKILL.md`。未导入时 `--magpie` 会明确失败，不会把“文件已生成”冒充“已同步”。其他电脑通过 Magpie 恢复资源库后，可用包中的读取脚本查询小结。

## 本机配置

在知识库的 `.knowledge/config.json` 添加以下配置，路径按本机填写：

```json
{
  "magpie": {
    "executable": "D:\\app\\Magpie\\magpie.com",
    "data_dir": "D:\\app\\Magpie\\data",
    "keep_days": 7,
    "max_kib": 64
  }
}
```

这是现有配置中的一个字段，不替换其他来源和引擎设置。Mac 的 executable 填应用实际程序路径，data_dir 填 Magpie 实际配置目录；可用 `magpie data` 查看。

## 先验证，再自动化

只生成压缩包，检查 `manifest.json` 和 gzip 大小：

```sh
knowledge export-magpie --workspace /path/to/PersonalWiki --output /path/to/personal-chat-digest
```

完成一次性导入后，运行整条流水线：

```sh
knowledge sync --workspace /path/to/PersonalWiki --magpie
```

执行顺序为：确认 Magpie 目标 GitHub 私有且包含 Library、采集变更、生成摘要和 Wiki、更新已登记集成包、调用 `magpie github now`。不导出或回显 Magpie 的令牌与口令。`--push` 独立控制完整 Wiki 的私有 Git 发布；`--magpie` 控制小型对话包，可同时使用。

## 每天北京时间 21:00

机器时区设为中国标准时间时，以下是每日 21:00，而非每 30 分钟：

```powershell
knowledge schedule --workspace 'D:\Knowledge\PersonalWiki' --platform windows --hour 21 --minute 0 --magpie --output 'D:\Knowledge\knowledge-daily.xml'
```

```sh
knowledge schedule --workspace ~/PersonalWiki --platform macos --hour 21 --minute 0 --magpie --output ~/Library/LaunchAgents/io.personal.knowledge.daily.plist
```

任务注册方法见 [scheduling.md](scheduling.md)。若希望只在每天 21:00 上传，可在手动验证成功并注册任务后，执行 `magpie github auto off`，避免同时保留每小时同步。该命令关闭的是 Magpie 的间隔上传，不会关闭外部每日任务。

调度文件生成不等于已启用任务；本仓库不会在安装包时悄悄修改本机同步频率。已部署任务需要能访问客户端记录、模型 CLI 和运行中的 Magpie。

## 出错时

- 私有目标、Library 或集成包核验失败：不读取新的来源、不上传。
- 模型短暂超时：有次数上限的重试；成功分段缓存保留，重跑可复用。
- Wiki 生成中断：生成日志用于下次恢复；人工编辑冲突会停止，不会强行覆盖。
- Magpie 上传失败：本地摘要和压缩包保留；修复连接后重试，不重传原始日志。
- 导出清单有省略数量：查看本地完整 Wiki，或在明确接受空间增加后调整预算。

Magpie 的资源库文件携带规则依据 [官方 carry.go](https://github.com/yetone/magpie/blob/main/internal/library/carry.go)；本集成沿用它的现有备份机制，没有修改 Magpie 程序。
