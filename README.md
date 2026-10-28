# Certificate Admin Console

多租户培训平台的结业证书后台。React + FastAPI + SQLite；支持 actor 切换、证书搜索／分页／排序、批量发证、详情与审计、撤销和 CSV 导出。

当前交付分支为 **`main`**，已包含 A2 改进，保留完整开发和纠错历史。[A1–A7 验收方案](docs/ACCEPTANCE.md) 与 [A2 补充验收](docs/A2-RECOVERY-ACCEPTANCE.md) 均在相应实现之前提交。

当前实现通过 **16 项真实 HTTP 验收 + 5 项前端状态测试**，并完成 Chrome 实测，包括刷新恢复、丢响应、身份切换、存储失败和主要工作流。见 [自动化结果](artifacts/a2-regression-results.json)、[Chrome 核验结果](artifacts/a2-ui-results.json) 与 [改进说明](docs/A2-RECOVERY-RESULTS.md)。版本、打包、时间线和待补材料统一见 [提交说明](SUBMISSION.md)。

## 启动

需要 Python 3.12+、Node.js 22.12+ 或 24+，首次安装依赖需要网络。在仓库目录执行一个命令：

```powershell
.\run.ps1
```

打开 **http://127.0.0.1:8765**。脚本查找可用 Python，创建 `.venv`，按锁文件安装依赖，构建前端，初始化演示数据库并启动完整应用。重复启动保留已有证书、撤销和操作记录。端口冲突时使用 `.\run.ps1 -Port 8769`；Ctrl+C 停止服务。

Linux/macOS 或已将 Python 配置到 PATH 的环境可使用 `python3 run.py`（Windows 也可用 `python run.py`）。Windows 启动已实测，其他操作系统未进行实机验证。

默认数据在 `data/demo.db`，不纳入 git。需要全新数据时，显式指定一个新的文件，而不要删除或覆盖已有数据：

```powershell
.\run.ps1 start -Database data/demo-fresh.db
```

本机已有的 `data/ready-demo.db` 等数据库可能包含操作记录，不承诺仍为初始数据。Git 交付包含初始化代码，不包含本机数据库、依赖缓存或临时验证目录；全新克隆首次启动会生成默认小数据集。

## 身份与默认数据

无需登录，在页面右上角选择 actor。API 使用 `X-Actor-Token`：

| 管理员 | token | 租户及时区 | 课程 |
| --- | --- | --- | --- |
| alice@east.test | alice-east | East，Australia/Sydney | 101 Safety 101，102 First Aid |
| bob@west.test | bob-west | West，Australia/Perth | 201 Safety 101 |

双方都有独立的 Alex Lee 和 Safety 101。每个 Safety 101 中有已完成未获证、未完成、已有证书的学员。默认 East 证书 ID 为 1、3、4、5，West 为 2；1 和 2 使用题目指定 UTC 时间，3 用于冬季检查，4、5 用于日期边界和同日排序。

API 文档：**http://127.0.0.1:8765/docs**。`GET /api/actors` 公开演示身份选项；其他业务接口验证 actor 并从管理员记录取得租户，不使用调用方传入的租户决定权限。这是题目限定的身份模拟，不能作为生产认证。

一次批量请求示例：

```powershell
$headers = @{ 'X-Actor-Token' = 'alice-east'; 'Idempotency-Key' = 'demo-bulk-1' }
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/api/bulk-issue `
  -Headers $headers -ContentType application/json -Body '{"course_id":101}'
```

重试时保留同一 key 和请求体。真正的新操作使用新 key；同一 key 换成另一门有权访问的课程返回 409。未知请求字段返回 422。

## 自动化验收和逐项复现

第二个命令执行构建与验收：

```powershell
.\run.ps1 verify
```

跨平台入口：`python3 run.py verify`。验收启动独立服务器，使用临时数据库和真实并发 HTTP 请求；不会修改默认演示数据。当前完整回归结果写入 `artifacts/a2-regression-results.json`，随后执行前端状态测试。原 12 项报告保存在 `artifacts/acceptance-results.json`。首轮曾因测试资源没有正确关闭而失败，[原始失败报告](artifacts/acceptance-first-run.json) 与修复提交均保留。

以下从全新小数据集开始；修改数据的场景应单独使用新数据库，或直接运行隔离的自动化验收。

| 场景 | 复现与通过标准 | 自动化用例 |
| --- | --- | --- |
| A1 隔离 | Bob 查询 East 编号 E-DEMO-001、导出该编号：空结果；GET `/api/certificates/1`、POST `/api/bulk-issue` 指定 101、POST `/api/certificates/1/revoke`：404，无证书、审计或操作写入。双方 Alex 的结果只属于各自租户。 | test_A1_tenant_isolation |
| A2 重试 | 同一 key 对 101 顺序及并发调用，所有结果相同；只新增 2 张证书和 2 条发证审计、1 条操作。重启后重放仍相同。包含两进程 20 秒提交前等待、48 个等待者下列表可用、已完成结果免写锁重放、等待预算及安全重试。 | tests/a2_recovery.py 中七个 test_A2 用例 |
| A3 key 冲突 | Alice 先以 K 对 101 发证，再以 K 对 102 请求：409，原结果不变、102 无写入；原请求仍可重放。并发不同课程也只能执行一种。 | 两个 test_A3 用例 |
| A4 结果 | East 101 首次发证：Alex、Morgan issued；Jamie skipped/not_completed；Casey skipped/already_certified。验收脚本注入单个审计写入失败，确认该学员没有半成品；注入最终结果写入失败，确认整个批次回滚。 | 两个 test_A4 用例 |
| A5 时区 | 详情 1 显示 2026-01-11 00:30；Bob 查看详情 2 显示 2026-01-10 21:30。3 显示冬季 2026-07-10 23:30。日期升序 ID 为 4、1、5、3，降序为 3、1、5、4；分页和 CSV 一致。 | test_A5_dates_sorting_and_query_parity |
| A6 导出 | 按下节生成大数据，搜索 Alex、按 Learner 升序，连续导出两次；各有 33,299 条相同且有序的记录，首次下载期间列表可用。完整十万条导出也必须在 60 秒内完成。 | test_A6_large_export |
| A7 撤销 | 页面查看有效证书，先取消撤销，确认未变化；再确认撤销，状态变为 REVOKED，恰好增加一条撤销审计。重复或并发请求不新增事件，首次撤销时间不变。审计失败时状态回滚。 | 两个 test_A7 用例 |

单独运行某个用例，例如：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.acceptance.Acceptance.test_A2_concurrent_replay -v
```

