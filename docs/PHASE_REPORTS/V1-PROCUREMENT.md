# V1采购公告：截止时间、门禁和草稿

基线：`40f3362`，在同一`codex/tradecase-v1`分支上增量实现。未开发V2、未调用付费模型、未发送邮件或提交投标。

## 实现与边界

新增`case_type=procurement`与`deadline_evidence_id`。采购公告须显式分类：既有普通询盘保持原行为，系统不声称能自动识别任意公告；一旦提供截止证据ID，即使case_type误留为inquiry也会套用门禁。原P7五例因包含已知的采购公告解析警告，旧Case未设置新字段时也会强制待核验；重新生成新Case才能绑定截止证据，不覆盖旧input。Evidence须为已支持的官方类型，含实际来源URL、逐字截止时间摘录和已索引的JSON快照；快照的source_url和selected_lines必须与Evidence匹配。草稿审核的`procurement_basis_sha256`绑定Evidence与快照字节，来源变化即使更新manifest hash也会使审核失效。

当前解析 `Deadline on: DD-Mon-YYYY HH:MM (GMT ±H.MM)` 并按UTC比较。无证据、未索引、来源不符、时区未知、多个或冲突截止声明均为`needs_review`；到达截止瞬间即`expired`。过期或未验证时，Case进入needs_review，completion transition和直接篡改后的validator均拒绝completed。若一份新证据将截止时间改为未来，只清除采购截止时间自身的阻碍，不自动完成Case；仍须审查其它阻碍。

到期或未确认时，草稿为**无收件人的内部核查说明**，明确不投标、不发送；开放公告草稿转为询问招标文件、截止、补遗、资格和交付要求，不冒充买家主动询盘、不承诺价格/交期/资质。所有草稿均需人工确认，send_allowed=false。报告展示状态、UTC截止时间、证据ID和未解决原因。截止时间随真实当前时间变化后，已有报告/草稿审核将过期，需重新生成。

来源内容必须由人或宿主判断其真实性；哈希只绑定捕获材料。快照可能过时或漏掉后续补遗；不支持日期仅有日、命名时区/DST或任意自然语言格式时，保持待复核，不猜测。即使状态open也不代表卖家有资格或获得发送/投标许可。只保存了原公开公告摘录，未取得完整附件、真实卖家资料或当前公告的后续补遗。

## 五条公开公告实跑

运行 `python tools/run_p7_public_procurements.py --out-root cases/deadline-final`，使用P7保存的真实公开来源摘录，不再使用手工日期表驱动状态。生成Case和strict校验5/5通过；对五例逐一实际尝试`transition --state completed`，5/5均被截止时间门禁拒绝；草稿均无收件人并提示不提交。每例状态、证据绑定哈希、Case路径和耗时见 `docs/evidence/V1-deadline/public-procurement-results.json`，命令输出与退出码见 `cli-gates.json`。

| 公告 | 证据计算的截止时间UTC | 状态 |
|---|---|---|
| UNICEF 318181 | 2026-10-20 15:30 | expired |
| UNICEF 301686 | 2026-06-11 08:59 | expired |
| UNICEF 299179 | 2026-05-21 09:00 | expired |
| UNICEF 290489 | 2026-02-12 21:00 | expired |
| UNICEF 310066 | 未确定 | needs_review：页面同列不同截止时刻，未假定孰为准 |

五条均为已过期的公开历史采购案例，不是用户的私有客户询盘；加沙公告虽两个时间均已过去，仍保留冲突待复核而非捏造唯一截止时间。

## 测试与执行

红灯：`tests/unit/test_procurement_deadline.py`初始因缺模块失败，`docs/evidence/V1-deadline/red.log`。定向回归包含UTC转换、截止瞬间、未来、未知时区、冲突、无证据、索引/来源篡改、审核hash失效、旧completed状态伪造、过期阻碍及更新后清除阻碍。最终 `make check` exit 0、**329项测试通过**，见 `final-regression.log`；原P0–P7测试未跳过。P6保存的8个Case再次strict验证均通过；原P7的5个未绑定截止证据的旧公告Case均被识别并拒绝使用旧草稿审核，input哈希未变化，需生成新Case，见 `historical-cases.json`。三个项目Skill已同步，二次安装返回unchanged；项目记忆检查见`memory-check.log`。

复现请使用未存在的输出目录：

```bash
uv run python tools/run_p7_public_procurements.py --out-root cases/deadline-repeat
uv run tradecase validate --case cases/deadline-repeat/unicef-318181 --strict
```

真实业务上线仍需更多不同买家、当前公告、附件与补遗、有权处理的卖家资料和人工审核；本次不改变P7对V2的No-Go结论。
