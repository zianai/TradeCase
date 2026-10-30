# GitHub 契约 CI 发布记录

日期：2026-10-30。用户明确授权推送本次 CI 改动、创建独立私有 Creative Engine 仓库并运行两边契约检查；只发布本次 CI 必需的契约测试，不上传旧测试集、密钥及运行数据，不升级套餐或公开仓库。

## 首轮已验证的远端执行

| 仓库与分支 | 精确功能提交 | 契约检查与实际结果 |
| --- | --- | --- |
| [TradeCase](https://github.com/zianai/TradeCase/tree/codex/tradecase-visual-tasks)，`codex/tradecase-visual-tasks` | `8b85c95f80b6759ed5e62bb25cec329857423a14` | [`visual-contract-consumer-v1` 成功](https://github.com/zianai/TradeCase/actions/runs/41101225734) |
| [CreativeEngine](https://github.com/zianai/CreativeEngine)，`main` | `a1b068ea889409065a382de33536afdfbda5c7df` | [`visual-contract-provider-v1` 成功](https://github.com/zianai/CreativeEngine/actions/runs/41101261005)；10 项检查器测试、26 个真实 HTTP 交互 |

已通过 GitHub API 核对两次 run 的 `head_sha`、`status=completed`、`conclusion=success`。Creative Engine 日志同时证明类型检查、前端构建及契约执行成功；Mock 执行费用为 USD 0。TradeCase 的本地同版本契约检查为 43 项，GitHub job 成功，JUnit artifact 由工作流保留。既有 TradeCase 综合 CI 也已成功，未上传新的旧测试集。

这是一份精确绑定上述功能提交的结果记录；本记录后续文档提交的检查状态以各仓库 Actions 为准，不拿其他 SHA 的结果冒充当前提交结果。首次读取 GitHub 元数据/日志遇到过短暂 502/503，最终以成功返回的实际 run 和日志为依据，没有重新推送或伪造通过。

## 发布范围与历史隔离

TradeCase 此次推送相对已存在远端 `064e0568b4d45e8368a57f7fb6cf288b979ef8fb` 仅新增/修改 14 个路径，旧工作区测试、访问策略改动和数据保持本地。原已存在于远端的历史不在此次修改范围。

Creative Engine 的本地旧历史本来包含旧 `tests/` 和截图/验证日志，因此没有直接推送原 main。新远端从上述无父提交的根快照开始，初始 86 个已审核文件：应用源码、Skills/规则、接口示例、依赖锁文件、必要文档及 `contracts/visual-task/`。已通过远端 tree 和 commit API 确认旧历史、旧测试、截图、日志、数据库和图片未随祖先进入新仓库。只有无凭据的 `.env.example` 模板；真实 `.env`、密钥和运行数据未上传。

原 `creative-engine` 的 main 及未提交工作没有改写。GitHub 发布分支为 `codex/github-private`，位于同级 `creative-engine-github` 工作树，跟踪 `github/main`；本地该 remote 的默认 push refspec 仅指向发布分支。后续迭代使用此工作树；不要合并旧 main 的整段历史，应选择性移植审核过的源码变更，以免重新带入被排除的文件。

独立复核覆盖精确提交、发布范围、常见凭据模式、契约一致性及实际本地检查。GitHub 的成功证明在托管 runner 上执行了这些检查，不证明真实图像模型质量或生产部署完成。

## 保留设置与限制

两个仓库均已读回确认 `private=true`；没有升级套餐、改为公开、修改计费或设置强制合并规则。当前这是自动运行的检查，不声称失败能强制阻止合并。

TradeCase 的工作流在当前功能分支上响应 push/PR；其每周计划及默认分支手动入口需在该分支合入 main 后启用。本次没有擅自合并已有 Visual Task 功能到 main。CreativeEngine 的工作流已在默认 main，含 push、PR、手动及每周触发。

没有配置 GitHub 模型密钥、调用付费生图服务、发送邮件或改变任何用户案例的审批状态。CI 日志/JUnit 为合成测试证据，不包含业务运行数据。
