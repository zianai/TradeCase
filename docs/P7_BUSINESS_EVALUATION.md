# P7 公开来源业务场景评测

## 样本边界与方法

这不是五份真实客户询盘，也不是对五家真实企业的尽职调查。我们构造五个**合成的业务问题/商品属性**，使用当次实际取得的真实公开资料作为来源，明确将Case输入标记 `is_synthetic=true`、来源标记 `is_synthetic=false`。未虚构买家采购意图、个人邮箱、商品资质或合规通过结果。五个Case均经真实CaseStore、上游买家研究函数、评分、规则引擎、草稿、报告和严格校验。业务事实由当前Codex会话查阅资料并人工对应，尚无独立行业人员验证。

来源快照：`docs/evidence/P7/host-web-sources.json`（web.open提取文本及来源URL，不是原始HTML）、`amazon-safety-source.json`（Amazon目标段落提取文本）、`web-access-independent.json`（隔离Chrome中上游Web Access真实返回的DOM计数）。对应全部Case的索引snapshot与SHA在本机`cases/p7-verified/<case>/snapshots/`及manifest。P6原始HTTP材料另在工作区 `../upstream-audit/live-source-evidence/`；P7未声称保存了本次各站原始HTML。

五组处理时间只计已取得来源后的本地Case生成，不包含共享联网研究；公共来源同一次web采集耗时3.123秒，动态浏览器单独耗时16.604秒。每例新增模型调用0、案例处理本身工具费用0；共享Codex会话的模型token及费用不可见，均为unknown，不能推算为0。每例两类检查、evidence ID、状态和细项有完整机器记录 `docs/evidence/P7/scenario-results.json`；5/5 strict校验通过，均needs_review。

