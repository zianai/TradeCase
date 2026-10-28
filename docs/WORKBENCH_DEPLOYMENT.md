# 部署、配置与恢复

## 服务组成

Next.js → FastAPI → PostgreSQL；Redis/ARQ 只发唤醒消息。CaseRunCoordinator 的数据库租约防止两个 Worker 同时进入相同 workflow_run_id。LangGraph 检查点持久化恢复游标，业务表保存案件、任务、证据、产物、审批和 Outbox。共享对象存储保留 SHA256 内容。原 CLI 文件格式是兼容视图，不是第二套调度器。

`ops/compose.yaml` 包含 Postgres、Redis、migration job、API、Worker、Web。默认 Web3300/API8800仅绑定回环；数据库与 Redis 不暴露宿主端口。

```bash
# 设置独立的测试/生产数据库密码；不要提交到 Git。
export TRADECASE_DB_PASSWORD='<set a strong deployment-specific password>'
docker compose -f ops/compose.yaml build
docker compose -f ops/compose.yaml up -d
# 初次以管理员身份生成个人令牌文件，不把令牌输出到日志。
docker compose -f ops/compose.yaml exec api tradecase-workbench provision-user \
  --tenant my-team --name reviewer --role admin --token-file /app/.tradecase/reviewer-token
```

迁移必须在 API/Worker 前成功。业务迁移 Alembic `upgrade head`；Checkpoint 独立 `AsyncPostgresSaver.setup()`，由 `ops/setup_checkpoint.py` 执行。普通 API 请求不会暗中创建生产表。初始迁移 `downgrade base` 会删除业务表，只在一次性数据库验证；生产回滚优先回滚应用镜像或还原到新的数据库，禁止盲目 destructive downgrade。

## 配置边界

| 配置 | 默认 / 作用 |
|---|---|
| TRADECASE_DATABASE_URL | SQLite开发；生产使用 postgresql+psycopg:// |
| TRADECASE_CHECKPOINT_URL | sqlite:///路径；生产使用 postgresql:// |
| TRADECASE_REDIS_URL | redis://localhost:6379/0 |
| TRADECASE_QUEUE_MODE | local开发 / arq多Worker；inline只供测试 |
| TRADECASE_RUNTIME | fake / openai，SDK不是自研推理循环 |
| TRADECASE_LIVE_MODEL_ENABLED | false，双重开关之外仍需要合法 API 凭据和费用上限 |
| TRADECASE_MODEL | 无隐式模型假定，部署时明确选择 |
| TRADECASE_DEMO_ENABLED | false；仅开发显式开启合成数据 |
| TRADECASE_OUTBOUND_ENABLED | false；不能由网页、模型或普通审批打开 |
| TRADECASE_MAIL_CONNECTOR | disabled / fake / smtp |
| TRADECASE_STORAGE_ROOT / WORK_ROOT | 对象与兼容视图目录，生产跨Worker共享 |

公开读取需 `TRADECASE_PUBLIC_FETCH_ENABLED=true` 和 `TRADECASE_RESEARCH_DOMAINS` 精确域名列表；生产模型需显式设置 `TRADECASE_MODEL`、`TRADECASE_USD_PER_TOKEN_UPPER_BOUND`（部署方确认的费用上界）及 `TRADECASE_MAX_CASE_COST_USD`。没有费用上界时在线模型失败关闭。

研究领域 allowlist、预算与费用上界见 `src/tradecase/platform/config.py`。只有明确授权的公开抓取允许接入；网站条款/robots/频率责任由来源配置承担。既有 ContentReader 会再次校验 SSRF、DNS 与重定向。未启用来源保持不可用，不能把工具存在等同于获准读取。

SMTP 仅在明确配置 `TRADECASE_SMTP_HOST/PORT/USER/PASSWORD/MAIL_FROM`、启用外发、精确版本审批和风险门禁全部满足后使用。凭据从部署环境/密钥管理系统提供；日志不写入密钥或邮件正文。不要把消费者 CLI 登录当作 API 使用权。OpenAI tracing 在适配器内禁用；应用不主动上传询盘正文到外部追踪服务。

本地对象存储与 `S3Storage` 共享协议；设置 `TRADECASE_STORAGE_BACKEND=s3`、`TRADECASE_S3_BUCKET`、可选 `TRADECASE_S3_ENDPOINT_URL` 与 `TRADECASE_S3_ENCRYPTION` 后，部署工厂使用 SDK 默认凭据链/实例身份创建客户端。S3 模拟测试检查哈希和加密参数，尚未做真实云账户验收。数据库/卷加密、TLS、备份密钥和生命周期策略属于部署责任；不能由本机测试推断已经生效。

## 备份、恢复与回滚

1. 将 API/Worker 进入维护状态，停止新的写入；保持数据库可供备份。
2. 使用 `ops/backup.sh` 获取 PostgreSQL dump 和对象目录；保存版本号、镜像 digest 与清单。对象引用须与数据库在同一维护窗口采集。
3. 在新 Compose project/新卷中使用 `ops/restore.sh` 恢复，先不暴露生产入口。
4. 运行 `ops/verify_object_references.py` 校验引用、SHA256 和可读取性；运行 API健康检查及人工中断恢复演练。
5. 确认之后切换入口；旧环境只读保留供回滚。真实外发必须保持关闭直到核对未完成 Outbox。

`DISPATCHING` 的进程崩溃可能已产生外部效果，恢复时不能重发。管理员根据提供商记录核对，并保留 receipt。凭据轮换、撤销与多租户审计在切换前检查。

## 验证与限制

实际执行记录在 `docs/evidence/full-delivery/`。本机已测试 PostgreSQL17.6、Redis7.4.6、真实 ARQ 去重、pg_dump/restore、恢复后的 PostgreSQL checkpoint 续跑，以及容器 API 健康检查。浏览器使用真实本地数据库和明确合成来源。没有调用付费模型、真实发信或 CRM 写入。

CI 配置覆盖 Python3.11/3.12、离线测试、Docker服务集成、前端构建与浏览器流程；当前交付报告只声称本机实际执行的检查，远端 GitHub Actions 需推送后才能验证，未将未运行的 CI 记为绿色。

版本迁移前应备份真实数据并在恢复环境演练。初始产品尚无真实租户负载和业务转化率证据；本机合成性能基线只说明该测试环境的耗时。
