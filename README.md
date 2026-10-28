# TradeCase

外贸询盘调查与跟进工作台：将询盘、买家调查、证据、风险、回复草稿和人工决策组织成可追溯的 Case。

TradeCase 在 [B2B Lead Hunter](https://github.com/xiongQvQ/-b2b-lead-hunter-skill) 的基础上开发，保留原有 CLI、业务规则和三个可移植 Skills，同时提供 FastAPI、LangGraph、PostgreSQL、Redis/ARQ 和 Next.js 工作台。

> **状态：本地与合成数据验收完成，生产与真实外部服务尚未验收。** 模型、公开数据源、SMTP、CRM 和 S3 的实际接入能力取决于配置、授权及服务环境。真实外发默认关闭；草稿审核不等于发送授权。不要将合成案例当作真实买家或法规依据。

## 可以做什么

- 粘贴或导入询盘，保存原始内容，管理案件、标签和跟进。
- 调查企业身份与采购需求，区分事实、推断和未知，保留来源快照与引用。
- 运行确定性评分及市场、平台两类规则检查，生成英文回复草稿和报告。
- 通过人工审核、版本和哈希校验保护草稿；外部动作另需明确授权及幂等校验。
- 使用 LangGraph 持久工作流、数据库任务租约和可替换 Agent/工具适配器恢复处理进度。
- 导出 JSON、Markdown、PDF；使用 Docker Compose 部署并演练备份恢复。

## 快速开始：本地工作台

需要 Python 3.11+、Node.js 24+ 和 [uv](https://docs.astral.sh/uv/)。下面的默认配置使用本地 SQLite，模型及真实发送均关闭。

```bash
uv sync --frozen --extra platform --extra dev
mkdir -p .tradecase
uv run tradecase-workbench init-db
uv run tradecase-workbench provision-user --tenant local --name reviewer --role admin --token-file .tradecase/reviewer-token
TRADECASE_DEMO_ENABLED=true TRADECASE_PORT=8800 uv run python -m tradecase.platform.server
```

另开一个终端：

```bash
cd frontend
npm ci
TRADECASE_API_URL=http://127.0.0.1:8800 npm run dev -- --port 3300
```

打开 [http://127.0.0.1:3300](http://127.0.0.1:3300)，在「连接设置」中输入 `.tradecase/reviewer-token` 的内容。令牌是访问凭证，请勿提交、分享或放入截图。使用「导入询盘」中的合成演示，可在不调用真实模型或发送邮件的情况下体验调查、审核和跟进。

生产或多 Worker 环境使用 PostgreSQL 和 Redis/ARQ；配置、迁移、私密凭据、HTTPS、备份与恢复步骤见 [部署说明](docs/WORKBENCH_DEPLOYMENT.md) 和 [运维手册](ops/README.md)。当前 Compose 配置默认使用模拟模型并禁止真实外发。

## 兼容 CLI 与 Skills

```bash
uv run tradecase doctor
uv run tradecase install-skills --target both --scope project
uv run tradecase demo --fixture fixtures/case_strong --out cases/my-first-demo
uv run tradecase validate --case cases/my-first-demo --strict
```

演示目录必须不存在；`cases/` 不纳入 Git。原始 CLI 的 Case 文件与工作台数据库各自管理，参见 [使用说明](docs/WORKBENCH_USAGE.md) 和 [Skills 目录](skills/CATALOG.md)。

## 验证与已知边界

```bash
PATH="$PWD/.venv/bin:$PATH" make check
python ops/verify_infrastructure.py   # 需要 Docker；创建并清理隔离的测试容器
cd frontend && npm run typecheck && npm run build
```

[完整交付报告](docs/FULL_DELIVERY_REPORT.md)记录实际执行结果、浏览器与 Compose 恢复演练及限制。现有测试使用合成资料和模拟连接器；它们不证明真实来源内容、买家身份或法律合规。附件不执行，也没有内建杀毒；真实注册库、邮箱账户同步和商业 CRM 尚未接入验证。真实 API、供应商凭据、数据许可证及生产安全配置需由部署者单独验证。默认配置不进行付费模型调用或外部写入。

## 贡献与许可证

欢迎在公开之前先审查代码、数据来源权限、依赖许可证与安全配置。请勿提交真实询盘、个人信息、访问令牌、密钥、数据库或备份；安全问题应避免在公开 issue 中披露敏感细节。

项目继承 [MIT 许可证](LICENSE)及原作者版权声明；上游代码和第三方依赖说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 [源码复用矩阵](docs/SOURCE_REUSE_MATRIX.md)。依赖许可证清单并不等同于完整法律审查。将仓库公开前应完成这些审查并确认维护者和安全问题的联系方式。

更多资料：[中文入口](README.zh.md) · [架构与决策](docs/ARCHITECTURE.md) · [安全复核](docs/architecture/SECURITY_REVIEW.md) · [保留与删除](docs/RETENTION.md) · [API 契约](contracts/workbench-openapi.json)。