完整断言、故障注入方法和数据约定见 [验收方案](docs/ACCEPTANCE.md) 与 [验收脚本](tests/acceptance.py)。

## 十万条数据

显式创建独立的新数据库，默认小数据集保持不变：

```powershell
.\run.ps1 seed-large -Database data/large.db
.\run.ps1 start -Database data/large.db -Port 8767
```

打开 http://127.0.0.1:8767。East 证书总量恰好为 100,000，West 保留一张证书。生成器拒绝默认 `data/demo.db` 和任何已存在的目标文件；需要再生成时使用另一个新文件名。它制造同名、同课程和同日期的数据，也包含逗号、引号、换行字段以检查 CSV 编码。

导出接口示例：`GET /api/certificates/export?q=Alex&sort=learner_name&direction=asc`，携带 Alice header。导出采用一次有序查询、读快照和分批流式编码；排序最后追加唯一 ID。分页参数不会限制导出范围。

当前实现的 Windows 本机测量：33,299 行的两次导出约 0.244 秒、0.120 秒；100,000 行完整导出约 0.521 秒；并发列表请求约 0.055 秒，在首次导出结束前完成。数值及时间重叠记录保存在当前自动化报告中，其他机器需要重新测量。

## 关键实现选择

- 幂等操作结果持久化，不依赖进程内缓存。操作、证书和审计在同一外层事务内提交；逐学员 savepoint 允许可恢复的局部失败。
- SQLite 启用 WAL、外键和唯一约束。批量发证先只读重放，再尝试 BEGIN IMMEDIATE，取得写锁后复查 key。写入前的 SQLITE_BUSY 使用异步有界重试，等待期间不占连接或工作线程；60 秒等待预算耗尽返回 503、code=OPERATION_BUSY、Retry-After: 1，调用方继续使用原 key。其他数据库错误不自动重试，撤销等其他写路径仍使用原 15 秒锁等待。
- 同一租户／课程／学员一生最多一张证书，撤销后不重发；没有重发、删除或编辑证书功能。
- UTC 时间保留，按租户 IANA 时区转换；本地日历日期在发证时计算保存用于排序，租户时区在本题中固定。
- 列表和导出共用筛选与排序规则；搜索匹配姓名或编号，英文大小写不敏感，通配符字符按普通输入处理。CSV 包含已撤销记录。
- UI 的旧 actor 请求被取消或丢弃。发请求前按 actor 将 key 和完整 payload 保存到 sessionStorage；刷新或切回 actor 后可继续原操作，未知结果下冻结原课程和 key。确认完成才清理恢复记录；存储失败时阻止发送。sessionStorage 不承诺关闭标签页后的恢复。

## AI 证据与提交状态

完整原生会话（含此前准备讨论、未采用建议、工具调用、编辑及失败）在 [ai/sessions](ai/sessions/)，索引为 [ai/session-index.csv](ai/session-index.csv)。另见 [决策记录](ai/decision-log.md)、[完整性声明](ai/completeness.md)、[导出清单](ai/export-manifest.json)。

GitHub 私有仓库：[hzx829/certificate-admin-console](https://github.com/hzx829/certificate-admin-console)。`main` 包含完整开发历史和 `ai/sessions/` 原生证据；评估方需要仓库读取权限。发布前补齐了历史导出中内部上下文副本的脱敏，保留每个提交的代码、作者、时间和消息；新旧 SHA 对照见 [历史映射](ai/history-redaction-map.csv)。

统一交付包为 `artifacts/certificate-admin-console-main.bundle`，完整 SHA、包哈希及证据截止时间见配套 `artifacts/main-submission.json`。导出脚本 `scripts/export_ai.py --finalize` 会等待当前回合结束、补录最终回复、提交证据并重新生成此包；不覆盖原版或 A2 分支归档。使用方法见 [提交说明](SUBMISSION.md)。

提交仍待候选人独立完成 `written-answers.md`、本人确认第 6 部分未使用 AI，并向评估方提供上述仓库的访问权限。当前 main 含原定 2026-10-27 16:57–19:57 窗口结束后的改进，完整时间线保留在证据和提交说明中。

已知范围限制：只在 Windows、Chrome 实测；批量发证超过 60 秒等待预算可返回 503，需原 key 重试；sessionStorage 不保证关闭标签页后恢复；单次超大课程的批量结果渲染未单独优化；CSV 中断后需要重新下载，没有断点续传。不包含题目排除的生产认证、部署或通知。环境差异仍须用提供的脚本验收。
