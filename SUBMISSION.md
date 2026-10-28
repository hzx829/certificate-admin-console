# 提交说明

当前选定交付为 **main 改进版**，包含 A2 改进及完整逐次提交历史，没有 squash 或丢弃提交。发布副本的应用实现基准是 `ec51c9c25a52bdcb5180619a4db00b21dcd4fa54`（原本地 SHA 为 `50370a5dee01886a6ba09a8d771ecba5ff830ed7`）。后续提交用于证据、文档及打包；发布前的历史脱敏及 SHA 变化见下节。

## 交付入口

| 内容 | 位置 |
| --- | --- |
| 当前完整 Git 历史包 | `artifacts/certificate-admin-console-main.bundle` |
| 最终提交 SHA、包 SHA-256、AI 证据截止时间 | `artifacts/main-submission.json`，以此包配套的记录为准 |
| 一键启动、API 身份、演示数据、A1–A7 复现 | [README.md](README.md) |
| 当前自动验收 | [16 项 HTTP 结果](artifacts/a2-regression-results.json)、[5 项前端结果](artifacts/a2-frontend-tests.txt) |
| Chrome 实测及实际请求证据 | [结果](docs/A2-RECOVERY-RESULTS.md)、[核验记录](artifacts/a2-ui-results.json) |
| AI 原生交互 | [ai/sessions/](ai/sessions/)、[索引](ai/session-index.csv)、[导出清单](ai/export-manifest.json) |
| 决策、纠错及完整性声明 | [决策日志](ai/decision-log.md)、[完整性声明](ai/completeness.md) |

GitHub 私有仓库：[hzx829/certificate-admin-console](https://github.com/hzx829/certificate-admin-console)，交付分支为 `main`。`ai/sessions/` 和完整提交历史一起推送；评估方需要该私有仓库的读取权限。

## 发布前的历史脱敏

2026-10-28 推送前检查发现：早期原生导出的内部上下文压缩副本漏掉平台内容脱敏。最新版已经修正，但仅修改最新文件不能清理 Git 中的旧副本。因此在独立发布目录 `D:\certificate-admin-console-github` 重建对应历史，原目录 `D:\certificate-admin-console` 及历史离线包保持不动，作为本机原始归档，不直接对外提交。

全部 19 个已有提交均保留，作者、提交者、时间、消息及父子关系不变；只修改 `ai/sessions/` 中合成的内部上下文记录、对应导出哈希和索引引用。原始按时间排列的用户消息、可见回复、命令、工具动作、失败和纠错不改写。业务代码在每个对应提交中完全一致。10 个提交因内容或父 SHA 变化而获得新的 SHA，见 [完整映射](ai/history-redaction-map.csv) 与 [核验报告](artifacts/history-redaction-verification.json)。

历史文档、测试报告和原生工具输出中的旧 SHA 是当时真实记录，可通过映射查到发布副本中的对应提交。之后的工作和推送使用发布目录，避免误推旧导出。

bundle 和配套 JSON 是包外生成物，不参与 Git 自身提交，避免把最终提交 SHA 写回同一个提交造成循环。交付离线包时同时提供这两个文件；远程交付时提供可访问 URL、main 分支和最终完整 SHA。

## 从离线包启动

在下载文件所在目录执行：

```powershell
git clone --branch main certificate-admin-console-main.bundle certificate-admin-console
cd certificate-admin-console
.\run.ps1
```

访问 http://127.0.0.1:8765。验证命令为 `.\run.ps1 verify`。全新克隆包含初始化代码，会生成小型演示数据；本机旧数据库和缓存不在 Git 包中。

## 重新导出与打包

仅验证并打包已经提交的 main：

```powershell
.\.venv\Scripts\python.exe scripts/export_ai.py --package-only
```

该命令要求 main 工作区干净，校验提交中的 AI 导出哈希和索引，再生成并验证 main bundle。它不会补录新的原生交互。

在有原生 JSONL 的机器上，补齐证据及当前回合最终回复后打包：

```powershell
.\.venv\Scripts\python.exe scripts/export_ai.py --source "C:\path\to\native-session.jsonl" --finalize
```

`C:\path\to\native-session.jsonl` 是占位路径，须替换为本会话原生记录。finalize 会等待发起该动作的回合结束，只提交 AI 证据文件，然后重新生成 main 包与配套元数据。在已配置且已授权的 GitHub 发布目录中加 `--push`，会推送 `origin main` 并核对远端 SHA；不加此参数只处理本地包。正式交付以最后一次成功打包的 SHA 为准，不用实现基准 SHA 代替交付 SHA。

## 时间线与保留的原版

本地实现窗口按用户指定为 2026-10-27 16:57–19:57（Asia/Shanghai）；此前从 14:36 开始的准备讨论仍保留在原生记录中。

- 原交付 `45b2c1657803d9b0f887ffa94395c1a22cfd1603` 在 17:53 归档，原包 `certificate-admin-console.bundle` 保留。
- 20:48 后进行了复核；21:17 后用户另行授权 A2 改进，21:31 归档为 `d91d07fc851dde8a4675da6db39eb4b59b9cb368`，历史包 `certificate-admin-console-a2.bundle` 保留。
- 当前 main 包汇总改进版及收尾材料，**不是对三小时内完成全部考试内容的声明**。评估方是否接受超时改进需按其规则认定。

历史 bundle 和旧 submission JSON 用于追溯，不作为当前 main 包的提交 SHA 来源。

## 尚待候选人完成

候选人已在 2026-10-28 提供 `written-answers.md`，从原目录复制到发布目录，并通过 SHA-256 核对确认字节一致。AI 仅处理文件交付，未查看、起草、翻译、润色或评审答案内容，不能据此核实其独立完成情况。

1. 本人确认第 6 部分未使用 AI，并补充本人可能在其他工具中产生的交互或行内补全使用情况。
2. 向评估方提供上述私有仓库的读取权限。

本次最终冻结在文档和证据导出后提交、推送及打包；后续只读校验和 SHA 回执不自动追加提交，避免回执使所报告的最终 SHA 再次变化。最终完整 SHA 见包外 `artifacts/main-submission.json`，应与远端 main 一致。

当前改进版的已知边界已在 README 披露，包括 60 秒等待预算、同标签页 sessionStorage 恢复范围，以及 Windows/Chrome 实测范围。
