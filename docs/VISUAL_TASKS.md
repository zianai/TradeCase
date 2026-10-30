# Visual Task 升级与使用

## 核查基线

2026-10-30 在独立临时目录从 Git 导出并执行历史测试：`e446f94` 315 passed；`codex/tradecase-v1`（3a4f8b4）347 passed。二者均为当前提交 11147c1 的祖先。当前工作区升级前为 497 passed / 4 skipped；跳过的是需指定 PostgreSQL/Redis 环境的测试，不计为通过。

实际架构为 Python 业务内核 + FastAPI / SQLAlchemy / Alembic + LangGraph + ARQ + Next.js。旧 CLI 的文件 CaseStore 继续支持离线流程，平台 PostgreSQL 为工作台业务权威。已有两个业务迁移、数据库任务租约、Agent Run 预算、版本化草稿及审批和默认关闭的 Outbox。不是从 315 项测试版本重新搭建。

Visual Domain 增量增加产品事实快照、授权源素材、计划、独立运行记录、图片审核及提案。Creative Engine 仓库位于同级目录；仅通过 HTTP 协议访问，不导入其代码或数据库。线上模型效果、生产部署和客户转化率不由 Mock 验收证明。

## 默认边界

视觉能力默认关闭；普通询盘不要求额外操作。启用后仍需显式计划审批与图片审批。用户必须提供产品来源、素材使用权限、允许变更范围和预算；未知信息保持未知，ODM 仅为概念。

生成图片不写入 Evidence。提案与邮件只准备交付物，不自动发送。旧案例及旧报告保留，更新草稿必须重新审核。

接口、配置与操作说明如下。

## 启用与迁移

先停止写入并备份数据库与对象存储，执行 `tradecase-workbench init-db` 或 `alembic upgrade head`；新增迁移 `20261030_0003` 创建 11 个独立业务表，不改旧 Case 字段。不要用 create_schema 替代生产迁移。原数据库、对象存储、工作流检查点继续采用原部署说明。

```sh
TRADECASE_VISUAL_ENABLED=true
TRADECASE_CREATIVE_ENGINE_MODE=mock
TRADECASE_VISUAL_PROVIDER=mock
TRADECASE_VISUAL_MAX_BUDGET_USD=5
TRADECASE_VISUAL_PAID_ENABLED=false
TRADECASE_OUTBOUND_ENABLED=false
```

离线 Mock 是固定测试图片及状态的协议替身，不执行视觉生成或通用 QA；持久状态默认在忽略目录 `.tradecase/creative-mock-fixture.json`，可用 `TRADECASE_CREATIVE_MOCK_STATE` 指定。API 与本地恢复 Worker 共用业务 DB；生产 ARQ 的 `recover_visual` 定期唤醒批准后的任务，Engine 自己执行图像作业。不要运行第二个图像执行器。

真实 HTTP 模式：设 `TRADECASE_CREATIVE_ENGINE_MODE=http`、`TRADECASE_CREATIVE_ENGINE_URL` 与服务端 `TRADECASE_CREATIVE_ENGINE_TOKEN`。固定协议 1.0.0；外网只允许 HTTPS，本地 HTTP 还需显式 `TRADECASE_CREATIVE_ENGINE_ALLOW_LOCAL=true` 且地址为 loopback。必须在部署的 Engine 侧配置认证及访问控制；本次本地测试不证明生产认证配置。Token 不传到浏览器。

保持 paid_enabled=false 即可验证真实服务上的 Mock/确定性合成；真实付费模型调用未在本次验证。供应商、服务地址、协议与预算绑定到计划，修改配置后须重新确认计划。VisualPlan 预算是上限，未知估算显示未知；不能编造供应商报价。

关闭 `TRADECASE_VISUAL_ENABLED` 不影响原 Case 分析。视觉错误会在任务状态中出现，Case 研究和草稿仍可完成。

## 操作

