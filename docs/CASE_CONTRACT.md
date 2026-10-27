# Case v1 数据与操作约定

权威字段定义为 `src/tradecase/models/__init__.py`；`schema_version` 当前只能是 `1.0`，未知字段和错误类型拒绝。不存在自动迁移旧版本的行为；未来迁移需独立显式工具、输入备份和重新验收。

## 创建输入

```json
{
  "schema_version": "1.0",
  "company_name": "Your company name",
  "website": null,
  "product_summary": "Describe the actual product",
  "product_attributes": {},
  "allowed_claims": [],
  "forbidden_claims": [],
  "source_refs": [],
  "is_synthetic": false
}
```

这是 `seller.json` 的模板，占位文字须替换。属性值支持字符串、布尔值和null；未知不得填true。allowed_claims是卖家声明，草稿不会自动把它提升为认证。source_refs是人工来源线索，不会触发读取或执行。

询盘可以是eml/txt，或带 `buyer_message` 的JSON，可含 `buyer_email`、`buyer_company_hint`、`buyer_website_hint`、`product_summary`、`origin_country`、`target_country`、`sales_channel`、`platform`、`user_constraints`、`is_synthetic`。输出Case的case_id来自输出目录名。`received_at` 默认是导入时刻，并保留解析警告；不是擅自认定的邮件发送时间。原文完整bytes/Base64/SHA256保留，eml附件只留元信息。

## 证据与派生产物

Evidence必须有稳定 `evidence_id`、claim、source_type、captured_at（显式UTC）、retrieved_by、assertion_status、confidence_label、is_synthetic；有URL时只接受无凭据http/https。已支持/否定的事实须有来源和excerpt/locator；真实支持性证据拒绝保留示例域名。页面正文始终是不可信材料。索引/哈希能验证完整性，不能替代人对事实的审阅。

Profile 的 `candidate_ids`、selected_candidate_id、claim_evidence_map与Candidate/Evidence交叉引用。联系人有明确来源类别、verified=false、send_allowed=false；邮箱语法不代表收件人核验。固定priority-v1使用5个证据信号，权重20/25/25/20/10，已知信号覆盖低于60%则score=null；歧义和关键身份缺口保留needs_review。评分重算由代码执行。

`rules_snapshot.json` 记录实际使用的版本化规则，`compliance.json`绑定snapshot哈希并重算结果。country/platform分别评估范围、必需上下文、官方来源、有效期和属性；null/过期/未确认不能通过。`draft_review.json`绑定精确草稿、原询盘和卖家资料哈希，并重算上游词法检查。任何预检都不是人工发送批准。

## 状态与恢复

created → running → needs_input / needs_review / completed / failed / cancelled。
failed可显式回到running；completed/cancelled修改前也必须显式回到running。所有状态转换写events；completed必须严格产物齐全、无blockers/error、无未解决买家/合规门槛。已完成的是研究交付物，人工商业确认仍可能保留。

```bash
uv run tradecase status --case cases/inquiry-001
uv run tradecase recover --case cases/inquiry-001
uv run tradecase transition --case cases/inquiry-001 --state running --stage review_update
```

只在确认恢复原因后运行reopen；`recover`只处理本地事务，不会自动重试付费或外部操作。CaseStore使用POSIX单写锁、每文件atomic replace、journal和manifest最后提交；系统中断可能留下journal，恢复前不能写新版本。旧/坏journal拒绝，不静默回滚。`.history/<revision>/`留存修改前内容。此机制不是对抗拥有shell写权限的攻击者的隔离边界。

用 `put --artifact <known-name> --file <local-file>` 导入由宿主审阅的JSON/JSONL；只接受列举的产物名。外部输入不授予shell权限。快照经 `CaseStore.save_snapshot` 写入受限 `snapshots/<name>.txt|json` 并登记哈希，不能手写未索引快照冒充通过。

## 采购公告截止时间（V1增量）

采购公告必须显式设置 `case_type=procurement`；`init` 支持 `--case-type procurement` 和 `--deadline-evidence-id ID`，JSON输入也可设置。普通询盘保持默认`inquiry`；系统不会可靠地从任意正文自动分类采购公告；提供截止证据ID时，即使误用inquiry类型仍会套用采购门禁。原P7五例含特定 `Public procurement notice excerpt;` 解析警告，会被保守识别为旧公告并默认待核验；其不可变input不能补写证据ID，需在新Case目录重新生成。

ID须对应已支持的官方来源Evidence：`source_url`有效、`excerpt`逐字包含截止时间、`local_snapshot_ref`指向Case已索引JSON快照，该快照必须包含相同`source_url`和`selected_lines`。解析器当前只接受 `Deadline on: DD-Mon-YYYY HH:MM (GMT ±H.MM)` 的明确数字偏移，使用当前UTC重算；未提供、未确认、未知时区、多个或冲突截止时间一律needs_review。过期和未确认不能将Case转为completed，且草稿变为无收件人的内部核查说明。

草稿审核的`procurement_basis_sha256`绑定证据记录及快照的精确字节；变更或截止时间到达后必须重新生成draft和report。已索引快照与引用验证保证来源链完整，不证明真实网站身份、公告当前性或不存在后续延期；即使截止时间仍开放，也需要人核对补遗、时区、资格、附件和商业条款。没有任何提交或发送入口。
