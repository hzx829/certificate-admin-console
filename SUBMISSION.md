# 提交说明

当前选定交付为 **main 改进版**，已将 `codex/a2-recovery` 快进合并到 main；保留完整提交历史，没有 squash 或改写原记录。应用实现基准是 `50370a5dee01886a6ba09a8d771ecba5ff830ed7`，后续 main 提交用于证据、文档及打包。

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

`ai/sessions/` 已纳入 Git 提交，包含在上述历史包中。当前未配置远程仓库，尚未推送到 GitHub 或其他远程服务。提供远程 URL 时须包含 main 的完整历史及已跟踪的 ai 文件，不能只上传源代码快照。

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

`C:\path\to\native-session.jsonl` 是占位路径，须替换为本会话原生记录。finalize 会等待发起该动作的回合结束，只提交 AI 证据文件，然后重新生成 main 包与配套元数据。正式交付以最后一次成功打包的 SHA 为准，不用实现基准 SHA 代替交付 SHA。

## 时间线与保留的原版

本地实现窗口按用户指定为 2026-10-27 16:57–19:57（Asia/Shanghai）；此前从 14:36 开始的准备讨论仍保留在原生记录中。

- 原交付 `45b2c1657803d9b0f887ffa94395c1a22cfd1603` 在 17:53 归档，原包 `certificate-admin-console.bundle` 保留。
- 20:48 后进行了复核；21:17 后用户另行授权 A2 改进，21:31 归档为 `d91d07fc851dde8a4675da6db39eb4b59b9cb368`，历史包 `certificate-admin-console-a2.bundle` 保留。
- 当前 main 包汇总改进版及收尾材料，**不是对三小时内完成全部考试内容的声明**。评估方是否接受超时改进需按其规则认定。

历史 bundle 和旧 submission JSON 用于追溯，不作为当前 main 包的提交 SHA 来源。

## 尚待候选人完成

1. 独立完成第 6 部分并保存 `written-answers.md`；AI 不起草、翻译、润色或评审其内容。
2. 本人确认第 6 部分未使用 AI，并补充本人可能在其他工具中产生的交互或行内补全使用情况。
3. 提供评估方可访问的远程仓库 URL；补充材料提交后重新冻结最终 SHA 和打包。

当前改进版的已知边界已在 README 披露，包括 60 秒等待预算、同标签页 sessionStorage 恢复范围，以及 Windows/Chrome 实测范围。
