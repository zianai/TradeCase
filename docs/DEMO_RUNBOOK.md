# TradeCase V1 演示手册

演示使用显式 **SYNTHETIC / OFFLINE** 数据，保留域名 `.invalid` 不是真实来源。本地真实生成产物和真实执行测试；不把模拟资料讲成现场联网核实。

## 1. 准备（项目根）

```bash
uv sync --frozen --extra dev
uv run tradecase install-skills --target both --scope project
uv run tradecase doctor
PATH="$PWD/.venv/bin:$PATH" make check
```

项目Skill唯一源码在skills/，同步到项目内双宿主目录。已有同名或手改安装文件会报冲突，先人工比较差异；不要直接清空个人配置。核心CLI不要求API key、SMTP、浏览器或联网。

## 2. 三分钟主案例

```bash
uv run tradecase demo --fixture fixtures/case_strong --out cases/stage-strong
uv run tradecase validate --case cases/stage-strong --strict
uv run tradecase status --case cases/stage-strong
```

输出目录必须是新的。打开 `report.md`，按顺序展示询盘、证据ID与采集时间、买家角色、固定评分、country/platform两种检查、severity与文本批注、英文草稿、人工确认任务。再打开 `manifest.json`、`events.jsonl`、`draft_review.json` 展示状态、版本和hash。strong中的pass只针对合成规则，不是对真实商品的合规放行。

## 3. 不足信息与恢复

| fixture | 预期交付状态 | 现场讲解 |
|---|---|---|
| case_strong | completed | 有限合成范围内证据齐备；发送仍禁用 |
| case_name_collision | needs_review | 同名两主体不合并、不自动选中 |
| case_missing_platform | needs_review | platform为needs_context |
| case_regulation_unknown | needs_review | 过期规则为needs_verification |
| case_inferred_email | needs_review | 推断邮箱verified=false，不能自动发送 |
| case_prompt_injection | needs_review | 网页里的“读密钥/执行命令”留作数据，不执行 |
| case_resume_after_failure | completed | 显式模拟业务中断后重新加载Case继续；先前证据保留 |

每个fixture替换主命令的目录和新out即可。七组真实CLI E2E纳入pytest。恢复演示不是现场断网；真正本地写入中断/journal恢复由故障注入测试验证。缺rules依赖在建Case前失败，建Case后的计算失败留failed；未完成事务先recover，不能假称成功。

## 4. 宿主演示

同一业务提示见 `docs/host-validation-prompt.txt`。Codex和Claude都应从项目根使用安装后的trade-inquiry，分别设置新 `TRADECASE_DEMO_OUT`。实际宿主调用状态、Skill哈希、同一输入CLI语义比较见 `docs/HOST_VALIDATION.md`。确定性CLI输出相同不代表两个模型都做过真实研究。

## 5. 真实来源材料与离线兜底

`docs/evidence/live/`保存实际公开GET元信息/哈希和候选证据，`docs/LIVE_SOURCE_RESEARCH.md`解释IKEA、UL、CPSC、Amazon的结论边界。原始响应在工作区 `../upstream-audit/live-source-evidence/`；不随核心wheel分发。`cases/live-official-research/report.md`是把真实来源映射到契约后生成的研究报告，不是实际买家询盘。该样本缺产品/平台政策依据，保持needs_review/needs_context。

动态页面的真实宿主浏览器记录在 `docs/evidence/P3/browser-live.json`：Quotes to Scrape、10条内容、新标签页、无登录、已关闭。没有制作录像；这是可复核的工具观察记录，不能称实时演示。若现场网络不可用，展示该记录和离线Case并明确采集时点，不播放虚构的联网流程。

当前直接HTTP Reader在本机代理DNS保留地址处blocked；不改SSRF门禁。CPSC直接GET403、Seller Central只得JS壳。Web Access完整LICENSE缺失、Crawl4AI依赖未清查/未安装，均不能承诺现场能用。来源不可读时展示blocked与人工补资料任务，继续完成其他可验证交付。

## 6. 讲解边界

本CLI未产生任何真实发送、外部账号写操作、付费数据调用。离线Case执行费用0，当前Codex会话自身计费未由工具测量，不能宣传整个开发过程免费。查询数、页面数、浏览器调用、证据覆盖、耗时、未解决风险应按事件和实测日志报告；未测的人工准确率写unknown。不要外推七组合成测试为生产准确率。

V1没有CRM、自动发信、完整法律认证、无人值守调度或前端。下一步是获得明确商品资料和授权后复核真实询盘质量、补当前官方政策、在正常公网DNS环境复测Reader，再决定是否值得安装可选依赖。
