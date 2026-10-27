# AI Hunter P0 审计（2026-10-27）

## 状态与边界

- 状态：`tested_offline`（下列纯函数单元测试）；源码获取是 `tested_live` 的 GitHub 公开只读获取，不代表 AI Hunter 线上业务已验证。
- 上游：https://github.com/xiongQvQ/AI_Find_Customer
- 完整 Git clone：`upstream-audit/AI_Find_Customer/`，`git status --short` 为空。未修改上游源码或测试。
- 锁定 commit：`9b2fde8f719623c627516da2663707a893ee6805`（2026-07-17T20:32:09+08:00；`docs: rewrite customization section with B2Binsights intro`）。`git ls-remote … HEAD` 与本地 HEAD 一致。
- 根 LICENSE：MIT，`Copyright (c) 2026 AI Hunter`。保留完整 LICENSE/版权通知是复制代码的前提。未找到独立 COPYRIGHT/NOTICE；候选文件无覆盖根许可证的独立声明。
- 测试环境是独立的 `upstream-audit/.audit-venv/`，Python 3.11；未安装上游完整 requirements，没有读取全局账号或发件凭据。
- 未启动 FastAPI、前端、LangGraph、ReAct、scheduler；未联网搜索买家、发送邮件、调用收费搜索/模型或读账号数据。

## 代码而非 README 的发现

1. `backend/tools/url_filter.py` 与 `contact_extractor.py` 全部为标准库纯函数，可以直接保留其实现并用 TradeCase 边界层补充校验和 provenance。这比移植整套服务更适合 V1。
2. `company_website_finder.py:56–95` 默认返回搜索结果中第一个非已知平台/内容域名，并把它描述为“official”。这只证明候选排序，不证明企业身份、同名消歧或官网归属。它还在顶层导入 `GoogleSearchTool`，继而依赖 httpx、tenacity、pydantic-settings 和项目配置，不能原样作为无依赖纯函数导入。
3. `email_verifier.py:82` 把 MX 非空直接设为 `is_deliverable=true`；没有 dnspython 时 `_get_mx_records` 用 A/AAAA 解析替代 MX 并返回域名。不能将这种结果提升为“邮箱已核实/可送达”。dnspython 亦未在 requirements 声明。V1 不迁移这段核实语义。
4. `customs_router.py` 有有用的查询构造/字段提取，但已与 Google/Jina 耦合；`_provider_for_url` 用域名子串匹配，`_fetch_raw` 跟随重定向，没有公共 URL/IP 策略。优先使用 B2B Lead Hunter 的 `customs_verify.py`，避免重复拷贝、付费依赖和网络攻击面。
5. `pdf_parser.py` 直接依赖 `pymupdf4llm`；根 MIT 不覆盖这些依赖。`requirements.txt` 只是范围，未锁定依赖快照。
6. `.docx` parser 是可单独迁移的可选后续候选，但不在最小询盘闭环的阻断路径。Excel 路径 `pandas.DataFrame.to_markdown` 需要 `tabulate`，上游 requirements 未显式声明；支持 `.xls` 时还需对应引擎。暂不迁移解析扩展。

## 源码复用矩阵（候选，不表示主项目已经移植）

以下每行的锁定 SHA 都为 `9b2fde8f719623c627516da2663707a893ee6805`，许可证均按该 SHA 根 `LICENSE` 核验；实际目标文件须由主实施在 P2 接入后更新。