| 场景 | 真实来源和可核对结论 | 运行结果、失败/未解原因 | 本地处理耗时 |
|---|---|---|---|
| IKEA主体消歧 | [IKEA加盟体系](https://www.ikea.com/global/en/our-business/how-we-work/the-ikea-franchise-system/) `p7-ikea`：Inter IKEA Systems B.V.是加盟体系的特许方；零售运营可能由不同加盟主体承担。 | 2候选、未选择主体，needs_review；缺乏具体询盘和签约主体证明，不能把品牌等同单一买家。 | 0.093秒 |
| UL采购角色证据不足 | [UL Solutions官网](https://www.ul.com/about) `p7-ul` 描述零售和消费品服务。 | 官网服务介绍不证明它有采购意图或询盘关联；1候选但未确认，score=null，needs_review。 | 0.112秒 |
| 动态网页 | [公开动态测试站](https://quotes.toscrape.com/js/) `p7-dynamic`：独立Web Access+隔离Chrome观察到10条quote、10个author。 | 渲染成功，但此站不是买家/订单证据；没有候选、needs_review。此场景验证浏览器能力，不是企业背调质量样本。 | 0.084秒；浏览器16.604秒共享实测 |
| 儿童产品标签冲突 | [CPSC官方追踪标签FAQ](https://www.cpsc.gov/FAQ/Tracking-Label) `live-cpsc-tracking-guidance`：儿童产品及包装的永久性标记要求需考虑可行性。假设产品缺标签是构造的测试输入。 | country=needs_verification，platform=needs_context；已知属性与规则预期存在潜在冲突，批注明示该冲突；规则当前性、起止时间未确认，不能直接断言已违法或pass。 | 0.084秒 |
| Amazon资料不足 | [Amazon官方刊登指南](https://sell.amazon.com/blog/amazon-product-listings) `live-amazon-listing-safety`：安全信息依商品而异。 | platform=needs_context，缺产品类别与安全审查证明；公开指南不能替代当前Seller Central完整政策正文。 | 0.084秒 |

`scenario-results.json`对每例单独记录生成秒数、调用/费用口径、完整检查及来源ID。各份报告分别为`docs/evidence/P7/<场景id>-report.md`。报告中“SYNTHETIC / OFFLINE”指构造问题与本地生成过程；同报告的Evidence列明确显示真实来源`is_synthetic=false`。

## 可复现

```bash
uv run python tools/run_p7_public_scenarios.py --out-root cases/p7-repeat
uv run tradecase validate --case cases/p7-repeat/children-label-conflict --strict
```

使用已保存的当次来源快照，输出根目录须不存在；该命令**不会重新联网**。当前规则源码变化后，旧版本P7临时Case需重新生成；最终目录为`cases/p7-verified/`。如要验证全新页面内容，应另记抓取时间及原始响应，不能把缓存截图当作新抓取。

本样本说明安全退化与来源对应可工作，不足以衡量真实买家背调准确率、实际企业关系匹配率、邮件质量或商业转化。至少需在明确授权后引入真实询盘和实际商品资料，并由行业人员独立复核。

## 五条真实公开采购公告的额外实跑

以下是UNGM平台公开发布的**真实历史采购公告**，不是用户自己的客户询盘；五条均由UNICEF发出，跨不同市场但集中于一个买方和家具类别，样本并不覆盖不同类型的真实买家。公告截止日期截至采集均已过去；不得作为当前可投标机会。只读取并保存了页面19–45行，刻意排除个人联系人，完整原文与附件仍以来源页面为准。采集时长为宿主web.open调用耗时（并发执行），Case耗时不含模型思考和网页检索。

| 公告、证据ID | 原始来源 / 业务内容 | 截止日期（已过） | 来源读取 / Case处理 | 结果和缺口 |
|---|---|---|---|---|
| `unicef-318181` / `p7-public-318181` | [UNICEF乌克兰四类供应商意向征集](https://www.ungm.org/Public/Notice/318181)：包括办公家具与ICT等类别 | 2026-10-20 | 3.270秒 / 0.157秒 | needs_review；公开市场调查不等于直接询盘，附件、卖家资质和乌克兰规则未核验 |
| `unicef-301686` / `p7-public-301686` | [UNICEF约旦办公室家具采购](https://www.ungm.org/Public/Notice/301686) | 2026-06-11 | 3.338秒 / 0.103秒 | needs_review；完整技术/商务附件与约旦适用规则未知 |
| `unicef-299179` / `p7-public-299179` | [UNICEF马来西亚办公室家具](https://www.ungm.org/Public/Notice/299179)：公告标题限定马来西亚本地公司 | 2026-05-21 | 4.626秒 / 0.082秒 | needs_review；无法证明卖家符合本地资格、安装或提交条件 |
| `unicef-290489` / `p7-public-290489` | [UNICEF厄瓜多尔Riobamba家具询价](https://www.ungm.org/Public/Notice/290489)：公告描述邻近供应商与当地交付 | 2026-02-12 | 3.339秒 / 0.094秒 | needs_review；物流可达性、产品规格及当地规则未核验 |
| `unicef-310066` / `p7-public-310066` | [UNICEF加沙应急家具采购](https://www.ungm.org/Public/Notice/310066) | 2026-08-30 | 3.074秒 / 0.093秒 | needs_review；交付能力和完整附件未知。页面摘要与正文截止时刻存在差异，但两者均已过期 |

机器记录在 `docs/evidence/P7/public-procurement-results.json`，包括每例原URL、采集时间、证据ID、用时、规则结果和待核实原因；`public-procurement-sources.json`是去除联系人后的页面摘录，不是原始HTML。五例严格校验5/5通过，全部`needs_review`、score=null，目标市场没有匹配规则时均显式产生country `needs_verification`。运行本地Case生成不触发网络或模型调用、成本0；共享Codex会话token和成本仍unknown。

**发现的业务缺口：** 截止日期是评审者依据公告摘录显式加入人工约束，不是当前系统自动抽取或过期门禁；固定回复模板也不会自动针对招标条款或截止时间形成适配回复。现有草稿不可直接用作投标、承诺或发送。需建立有证据绑定的截止时间处理、地域资格与采购附件核验，并用实际卖家资料评估，才能认为具备业务应用质量。

复现（依赖已提交的来源摘录；输出目录须不存在）：

```bash
uv run python tools/run_p7_public_procurements.py --out-root cases/p7-public-repeat
uv run tradecase validate --case cases/p7-public-repeat/unicef-318181 --strict
```

## 后续V1改进

P7报告保留当时事实。后续已为显式标记的采购公告增加证据绑定、数字GMT偏移解析、过期/冲突门禁和招标草稿；五条公告的最新回归另见 `docs/PHASE_REPORTS/V1-PROCUREMENT.md`。`tools/run_p7_public_procurements.py` 现在生成新版结果到 `docs/evidence/V1-deadline/`，不会覆盖本P7历史证据。
