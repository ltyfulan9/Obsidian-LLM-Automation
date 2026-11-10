# 备份、恢复与运行状态

状态 ZIP **不加密，可能包含私人正文**。它不是整个旧仓库的备份：

- 包含 SQLite、配置、生成清单/页面、Notes、运行状态和 `.gitignore`。
- 不包含未受管旧目录、外部源文件/附件、`.git`、认证和部署脚本；这些另靠 Git 或原文件备份。

## 备份与校验

```sh
knowledge backup --workspace "$HOME/PersonalWiki" --output "$HOME/knowledge-state.zip"
knowledge restore --workspace "$HOME/RecoveredWiki" --input "$HOME/knowledge-state.zip" --dry-run
```

每次使用新包名，已有文件不覆盖；输出须在工作区和公共源码之外。`backup` 返回文件位置、文件数与字节数。`--dry-run` 校验但不创建目标，坏 ZIP、校验不符或已有目标都会拒绝。

## 恢复到新目录

```sh
knowledge restore --workspace "$HOME/RecoveredWiki" --input "$HOME/knowledge-state.zip"
knowledge doctor --workspace "$HOME/RecoveredWiki"
knowledge build --workspace "$HOME/RecoveredWiki"
knowledge search --workspace "$HOME/RecoveredWiki" '观察' --format text
knowledge review --workspace "$HOME/RecoveredWiki"
```

恢复只写入尚不存在的新目录，不调用模型、采集来源、联网或操作 Git。恢复后先检查来源路径和引擎配置，再决定是否同步；源文件、CLI 认证和 GitHub 设置需要在新机器单独确认。不要将恢复当作自动重新发布。

## 看懂状态

```sh
knowledge status --workspace "$HOME/PersonalWiki" --format text
```

- `last_attempt`：最近同步尝试，可能为 `running`、`succeeded`、`failed` 或 `interrupted`；未运行时为 `null`。
- `last_run`：最近一次完整成功的同步，失败不覆盖它；它不能证明本轮健康。
- `phase`、`error`、`next_step`：失败阶段及修复入口，不记录原文或模型 stderr。
- `saved`：哪些阶段已确认保存；`false` 表示尚未确认，不保证没有发生。
- `requested`：本轮是否要求 GitHub 或 Magpie 发送，不能用未请求的阶段判断故障。

生成失败可先 `build`，发布失败可先 `publish`；随后按原参数再运行 `sync`，才记录新的整轮成功。[完整排错](workflow.md#错误恢复)。
