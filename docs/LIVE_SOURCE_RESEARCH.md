# P3 / P4 只读真实来源准备

采集日期：2026-10-27，UTC 时间与原始响应哈希见 `live-source-evidence/fetch_manifest.json`。本任务只整理来源，不实现业务代码、不判断商品通过、不操作真实账号。公开 GET 共 10 个 URL：8 个 HTTP 200、1 个 403、1 个 404；Amazon Seller Central 的 200 仅为页面壳，不能算读取政策正文成功。另用宿主 web 工具阅读公开页面，结果和原始 HTTP 能力分别记录。

## 1. 美国规则候选：儿童产品追踪标识

正式来源：[CPSC Tracking Label FAQ](https://www.cpsc.gov/FAQ/Tracking-Label)。这是监管机构的一手指南，指向 CPSA §14(a)(5)(A)，15 U.S.C. §2063(a)(5)(A)。宿主 web 工具已读取内容；本机直接 GET 返回 403。链接中的法条页面直接 GET 返回 404，未声称读取法条原文。

短摘录：`Are visible and legible`。

可研究的要求：适用儿童产品的产品及包装原则上需有可追溯的永久性标识，并考虑实际可行性。需检查制造商/进口商/自有品牌主体、生产地点与日期、批次等信息。不能把追踪标签要求误写为“必须取得第三方追踪标签认证”；CPSC FAQ 对该点作了区分。

建议 `rule_id=US-CPSC-TRACKING-LABEL`；`jurisdiction=US`；产品范围必须先确认属于儿童产品。未提供年龄定位、标签图样、包装、耐久性及可行性说明时输出 `needs_context`。适用性、例外或材料真实性无法确认时输出 `needs_verification`。指南没有已核实的版本号/生效日期，`effective_date=null`，不得以抓取日代替法规生效日；不能把该一项规则当作完整市场准入检查。

证据 `live-cpsc-tracking-guidance` 保存在 `evidence.jsonl`。哈希对象是 **宿主 web 工具返回文本** `web_tool_capture.json`，不是原始 CPSC HTML。原始 HTML 获取受阻已保留，不伪造原始响应哈希。

## 2. Amazon US 平台规则候选

公开可读的一手来源：[Amazon 产品刊登指南](https://sell.amazon.com/blog/amazon-product-listings)，页面发布日期 2026-04-29，`Safety and Compliance` 小节。原始 HTML HTTP 200 已保存。

短摘录：`Select products may need to meet certain requirements or hazmat regulations.`

可据此检查产品安全与合规信息是否齐备；年龄风险、相关资质、是否含电池等信息按产品而异。该页面是 Amazon 官方操作指南，不应冒充类目完整准入条款。平台字段未知为 `needs_context`；平台明确为 `amazon_us` 但缺商品分类、适用属性、对应证据/刊登材料时仍不能 `pass`。

正式政策入口：[Amazon CPSC-regulated products](https://sellercentral.amazon.com/help/hub/reference/external/GKHQEFBM7834V6AV?route=product%2Fcategory)。该入口搜索结果出现政策文本，但本次真实 GET 和 web.open 只有 JS 页面壳，故完整当前条款为 `blocked`，摘要不得进入正式证据支持 `pass`。CPC 入口也只有壳，未登录或启动浏览器补抓。

补充官方公开资料已读取并保存：[卖家政策概览](https://sell.amazon.com/blog/selling-policies)（页面日期 2024-10-16）及[产品合规政策入口](https://globalselling.amazon.com/policy/product-safety)（中文，含美国受限商品链接）。它们可支持“卖家需核查安全和平台规则”的调查方向，不能证明某一商品已满足当前 US 类目要求。为真实演示建议输出 `needs_verification`，并要求人工提供适用的 Seller Central 政策正文/账户通知；不要自动登录、提交或申请审核。

## 3. 两条真实公开企业来源抽查

| 企业来源 | 本次所见、短摘录 | 允许用途与边界 |
|---|---|---|
| [IKEA How we work](https://www.ikea.com/global/en/our-business/how-we-work/) | `One brand, many companies, and many, many people`；HTTP 200，真实原始 HTML 有哈希 | 可证明其官网如何描述品牌结构；不能把 IKEA 品牌直接合并成一个法定买家。具体合同主体、询盘关联、采购授权仍未知。 |
| [UL Solutions About](https://www.ul.com/about) | `Our testing, inspection and certification services`；HTTP 200，真实原始 HTML 有哈希 | 可证明其自述服务范围；不能证明它对本产品有采购意图、已核验某封询盘或为卖家颁发认证。未提取私人联系人。 |

以上是 **tested_live：公开来源读取**，不是完整真实买家背调。`evidence.jsonl` 的 `claim`、`limitations` 已写明边界。未采集真实个人邮箱、个人手机号或登录态信息。

## 4. 动态示例预检查

[Quotes to Scrape /js/](https://quotes.toscrape.com/js/)：HTTP 200，5,808 字节，原始哈希 `a9067d4438044d45a1a895ed6939df4fa4d0487e17b82053dd694ad425466074`。

静态 HTML 解析器得到 0 个 `.quote` DOM；内嵌惰性 JSON 数据有 10 条记录，后续脚本调用 `document.write` 生成 DOM。没有执行页面脚本，也未打开浏览器。此站适合作公开动态渲染 smoke：未来浏览器应看到 10 个 `.quote` 和 author 字段，再记录 URL/时间/数量。不必为读取底层数据强制开启浏览器，因为内嵌 JSON 已能作为数据被安全解析。

状态：公开 GET `tested_live`；离线快照结构检查 `tested_offline`；真实浏览器渲染 `not_started`。本次未安装浏览器、未启动 CDP、未操作登录页面。

## 5. 本地证据与实跑检查

文件均在 `upstream-audit/live-source-evidence/`，不在产品仓库：

- `fetch_sources.py`：5 个初始 URL 的有界、无凭据公开 GET 脚本；后续 5 个 URL 调用同一 `fetch` 函数。每请求 25 秒上限、2 MiB 响应上限，未启用重试。
- `fetch_manifest.json`：10 个真实请求的 URL、UTC、状态、错误、原始字节 SHA-256（仅成功响应有）。
- 每来源 `.html/.txt/.json`：原始 HTTP、纯文本与元信息。`amazon_cpsc_policy.txt` 明确只有 JS 壳。
- `web_tool_capture.json`：CPSC 与 Amazon 官方页面的宿主工具返回文本；它的哈希与 raw HTML 哈希分开。
- `evidence.jsonl`：4 个可审阅候选证据（CPSC、Amazon、IKEA、UL），全部 `is_synthetic=false`；存在局限并不等同于编造数据。
- `dynamic_smoke_preflight.json`：动态站点静态结构与 JSON 条目计数。
- `prepare_evidence.py`、`evidence_validation.json`：实际执行 `python3 upstream-audit/live-source-evidence/prepare_evidence.py`，退出码 0；核对 3 个原始快照哈希、1 个 web 返回哈希、4 个短摘录确实存在，并确认动态站点 10 条惰性 JSON / 0 个静态 quote DOM。

失败保留：CPSC raw GET 403、US Code 指向链接 404、Seller Central 正文不可读。成功的公开来源不会被拿来掩盖这些缺口。未来若搬运证据进 Case，需要按产品 Schema 映射（审计记录额外含 `snapshot_sha256/hash_basis/limitations`，不能不加映射地假定契约已通过）。

## 后续实测更新（P3–P5）

上文第4节的not_started是静态预检时状态。随后在2026-10-27T15:57:04.600Z，宿主CUA临时IAB标签页实际完成动态页面读取，可访问树含10条内容与10个作者标记，已关闭标签页；详见 `docs/evidence/P3/browser-live.json`。这是宿主浏览器tested_live，并非Web Access。

P4核对来源哈希后把4条真实材料映射到 `cases/live-official-research`；P5实际运行draft/report/validate --strict，全部exit0。该样本是工程研究记录，未关联真实客户询盘，未核实采购意图和商品合规。原始HTTP读取成功与新直接Reader（因保留地址DNS被阻止）的结果分别记录，不能相互替代。
