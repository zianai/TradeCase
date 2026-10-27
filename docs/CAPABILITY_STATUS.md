# 能力与验证状态（2026-10-27）

`implemented`表示代码存在，`tested_offline`表示真实执行但输入是合成/离线，`tested_live`表示相应真实环境动作已发生；`blocked`表示明确缺口，不表示自动化测试通过。状态只覆盖表中动作范围。

| 能力 | 状态 | 可核对证据与边界 |
|---|---|---|
| 原上游复现 | tested_offline | P0原make可通过，但严格Ruff77/mypy14问题，README付费搜索缺key；失败未隐藏 |
| Case解析/Schema/状态/引用/hash/恢复 | implemented + tested_offline | P1/P3与最终回归；eml/txt/JSON，POSIX单写；不解析执行附件 |
| B2B纯函数与AI URL分类移植 | implemented + tested_offline | 真实导入上游函数，精确SHA与License映射；非自造同名空wrapper |
| 买家消歧/确定性评分 | implemented + tested_offline | 同名、推断邮箱、未知值、篡改重算；任意真实语义的正确性仍需审阅 |
| 静态HTTP读取 | implemented + tested_offline；在线blocked | DNS保留地址导致本环境连接前拒绝；无安全降级绕过 |
| 宿主搜索规范化 / Jina响应导入 | implemented + tested_offline | 只处理已读取产物；不自带搜索账户、Jina实时调用或可信认证 |
| 宿主动态浏览器 | tested_live | Quotes JS站10条内容、无登录新tab、已关闭；非Web Access |
| 两条企业公开来源 | tested_live（读取） | IKEA/UL实际公开GET与哈希；不是客户真实性/采购意图核验 |
| 真实主管机关/平台来源研究 | tested_live（有限读取） | CPSC宿主文本、Amazon公开指南；CPSC raw403、Seller Central JS壳、完整适用条款缺口 |
| country + platform引擎/反馈 | implemented + tested_offline | 有来源/有效期/适用性门槛，结构化severity和文本整改；合成pass不认证真实商品 |
| 英文草稿/审核/人工任务/报告 | implemented + tested_offline | 真实CLI生成、精确hash及重算；固定保守模板，不承诺未提供商业条款 |
| 七组完整Case | tested_offline | 实际CLI子进程，2完成/5需复核，严格引用一致；全程0发送 |
| 项目内双宿主Skills | implemented + tested_offline | 安装记录、相同文本hash；无用户全局写入，见HOST_VALIDATION |
| Codex宿主运行 | 见HOST_VALIDATION | 当前会话显式读取安装Skill并调用工具；自动发现与新会话不是同一测试 |
| Claude Code实际Agent运行 | 见HOST_VALIDATION | 可执行文件/登录检查不等于Agent业务运行；额外调用的计费授权单独记录 |
| 独立wheel | tested_offline | 干净临时venv从wheel安装，repo外cwd运行demo/strict；bundled许可检查 |
| Crawl4AI | blocked | 未装，完整依赖许可证/运行清查未完成，未声称实际接入 |
| Web Access | blocked | 锁定仓库缺完整LICENSE，未安装/启动Proxy，未改用户配置 |
| 真实客户端到端质量、人工准确率 | not_started | 没有真实询盘授权样本，合成测试不能替代质量研究 |
| Windows / 远程CI | not_started | 本机macOS检查已实跑；Actions尚未触发，Windows文件锁未实现 |
| 邮件发送、外部写操作 | disabled | 无send命令，遗留SMTP函数/CLI硬拒绝；不是待自动启用功能 |

## 成本与质量口径

七组离线业务运行网络/模型/邮箱调用均0、外部工具费用0；各例耗时、有效证据数、证据覆盖和未解决风险见P5 demo-matrix。覆盖是固定评分信号覆盖，不是“事实准确率”。人工错误率未测量，为null。当前开发会话本身的订阅/模型费用工具不可见；不据此宣称开发总成本0。

真实来源获取的10个URL得到8次HTTP200、1次403、1次404；200里有页面壳，不能报告成8个有效政策来源。保留4条有边界的证据。动态浏览器单独记录一个新tab访问，不混入静态Reader指标。

## 优先补齐项

先用经授权的真实询盘与实际商品资料做人工复核，记录错误主体关联和来源覆盖；在正常公网DNS环境复测Reader；取得当前适用的正式监管/平台材料，再补规则。仅当确定需要时完成Crawl4AI依赖许可清查或取得Web Access完整许可。生产化之前另评估数据保留、并发恢复、真实文档解析与跨平台支持；不提前开发V2服务。

## P7追加（2026-10-27）

Web Access锁定上游在隔离临时Chrome与本机代理的公开动态站测试为`tested_live`（10 quote/author，进程清理成功）；它**仍未集成/分发**，完整LICENSE与代理安全审计未解决。Claude受限认证原因已用只读状态命令定位，本次用户选择不做额外模型调用，真实Agent运行仍blocked。Reader在当前DNS映射下仍blocked；5组真实来源+合成业务问题Case的结果见 `docs/P7_BUSINESS_EVALUATION.md`，不等于真实客户询盘验收。

P7又实际处理5条UNGM真实公开采购公告，均已过期且来自UNICEF；Case均needs_review，未发送或投标。过期识别目前依赖人工约束，非自动门禁，是真实业务应用的重要缺口。详见业务评测。
