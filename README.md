# TradeCase V1

基于 B2B Lead Hunter 二次开发的外贸 Agent-native Skills 能力包。Codex / Claude Code 负责调查和判断；Python CLI 负责 Case、证据、确定性评分、规则检查和交付物。**不包含自研 Agent Loop、前端或后台调度服务，不发送邮件。**

已实现询盘解析、买家候选与消歧、来源记录、两类合规检查、英文回复草稿、人工行动项、可恢复 Case。七组演示均为显式 **SYNTHETIC / OFFLINE**；真实公开来源抽查和受阻能力另列，不能把测试通过当作真实买家或商品认证。

## 本地运行

Python 3.11+，macOS / Linux（使用 POSIX 文件锁）。在此仓库根目录执行：

```bash
uv sync --frozen --extra dev
uv run tradecase doctor
uv run tradecase install-skills --target both --scope project
uv run tradecase demo --fixture fixtures/case_strong --out cases/my-first-demo
uv run tradecase validate --case cases/my-first-demo --strict
uv run tradecase status --case cases/my-first-demo
```

打开 `cases/my-first-demo/report.md`。输出目录必须不存在；重复演示换一个目录名，已有 Case 不会被覆盖。没有 uv 时：`python3 -m venv .venv`，再运行 `.venv/bin/python -m pip install -e '.[dev]'` 并用 `.venv/bin/tradecase`。`pip install -r requirements.txt` 等价于可编辑开发安装，不安装旧 Serper/SMTP 服务栈。

```bash
PATH="$PWD/.venv/bin:$PATH" make check
```

检查真实执行 compileall、Ruff、pytest、依赖许可证与源码映射。当前本机结果与每阶段的红/绿日志见 [P0–P6 验收报告](docs/PHASE_REPORTS/)；远程 GitHub Actions 配置存在，但本任务没有推送或声称远程 CI 已运行。

## 使用自己的询盘

```bash
uv run tradecase init --inquiry /path/to/inquiry.eml --seller /path/to/seller.json --target-country US --platform amazon_us --out cases/inquiry-001
uv run tradecase research --case cases/inquiry-001
```

支持 `.eml`、`.txt`、JSON。原始 bytes/Base64/SHA256 和附件元信息保留；附件不执行。卖家资料格式见 [数据契约](docs/CASE_CONTRACT.md)。新 Case 缺少证据时不会自动完成；由宿主按 [trade-inquiry Skill](skills/trade-inquiry/SKILL.md) 收集资料，使用 `put`、`assess`、`compliance`、`draft`、`report`，最后严格校验。`research` 只准备未核实候选，不会自动搜索或确认身份。

采购公告请显式使用 `--case-type procurement` 并绑定截止时间证据；过期、冲突或无法确认会阻止Case完成。证据格式、时区范围及人工核验边界见 [数据契约](docs/CASE_CONTRACT.md)。

三个 Skill 的唯一源码在 `skills/`；安装器同步到项目内 `.agents/skills/` 和 `.claude/skills/`，校验相同内容哈希。参考文件路径以项目根为准。安装器保护已有同名和用户修改内容，不改 `~/.codex`、`~/.claude` 或个人授权设置。双宿主实际执行状态与相同业务提示见 [宿主验证](docs/HOST_VALIDATION.md)。

## 交付物和业务边界

每个完整 Case 有 `input.json`、`seller_context.json`、`candidates.jsonl`、`buyer_profile.json`、`evidence.jsonl`、`assessment.json`、`rules_snapshot.json`、`compliance.json`、`reply_draft.md`、`draft_review.json`、`next_actions.json`、`report.md`、`manifest.json` 与 `events.jsonl`。来源快照在 `snapshots/`，历史在 `.history/`。业务数据目录 `cases/` 不进入 Git。

- `validate --strict` 通过代表结构、引用和确定性推导一致，允许诚实的 `needs_review`；不证明自然语言内容真实。
- 评分使用固定规则和证据门槛，不代表信用评级。搜索摘要、推断邮箱或海关启发式不能冒充核实证据。
- country / platform 两类检查独立输出状态、severity、文本批注和整改动作。缺上下文或当前官方依据不能 pass。合成规则只测试引擎，真实研究规则保留未知字段。
- 英文草稿使用保守模板，未知价格、付款、MOQ、交期和资质待确认。审核哈希随依据变化失效；审核始终要求人确认，发送始终禁止。
- 直接公开读取有 DNS/IP、重定向、robots、大小、超时和持久请求预算。当前环境代理 DNS 返回保留地址，Reader 在线成功验证受阻；没有关闭门禁。

## 证据、限制与演示

[演示手册](docs/DEMO_RUNBOOK.md) · [能力状态](docs/CAPABILITY_STATUS.md) · [架构](docs/ARCHITECTURE.md) · [真实来源研究](docs/LIVE_SOURCE_RESEARCH.md) · [合规范围](docs/COMPLIANCE_SCOPE.md) · [P7真实环境验收](docs/PHASE_REPORTS/P7.md) · [P7业务案例](docs/P7_BUSINESS_EVALUATION.md)

实测的两条企业来源是 IKEA 与 UL Solutions 的公开官网材料，只支持官网自述，未证明真实采购意图。动态网页验证使用宿主浏览器，不是 Web Access。Crawl4AI 未安装；Web Access 缺完整许可证；Jina 只支持显式导入已读取响应。真实客户端到端质量、Windows、远程 CI 和可选第三方运行栈没有被伪报为通过。

## 源码与许可证

主上游：[B2B Lead Hunter](https://github.com/xiongQvQ/-b2b-lead-hunter-skill)，锁定 `ac27d0ec6627366337423bfcb1ba86c5be5a95a5`，保留完整 Git 历史与 MIT。实际包装联系人、搜索规范化、去重辅助、海关信号、草稿哈希和风险检查。AI Hunter 仅移植一个 MIT URL 分类文件并做安全适配；不引入其 Agent/backend/frontend。

[上游审计](docs/UPSTREAM_AUDIT.md) · [源码复用矩阵](docs/SOURCE_REUSE_MATRIX.md) · [精确源码哈希](docs/SOURCE_MANIFEST.json) · [第三方声明](THIRD_PARTY_NOTICES.md) · [实施基线](docs/baseline/TradeCase_V1_Codex_Implementation_Spec.md)

旧 `scripts/`、`templates/`、`references/` 中非 V1 入口保留以便追溯，不能直接当作当前使用手册。`send_smtp.py` 的函数与 CLI 均已硬禁用；没有“打开自动发送”的参数。可恢复历史源码不等于启用的产品能力。
