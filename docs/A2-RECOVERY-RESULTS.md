# A2 最小改进与验证结果

本阶段由用户在原交付后另行授权，不计入原三小时成果；分支 `codex/a2-recovery`。原交付提交与 bundle 保留，未涉及 Section 6。

## 先验收，再实施

[验收合同](A2-RECOVERY-ACCEPTANCE.md) 与测试先提交于 `f98f055`，应用代码当时未改。
[旧实现失败报告](../artifacts/a2-before-results.json) 提交于 `0ee2032`：四个新增后端用例全部失败，包含已完成重放超时、20 秒未提交操作的五个等待者返回 503、忙碌错误缺少恢复协议、48 个等待者拖住列表。前端测试先执行时因恢复模块尚未实现而失败，此记录在原生会话中；它不是旧浏览器行为的替代证明。

## 实现范围

- 后端先验证权限和只读查询结果，已有结果直接重放；未找到时尝试写锁，取得锁后再次检查 key。证书、审计、结果依然在同一事务内提交，没有表结构变更。
- 写入前遇到 SQLITE_BUSY 释放连接和线程，异步等待 200 毫秒后重试，等待预算 60 秒。超出预算返回明确的 `503 / OPERATION_BUSY / Retry-After: 1`；执行期间其他数据库错误不被自动吞掉或重试。
- 前端在请求前按 actor 保存 `{key,payload}` 到 sessionStorage，刷新、身份切换后恢复同一操作。结果未确认时保留；结果确认后清理。无法保存时显示错误且不发送请求。
- 验证命令仍为 `./run.ps1 verify`：前端构建、16 项真实 HTTP 测试、5 项 Node 前端状态测试。

一次真实修正：第一版仅重试 BEGIN IMMEDIATE 的 BUSY，[第一版回归](../artifacts/a2-first-implementation-results.json) 有两项并发失败。[诊断日志](../artifacts/a2-concurrency-diagnostic.log) 定位到写事务前的课程 SELECT 也会短暂报 BUSY。因此重试范围扩为写入前的读取/拿锁阶段；写事务开始后的错误仍按原规则回滚并报告。

## 自动化结果

[完整回归](../artifacts/a2-regression-results.json)：16/16 通过，约 56.3 秒。[前端状态测试](../artifacts/a2-frontend-tests.txt)：5/5 通过。生产构建成功。

新增后端测试覆盖：已完成 key 在无关写锁下不到一秒返回；两个真实服务进程中首个事务提交前暂停 20 秒，六个同 key 调用得到相同 200 结果、异 payload 得到 409；48 个等待者期间列表两秒内可用；缩短到一秒的测试预算得到结构化 503、无副作用、原 key 可重试。

原 A1–A7 的资格、隔离、时区、回滚注入、撤销、重启及导出测试全部回归。十万行完整导出约 0.521 秒，过滤导出 0.244 / 0.120 秒；并发列表约 0.055 秒，比导出结束早 0.047 秒。

## Chrome 实测

通过 Chrome 浏览器工具操作三个隔离代理页面。实际网络记录为 [丢响应](../artifacts/a2-ui-loss-network.jsonl)、[未提交与预算耗尽](../artifacts/a2-ui-pending-network.jsonl)，[交叉核验结果](../artifacts/a2-ui-results.json) 来自这些记录、SQLite 计数和浏览器下载 CSV 的解析。

| 场景 | 实际观察和断言 |
| --- | --- |
| 发证提交成功后丢响应，再刷新 | 页面恢复原课程并禁用课程选择；出现 Continue original operation；重试与首次请求 key、payload 和完整结果相同，仍为 2 issued |
| Alice 待恢复时切 Bob，再切 Alice | Bob 正常发起自己的 key；Alice 恢复自己的原 key，没有混用 |
| 原结果确认后刷新，再主动发证 | 恢复记录已清理，新操作生成新 key，已有学员返回 skipped |
| 首次事务提交前暂停，刷新 | 数据库仍为 5 证书、5 审计、0 已提交操作；页面恢复原 key |
| 恢复请求等待预算耗尽 | 显示 Database is busy 与 Retry same operation；释放测试屏障后重试成功，三次请求同 key，响应 200/503/200；最终 7 证书、7 审计、1 操作 |
| sessionStorage 写入失败 | 测试代理仅为测试 HTML 注入存储异常；出现 No request was sent，提交按钮禁用；代理收到的发证 POST 数量为零，数据库不变 |
| 原有界面回归 | 详情、撤销取消后保持 ACTIVE、确认后 REVOKED 和一个新事件；排序、分页、空搜索正常；从第二页导出全部六条，解析 CSV 顺序正确 |

测试故障仅在 `tests/a2_server.py` 与 `tests/ui_proxy.py` 中，生产应用没有故障控制入口。

重现浏览器故障可启动单独数据库的应用，再运行：

```powershell
.\.venv\Scripts\python.exe -m tests.ui_proxy --port 8781 --target http://127.0.0.1:8780 --east-delay 0 --trace artifacts/repro-loss.jsonl
```

打开代理地址，第一次成功的发证响应会被丢弃。刷新、切换 actor、继续原操作后比较 trace 中的 received/completed 记录。用 `--no-drop-first --block-storage write` 可重现存储失败；代理的 trace 文件应没有任何 bulk POST。提交前屏障由 test server 的 TEST_COMMIT_GATE 指定路径，产生 `.ready` 后创建 `.release` 即可释放；TEST_BULK_WAIT_SECONDS=1 只供该测试服务器缩短等待预算。

## 保留的边界

60 秒是等待预算，不是对任意数据库故障或任意执行时间的成功承诺；长期忙碌仍需原 key 重试。sessionStorage 覆盖同标签页刷新和 actor 切换，不覆盖关掉标签页后的恢复。未新增队列、操作查询接口或跨设备恢复功能。
