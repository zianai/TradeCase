# TradeCase 工作台使用说明

完整规格见 `tradecase-full-implementation-plan.md`；实际验收证据与环境限制见 `FULL_DELIVERY_REPORT.md`。原有 `tradecase` CLI、七组合成演示、三个 Skills 继续保留。工作台 API 和 `tradecase-workbench` CLI 共用 CaseService。

## 本地运行

需要 Python 3.11+、Node 24+。在仓库根目录：

```bash
uv sync --frozen --extra platform --extra dev
mkdir -p .tradecase
uv run tradecase-workbench init-db
uv run tradecase-workbench provision-user --tenant my-team --name reviewer --role admin --token-file .tradecase/reviewer-token
TRADECASE_DEMO_ENABLED=true TRADECASE_PORT=8800 uv run python -m tradecase.platform.server
```

另开终端：

```bash
cd frontend
npm ci
TRADECASE_API_URL=http://127.0.0.1:8800 npm run dev -- --port 3300
```

打开 http://127.0.0.1:3300。连接工作区时填入本机令牌文件里的值。令牌只保存在当前浏览器标签页的 sessionStorage；退出会清除本地连接状态。不要把令牌粘贴进聊天、报告或截图。生产部署请使用 HTTPS、可信反向代理和单独分发的个人令牌。

默认本地 SQLite + 持久 SQLite Checkpoint + 进程内唤醒用于开发；正式多 Worker 使用 PostgreSQL/Redis/ARQ，见部署说明。

## 完整业务路径

1. 工作台导入询盘：粘贴文本、手工字段或 `.eml` / `.txt` 文件。原始邮件字节与 SHA256 保留；附件仅解析元信息，不执行或解压。需要附件内容时，在受控扫描/转换服务中另行处理，当前系统不声称已做杀毒。
2. 也可显式选择「合成演示」。合成来源、规则和报告均标注 synthetic，绝不能用作真实买家或法规证明。演示选项在生产默认关闭。
3. 发起调查。可并行的三类研究对应独立 Task/Attempt/AgentRun；刷新不会丢失记录。未配置来源或模型时产生 PARTIAL/UNKNOWN 以及人工待办。
4. 在详情页分别查看事实、推断、未知、冲突、两类规则风险和逐条来源。来源快照以纯文本打开，展示引用及采集时间。日志仅包含脱敏事件。
5. 真实调查需要人工在「证据审核」中选择企业候选、已有来源与引用关系，并确认来源使用权限、角色及规则时效。手工导入的公开网页快照标明人工提供，不冒充在线抓取；高级审核表单保存不可变输入版本后，重新运行原有评分和规则引擎。缺项或冲突会被拒绝或保留 UNKNOWN。
6. 草稿审核允许批准、拒绝、要求修改或补充证据。批准精确绑定 Case 版本、草稿哈希与审批范围。旧版本不可覆盖新材料。人工编辑后产生新版本，原审批失效。
7. 批准草稿后创建人工跟进；可调整负责人、到期时间、完成或推迟。长期提醒由 DB/调度器唤醒，不保持 Agent 睡眠。
8. 导出 JSON、Markdown、PDF。JSON 含结构化证据与版本；PDF 是可阅读导出，不代替结构化来源校验。

## 邮件与外部动作

默认 `TRADECASE_OUTBOUND_ENABLED=false`、连接器 `disabled`。草稿审核只批准该草稿供人工使用，不是发送授权。当前版本草稿审核通过后，发送必须另行选择精确收件人和版本，申请 `mail_send` 范围审批，再显式执行发送动作。权限、哈希、Case版本、风险和对象完整性在排队及发送前重查。

`fake` 连接器产生 `SANDBOX_ACCEPTED`，回执明确 `delivered=false`。SMTP 适配器默认不启用，未经真实账号与环境验收不能声称可投产。系统在 `DISPATCHING` 或 `DELIVERY_UNCERTAIN` 时冻结相关修改；超时后由管理员依据提供商记录核对。新的幂等键也不能重复发送同一逻辑动作。未知结果从不自动重发。

尚未交给连接器的 `PENDING` 动作可由审核员通过 `POST /api/outbound-actions/{id}/cancel` 撤销，提交当前 `case_version` 和 `reason`；重复撤销返回原记录。关闭 Case 也会原子取消未发送队列项。发送中或结果未知的动作不能用取消代替回执核对。

CRM 提供可替换协议及模拟边界；当前没有配置和验证任何商业 CRM 在线写入。邮件账户同步、付费注册库、动态浏览器均需要额外权限/许可，目前显示未连接。

## 来源、知识与角色

内部知识保存不可变内容哈希、版本、授权租户和有效期。它属于用户提供的背景材料；检索结果必须转为 Case 的具体引用才能成为证据，不能自动证明产品认证或现行法律。新版本不覆盖历史，过期版本不进入当前检索。

角色：viewer 只读；operator 导入/运行/编辑/跟进；reviewer 具备审批；admin 增加监控、身份配置及不确定回执核对。每个查询（包括 SSE、快照、导出）按租户过滤。令牌哈希存数据库；撤销用户后新请求及 SSE 续读停止。

同域名案件只聚合为「可能相关」，不自动合并企业。同名、不同国家/不同域名以及来源冲突保持独立。标题、优先级与标签可编辑；为保持审批边界，Case 版本变更后需要重新审核。

## 开发者入口

- 兼容 CLI：`tradecase doctor`、`tradecase demo --fixture fixtures/case_strong --out cases/demo`、`tradecase validate --case cases/demo --strict`。
- 工作台 CLI：`tradecase-workbench create --file inquiry.eml --token-file ...`、`list`、`run CASE_ID`、`demo`。
- REST/OpenAPI：`/docs`、`/openapi.json`；交付快照 `contracts/workbench-openapi.json`。
- 创建、审批、跟进与外部动作使用 `Idempotency-Key`。复用键但更换内容将拒绝。
- SSE `/api/cases/{id}/events` 使用事件序号作为 `Last-Event-ID`；JSON 补拉可用 `?format=json&after=N`。
- 测试 `make check`；服务验证 `python ops/verify_infrastructure.py`；浏览器测试在 `frontend` 执行 `npm run test:e2e`。
