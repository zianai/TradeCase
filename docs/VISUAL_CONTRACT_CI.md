# TradeCase ↔ Creative Engine 固定契约检查

核查日期：2026-10-30。原先 TradeCase 只有归档 OpenAPI 和未提交的本地视觉测试；Creative Engine 的通用接口测试没有覆盖 TradeCase 实际 HTTP 适配器。原有 GitHub 综合 CI 成功不等于双边契约已验证。

## 固定检查

| 仓库 | 稳定检查名称 | 实际执行对象 |
| --- | --- | --- |
| TradeCase | `visual-contract-consumer-v1` | 当前 `CreativeEngineClient` 对固定版本请求/响应执行计划、提交、幂等、查询、下载、对账、取消 |
| Creative Engine | `visual-contract-provider-v1` | 当前真实 HTTP 服务、临时 SQLite、隔离端口、Mock Provider 对同一份发布契约执行 26 次交互 |

两边各有 `.github/workflows/visual-contract.yml`，在所有 push / pull_request 触发，无路径过滤，另有手动和每周检查。周计划仅在默认分支存在该 workflow 后运行。权限只有 `contents: read`；失败会使 job 失败，保留 JUnit 或日志；不使用 `continue-on-error`，不依赖另一仓库 HEAD、已运行服务、生产 DB、付费密钥或邮件配置。

当前契约发布物为 `contracts/visual-task/1.0.0/contract.json` 和 `SHA256SUMS`，两仓库内容必须一致。TradeCase 维护消费方需求，Creative Engine 保存相同发布物；这是 HTTP 交互契约，不复制对方业务代码。`contracts/creative-engine-1.0.0.openapi.json` 仍是最初完整接口归档；固定检查使用更小的可执行消费方契约，避免新增无关模型、路径或能力导致整份 OpenAPI 快照比较误报。

## 兼容与版本规则

- 明确请求 `X-API-Version: 1.0.0`；不支持的显式版本在执行前返回 409。现有未发该头的本地客户端继续使用 v1。
- 服务软件版本、模型名称、Skill 版本和 HTTP 契约版本分开演进。新增业务模块、新供应商或无关端点不要求对方更新内部实现。
- 允许新增响应字段；必要字段的删除、类型或语义变化必须失败。请求使用固定精确断言，意外传输买家数据、扩大允许变更或预算会被拦下。
- 已发布的版本目录不可改写或删除。CI 相对 PR base / push before 的 Git 提交检查旧发布物，防止通过重录 fixture 把破坏性改动变绿；新增需求发布新版本目录，保留仍受支持的旧版本检查。
- 新视频、3D 或不同资产语义必须显式协商能力和契约，不能把图片 v1 的 MIME、证据或审批规则改掉。旧客户端遇到未知执行状态进入待对账，遇到未知资产格式拒收。
- 破坏性升级先提供并行兼容接口、发布新契约和迁移说明，再迁移调用方；旧版本停止支持需明确发布退役计划，不能靠同步修改两边内部代码或测试断言绕过。

发布新消费需求时，把审核过的新契约发布物复制到生产方，同版本同 SHA，分别运行检查。日常 CI 完全离线使用仓库内固定发布物，避免拉取浮动 main 或使用跨仓库访问令牌。语义守卫使用合成反例验证，并不声称穷尽所有输入组合。

## 检查边界

覆盖认证和版本拒绝、授权原始素材与事实映射、计划范围、零费用预算、未授权付费拒绝、预算超限拒绝、幂等重放和冲突、异步待审核、来源/产品事实/任务关系、PNG 原始字节与 SHA256、费用字段有效性、未知提交不自动重试、只读对账与取消。

生成资产不能成为 Product Truth；文件 QA 通过和远端 approved/completed 都不等于 TradeCase 业务审批。契约回归另外验证缺失 QA 不视为通过、阻断 QA 不能被总体 pass 掩盖、下载不跟随资产里的任意 URL。Mock 素材不是视觉效果或真实供应商质量证明。该检查不修改任何用户案例、审批、草稿或邮件。

此次附带修复：Engine 原先忽略 `X-API-Version`，现在拒绝不支持版本；TradeCase 原先把缺失 `cost_usd` 当作 0，现在拒收未知费用，避免伪称免费。

## 本地复现

TradeCase：

```sh
.venv/bin/python contracts/visual-task/verify.py
.venv/bin/python -m pytest contracts/visual-task/test_consumer.py contracts/visual-task/test_verifier.py -q
```

Creative Engine：

```sh
pnpm install --frozen-lockfile
python3 contracts/visual-task/verify.py
pnpm test:contract:tradecase
```

额外真实双边联调（在 Creative Engine 根目录，Python 指向已安装 httpx 的解释器）：

```sh
CONTRACT_CONSUMER_ROOT='/absolute/path/to/tradecase-v1' \
PYTHON='/absolute/path/to/tradecase-v1/.venv/bin/python' \
pnpm test:contract:tradecase
```

该启动器仅注册 Mock 和一个永远不执行生成的付费拒绝哨兵，不加载真实 Provider；所有 HTTP 指向新建临时 DB 的 loopback 随机端口。两个正式 CI job 各自独立，双边联调是额外验证，不以另一仓库当前工作区作为固定依赖。

## GitHub 启用状态与限制

本次契约 CI 已按用户后续授权发布到两个私有仓库，首轮 GitHub Actions 均实际成功。精确提交、运行链接、发布范围及安全审计见 [GitHub 发布记录](GITHUB_CONTRACT_CI_PUBLICATION.md)。

CreativeEngine 的新私有仓库采用不含旧测试及运行数据的无父根快照；保留原本地历史。TradeCase 推送到现有功能分支，未合并 main。没有升级套餐或修改仓库可见性；分支保护套餐限制保持原状，因此“CI 自动运行”仍不等于“强制合并门禁”。

过去不提交测试集的约束继续适用于旧测试、客户数据、截图和运行产物。本次固定 CI 所需的合成协议发布物和可执行检查随代码版本管理，否则独立仓库无法长期执行契约检查。
