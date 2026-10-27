# Codex / Claude 宿主验证

2026-10-27，本机Codex CLI 0.164.0-alpha.11.1、Claude Code 2.1.291。三个Skill统一源码同步到项目 `.agents/skills` 和 `.claude/skills`；实跑安装exit0、重复安装unchanged，每份源文件和两端SHA256相同。没有改全局配置。证据 `docs/evidence/P6/skill-install-live-filesystem.json`。

同一业务自然语言提示为 `docs/host-validation-prompt.txt`，SHA256 `8180b62246097556be227c3bdefabb12b55f8500159a3c4054486fc950c51eb0`。输入同为 `fixtures/case_strong`；输出路径通过TRADECASE_DEMO_OUT区分，Case basename均strong。

| 层次 | Codex | Claude Code |
|---|---|---|
| 工具安装/版本检查 | exit0 | exit0 |
| 项目内Skill安装及哈希 | passed | passed |
| 同一CLI包、同一Skill内容 | 已实跑验证 | 文件和CLI契约一致；不能据此称Agent已运行 |
| 实际Agent调用 | 当前Codex会话显式读取安装Skill/SOP和保存提示，然后调用demo/strict；均exit0 | 用户批准一次、预算$1后真实启动受限print调用；exit1、Not logged in |
| 完整Case | completed，synthetic/offline数据 | 未创建；blocked |
| 模型计费 | 当前开发会话成本不可见；没有另起Codex模型调用 | CLI报告total_cost_usd=0，输入/输出tokens均0；实际账单未独立核验 |

Codex验证是现有成熟宿主使用Skill和工具，不是新会话自动发现测试、独立模型benchmark或在线自主背调。再次用普通CLI回放相同fixture，12份业务产物字节哈希完全一致；manifest/events/history中时间及耗时字段不作字节相等要求。该第二次是普通CLI回放，**不是Claude Agent执行**。详细命令和hash见 `host-cli-verification.json`。

## Claude实际尝试及权限

授权为用户直接回复“允许一次，调用预算 $1”。命令使用 `--print --max-budget-usd 1 --no-session-persistence --restricted --permission-mode dontAsk`，仅开放Read和demo/validate/status三种TradeCase Bash命令，MCP配置为空；不会调用capture、SMTP、浏览器研究或编辑代码。没有bypassPermissions，没有写用户授权配置。

启动前普通 `claude auth status --json` 报loggedIn=true/oauth_token；但本次受限调用返回 `Not logged in · Please run /login`，is_error=true，duration_api_ms=0，input/output tokens=0、total_cost_usd=0。两者差异保留，不能把状态检查当作有效会话认证。未读取密钥、自动登录、改配置或重试。原始执行结果见 `claude-invocation.json`、`claude-stdout.json`、`claude-stderr.log`；本阶段诚实归类blocked。

## 后续人工复现

先在用户选择的Claude环境完成正常登录，再确认可用权限和预算；不要为了通过测试自动关闭权限边界。输出目录用新的 `cases/host-claude-N/strong`，从项目根运行本地Claude Code，提交保存的同一提示，并设置TRADECASE_DEMO_OUT。保持最多$1模型预算、Read及上述3个CLI命令、无外部写操作。成功后由独立CLI运行validate --strict并比较12份业务产物；把新的认证方式、调用成本和结果另存，不覆盖本次失败证据。

本任务没有验证Claude Agent完整链路；双宿主文件同步与可移植CLI已通过。此缺口不阻止本地离线演示，但禁止宣传“双Agent已全部在线验收”。