| 原文件 / 函数 | 建议目标 | 变更性质 | 依赖 / 许可证核验范围 | 测试结果 | 原因 / 替代方案 |
|---|---|---|---|---|---|
| `backend/tools/url_filter.py`: `classify_url`, `classify_search_results`, `extract_linkedin_company_slug`, `slug_to_company_name` | `src/tradecase/vendor/ai_hunter/url_filter.py` + provider wrapper | adapted（P2 候选） | 标准库 `re`, `urllib.parse`；源代码 MIT | 原测试在 80-test 组合内全部通过；负向问题见下 | 有现成分类字典与 slug；必须限制协议/主机，分类不代表官网认证。替代：仅保留为宿主研究提示，不自动抓取 |
| `backend/tools/contact_extractor.py`: `extract_phone_numbers`, `sanitize_phone_list`, `extract_social_media`, `discover_contact_pages` | `src/tradecase/vendor/ai_hunter/contact_extractor.py` + evidence wrapper | as-is / adapted（P2 候选） | 标准库；源代码 MIT | 原测试在 80-test 组合内全部通过；ftp 候选问题真实复现 | 电话去重/反假阳性及同站 contact 页面发现有增益；每项必须附原文和 URL，电话格式有效不等于可联系；B2B 脚本已有相同功能时优先 wrapper 复用 B2B |
| `backend/tools/email_finder.py`: `extract_emails_from_text` | 无（默认 B2B `extract_contacts.py`） | not-used（推荐） | 标准库；MIT | 负向脚本提取示例实际执行 | 避免重复邮箱抽取实现；这里仅抽取可见邮箱，不可标为 verified |
| `backend/tools/company_website_finder.py` | 将来仅抽离非平台候选筛选 | not-used（当前） | httpx + tenacity + pydantic-settings 等；完整传递许可证未审结 | 原模块导入 exit 1，缺 httpx；未调用网络 | “首条非平台结果=官网”不符合证据标准。宿主搜索 + 已复用 URL classifier + Agent 消歧更合适 |
| `backend/tools/customs_router.py` | 无 | not-used | httpx/tenacity/配置/Jina/Serper；未安装 | 静态审计，未运行网络流程 | 与 B2B `customs_verify` 重复，且含松散域名匹配；不引入收费数据 |
| `backend/tools/docx_parser.py` | 可选后续解析适配器 | not-used | python-docx，传递依赖需单独版本锁定与许可证核验 | 未执行 | `.eml/.txt/JSON` 先满足；无必要不扩大攻击面 |
| `backend/tools/excel_parser.py` | 无 | not-used | pandas/openpyxl，隐含 tabulate/xls engine，未锁定 | 未执行 | 本轮非必选；若接入，应资源限额/格式校验/完整依赖锁定 |
| `backend/tools/pdf_parser.py` | 无 | not-used | PyMuPDF4LLM / PyMuPDF AGPL 或商业双许可；不可凭根 MIT 放行 | 未安装、未执行 | 避免未经核验带入不匹配的商用分发义务 |
| `backend/tools/email_verifier.py` | 无 | not-used | DNS/网络；dnspython 可选但未声明 | 静态审计，未联网 | MX/A 不能证明个人邮箱可达；不搬 `is_deliverable` 结论 |
| `backend/tools/react_runner.py`, `llm_client.py`; agents/graph/API/frontend/scheduler | 无 | not-used | Agent 框架/模型/服务依赖 | 未运行 | 明确超出 V1；由成熟宿主 Runtime 负责循环，无独立发送路径 |

## 依赖许可证与安装决定

