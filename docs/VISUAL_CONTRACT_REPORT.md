# Visual Task 契约 CI 实际验证记录

后续远端发布已完成，见 [GitHub 实际执行记录](GITHUB_CONTRACT_CI_PUBLICATION.md)。以下保留发布前的本地验证历史。

日期：2026-10-30。原始 Git 基线：TradeCase `064e0568b4d45e8368a57f7fb6cf288b979ef8fb`；Creative Engine `9275a01`。两个仓库的既有未提交修改均保留，本次提交只包含新增固定契约检查及相关边界修复。

| 实际执行 | 结果 | 说明 |
| --- | --- | --- |
| TradeCase 新增契约检查 | 43 passed，退出 0 | 当前适配器、故障与破坏性变更反例、发布物不可改写、允许响应扩展 |
| TradeCase 现有完整 pytest | 534 passed / 4 skipped，退出 0 | 4 项 PostgreSQL/Redis 环境检查未配置，本次不计通过；该默认测试集不包含上面的独立契约目录 |
| Creative Engine 当前工作区类型检查 | 退出 0 | TypeScript |
| Creative Engine 当前工作区回归 | 121 passed，退出 0 | 包含该仓库原有未提交 live-provider 改动的测试 |
| Creative Engine 真实 HTTP 契约 | 26 个交互 passed，退出 0 | 真实路由、存储和 Worker；隔离 Mock，无真实模型 |
| Creative Engine 发布物检查器 | 10 passed，退出 0 | 与 TradeCase 同一检查器测试；包含真正临时 Git 历史上的修改/删除拒绝 |
| 干净 TradeCase 提交候选导出树 | 43 passed，退出 0 | 从 Git index 导出，不包含用户原有工作区改动 |
| 干净 Creative Engine 提交候选导出树 | 类型检查、26 个 HTTP 交互、118 个原有测试均通过 | 与工作区 121 的差别来自未提交的历史测试，不混入本次提交 |
| 两个干净导出树的真实双边联调 | 退出 0 | 实际 Python Client ↔ 实际 Node HTTP：计划、单次执行、重放、待审核、哈希、对账与取消 |
| Python 静态检查 | 退出 0 | 契约代码及修改的实际 adapter |
| CI YAML | 两份解析成功 | push / PR / manual / weekly，未设置 paths 或 continue-on-error |
| 两仓库发布物/检查器一致性 | 逐字节相等 | contract.json、SHA256SUMS、verify.py、test_verifier.py |

固定 `1.0.0` 的契约内容 SHA256 见同目录 `SHA256SUMS`；不是运行时从对方最新分支重录。首次 provider 调试发现未配置 Vision 会先返回 `VISION_NOT_CONFIGURED`，因此付费授权/预算反例改用不具备任何外部执行能力的专用哨兵供应商，在最终冻结前验证了精确授权拒绝及预算拒绝。这不是一次在线付费尝试。

实际双边运行的费用为 USD 0，所有图片为合成 fixture，测试素材保持 pending，未创建用户业务审批或邮件。本次没有使用已有 OpenAI 密钥、浏览器或用户工作数据库。确定性契约测试不证明真实模型的 Logo 还原、图片质量或生产部署配置。

## 远端状态（首次本地验证时的只读核查）

GitHub 连接器读取 TradeCase 返回 404，使用已有本机 gh 登录核查到私有仓库 `zianai/TradeCase`。默认 main，当时仅有 `TradeCase offline validation` 工作流；最新 Visual Tasks 提交的既有综合 CI 成功： https://github.com/zianai/TradeCase/actions/runs/41090581913 。它没有验证本次新契约工作流。

本次新增 workflow 未推送、未在 GitHub 执行。Creative Engine 未配置 remote。TradeCase 的 branch-protection 查询返回 403，提示 GitHub Pro 或公开仓库条件，故未确认/设置强制合并检查，也没有改变套餐、仓库可见性或任何远端设置。

完成状态：本地已实现、已实际验证、已本地提交；双仓库远端发布、首次 Actions 成功及必需检查规则仍待完成，不能称为已上线的合并门禁。