在 Case 的“视觉任务与提案”中先查看建议。无视觉需求的 Case 保持原流程。输入 SKU、尺寸、材料、结构、定制能力和事实来源，并说明是 verified / supplier_claim / unverified / concept。这里只记录审核人提供的事实状态，不声称数据库替用户独立验证了产品。

上传 PNG/JPEG/WebP 真实产品图、Logo 或包装素材，逐项确认来源、授权及外部使用许可，单图不超过 2 MiB。创建计划时可引用同 Case 多个 SKU 的素材；缺资料会显示 needs_input。允许的 Logo 变更名称为 `authorized_logo`。结构/尺寸等事实变更须明确转为概念方案，不能冒充现有 SKU。

计划审批绑定版本、SHA256、预算、数据处理授权和执行配置。批准后异步执行，查看状态或手动同步。图片必须通过 Engine QA 和独立业务审核；校验正确 SKU、Logo、参数与未经核实的制造/认证暗示。已核实的底层产品事实与概念预览图分开显示。

将批准素材加入 Buyer Proposal，可下载带追溯 JSON 的 ZIP。更新跟进草稿会新增草稿/报告版本并使旧审批失效；邮件从未自动发送。Mock 提案带明确标识且外发门控禁止投递。旧产品快照、旧计划或未批准资产不能导出为当前提案。

修订创建新计划且需重新审批；部分失败仅允许恢复不超过失败数量的变体，成功旧素材保留历史，不能自动把旧计划审批并入新计划提案。未知远端提交结果保持 reconciling，按保存的 Batch/Plan 查询，不能按“重试”盲目重复收费。无法确认的结果需运维对账，不提供强制清零按钮。

## API 与 CLI

认证沿用现有 bearer/RBAC；资源按 tenant 和 Case 校验。写入使用 Idempotency-Key；计划/图片决定还要求当前 version 和 hash。

- `GET /api/cases/{id}/visuals`：建议、产品、素材、计划、状态及提案。
- `POST /api/cases/{id}/visuals/{products,assets,tasks,suggestions}`：产品 JSON、授权图片 multipart、计划 JSON、引用原询盘原句的 Agent 语义候选。
- `GET /api/visual-tasks/{id}`；`POST /api/visual-tasks/{id}/{approve-plan,sync,cancel,revisions,reviews,attach}`。
- `GET /api/visual-assets/{id}/content`、`/api/visual-source-assets/{id}/content`：认证读取。
- `GET /api/visual-proposals/{id}/export`：重新校验当前快照与审核后导出 ZIP。

`tradecase visual --token-file <file> --url http://127.0.0.1:8800 --help` 列出命令。`suggest --case <id>`、`status <task-id>` 和 `export <proposal-id> --out <new.zip>` 可直接使用。`create/plan --case <id> --plan <JSON>` 只保存计划；`approve-plan/review/revise/attach/cancel/sync <task-id> --file <JSON>` 使用与 API 相同的版本化请求。`import-products --case <id> --file <JSON或CSV>` 支持轻量目录导入；CSV 数组字段以 `|` 分隔。CLI 不保存 Token、不跟随 HTTP 跳转、不自动重试外部操作。

规则建议自动运行；复杂语义可由已有宿主 Agent 按 `skills/visual-opportunity/SKILL.md` 产生候选，通过 Schema、原句和规则门控导入。这次未执行新的付费语义 Agent，亦未新增 Agent 调度循环。

## 验证与限制

实际测试结果见 `docs/VISUAL_UPGRADE_REPORT.md`。真实服务验证包含本地 Creative Engine HTTP、Mock Provider 及实际确定性合成；不包括付费生成、Oracle 或生产认证验收。业务转化率、真实图片质量仍需真实使用数据。完整本地测试和截图保留在 `.tradecase/visual-validation`、`docs/evidence/visual-upgrade-2026-10-30`；遵循用户要求不提交测试集/测试产物。