- 实际候选 `url_filter.py`、`contact_extractor.py` 无第三方运行时依赖，故不要求把 AI Hunter requirements 搬入 TradeCase。
- 上游 `backend/requirements.txt` 声明 `pymupdf4llm>=0.0.10,<1.0.0`。本次不解析这个范围为某个安装版本，也不声称整条依赖树已合规。
- [Artifex 官方 FAQ](https://pymupdf.readthedocs.io/en/latest/faq/index.html) 说明 PyMuPDF4LLM 与 PyMuPDF/MuPDF 采用 AGPL 或商业许可；[官方许可页](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright) 说明 PyMuPDF/MuPDF 的许可。
- [Artifex 官方 2026-08-10 说明](https://pymupdf.io/blog/open-source-all-the-way-down-pymupdf4llm-goes-fully-agpl) 说明较新 1.28.2 的 Layout 转为 AGPL，此前 Layout 使用 PolyForm Noncommercial/商业条款。该较新版本不在 AI Hunter `<1.0.0` 声明范围内，不能拿当前版本说明代替对上游范围解析出的具体历史版本审计。实际决定：PDF 路径不安装/不复用，避免许可推断。
- 测试只安装 `pytest==8.4.2`；解析结果在 `logs/ai-hunter-test-environment.txt`，未向项目添加运行时依赖。无完整传递依赖许可证通过声明。

## 实际执行与证据

原 README 后端开发命令为 `cd backend; python -m pytest tests/ -q`。完整应用依赖未安装，不把局部结果当全套通过。选择已有确定性工具原测试，不改测试，不模拟整个应用成功。

| 命令 | 退出码 / 结果 | 类型 |
|---|---|---|
| `git clone https://github.com/xiongQvQ/AI_Find_Customer.git upstream-audit/AI_Find_Customer` | 0，完整历史本地存在 | 公开源码只读在线 |
| `git ls-remote https://github.com/xiongQvQ/AI_Find_Customer.git HEAD` | 0，SHA 与本地相同 | 公开源码只读在线 |
| `python3 -m pytest --version` | 1，系统 Python 3.14 无 pytest | 环境失败已记录，不修改全局 |
| `python3.11 -m venv .audit-venv` + `.audit-venv/bin/python -m pip install 'pytest==8.4.2'` | 0，仅本地隔离测试环境 | 依赖安装，不是业务在线验证 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 ../../.audit-venv/bin/python -m pytest tests/test_tools/test_url_filter.py tests/test_tools/test_contact_extractor.py -q -p no:cacheprovider`（backend 目录） | 0，**80 passed, 1 warning**；warning 为未装 pytest-asyncio 时未知 `asyncio_mode` 配置；这些选中测试都是同步纯函数 | `tested_offline` |
| `PYTHONDONTWRITEBYTECODE=1 .audit-venv/bin/python ai_hunter_negative_probe.py`（audit 目录） | 0，6 项安全弱点按现状真实复现；这里 0 仅表示复现断言成功，**不是安全验收通过** | 合成输入负向 probe |
| `PYTHONDONTWRITEBYTECODE=1 ../../.audit-venv/bin/python -c 'from tools.company_website_finder import CompanyWebsiteFinder'`（backend 目录） | 1，`ModuleNotFoundError: No module named 'httpx'` | 原模块依赖失败 |
| `git status --short` | 0，空输出，源码未改变 | 本地核查 |

日志：

- `logs/ai-hunter-baseline.txt`、`logs/ai-hunter-baseline.json`
- `logs/ai-hunter-negative-probes.txt`、可复跑 `ai_hunter_negative_probe.py`
- `logs/ai-hunter-finder-import.txt`
- `logs/ai-hunter-test-environment.txt`

真实复现的负向输出：

| 合成输入 | 原上游输出 | P2/P3 必须处理 |
|---|---|---|
| `https://evil.invalid/linkedin.com/company/acme` | `linkedin_company` / slug `acme` | 正则仅在校验后的 LinkedIn hostname + path 上使用 |
| `https://127.0.0.1/contact` | `company_site` | 不能把分类函数当 SSRF 防护，公网 IP/DNS/redirect 必须独立校验 |
| `ftp://acme.invalid/contact` | `company_site` | 仅 HTTP(S) |
| `https://www.google.com:443/search?q=acme` | `company_site` | 用 hostname 分类，不能用 netloc 含端口比较 |
| HTML 中同站 `ftp://acme.invalid/contact` | 被 contact discovery 返回 | 返回候选再验证协议、源域名和公共网络策略 |

## 锁定文件 SHA-256

| 文件 | SHA-256 |
|---|---|
| `LICENSE` | `cdcb53c582249b363e222269c002639e8028877f23cdea06a9ee222c47593092` |
| `backend/tools/url_filter.py` | `5ea34d67ff15bea059c2b27b98f91db680195a35f402a55c2118ef3c5f96e3c4` |
| `backend/tools/contact_extractor.py` | `adc37494a64edac5c3a13ef04f4bf886139e85bad9c3155c485c5e92a074d00c` |
| `backend/tools/company_website_finder.py` | `3d74dba49ee08fa93423881f6da88863da28f47c45283d6ea6c5dd3974ed9922` |
| `backend/tools/email_verifier.py` | `56a61f8b4d8b73e4bea9bf9c2f9d90dd6769022cb1a6d973772ccca01845280d` |
| `backend/tools/pdf_parser.py` | `1aa13d71b0b863421538f2d780987eef2cb905483ec98707301c904c828d330b` |
| `backend/requirements.txt` | `3fd0ab092541c4bce209d1cbb902bbc5e91d7151cf5e3b0597f4b411adc504f5` |

## 未验证 / 阻碍

- 全应用测试、AI 调用、真实官网发现、海关数据、DNS/MX、邮件发送：未运行；没有凭据也不需要作为 P0/P2 验收。
- 未安装或审结整套 requirements 的传递许可证与平台兼容性；不能称上游全套复现成功。
- 主 TradeCase 仓库未由本审计修改；复用矩阵的目标是建议，主实施须在实际移植时同步准确路径/改动/测试。
