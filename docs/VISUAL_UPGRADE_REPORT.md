# Visual Task 升级验收记录

日期：2026-10-30。功能代码提交：5bc0d4e（codex/tradecase-visual-tasks）。原始起点：11147c1。用户原有询盘、Skills、证据评分、合规、草稿与报告语义保留；旧本地未提交的访问策略改动不混入本次提交。

## 实际执行

| 验证对象 | 结果 | 范围 |
|---|---|---|
| 历史 e446f94 导出树 | 315 passed | 独立临时目录执行 |
| 历史 codex/tradecase-v1 / 3a4f8b4 | 347 passed | 独立临时目录执行 |
| 升级前工作区 | 497 passed / 4 skipped | 当时未设置基础设施测试变量 |
| 最终完整工作区 | 538 passed / 0 skipped | 显式隔离 PostgreSQL、Redis、备份恢复、迁移及视觉回归；1 条 ARQ close 弃用警告 |
| 本次独立提交树 + 新增本地视觉测试 | 505 passed / 4 skipped | 排除旧未提交业务改动；随后 4 项基础设施测试单独补跑全部通过，合计 509 项 |
| 浏览器新流程 | 3 passed | 真实 Next/API/数据库，Mock Engine，桌面与 390px；图片解码、Logo 建议、MOQ 原流程 |
| 浏览器既有回归 | 11 passed | UI、草稿与 SSE 取消 |
| CLI | suggest/status/export 退出 0 | 与实际本地 API 通信，提案 ZIP |
| 原有七组合成 Case | 14 命令退出 0 | 每组 demo + strict validate |
| 类型与生产构建 | 退出 0 | TypeScript、Next production build |
| 分发包 | wheel + sdist 构建成功 | visual 包注册 |
| UI 运行检查 | 0 fail / 7 warn | 既有样式、间距及移动端控件尺寸建议；不等于用户视觉签核 |

运行日志保存于 `.tradecase/visual-validation`，服务集成证据保存于 `docs/evidence/visual-upgrade-2026-10-30`。按用户要求不提交测试集、测试素材、截图、运行数据库或 Token；此文件只提交执行摘要。

## 真实 Creative Engine 与模拟边界

实际发现同级 Creative Engine 仓库 HEAD 9275a01，本地服务发布 1.0.0 OpenAPI，已固定契约。通过 HTTP 执行项目/授权素材/产品事实/Brief/Plan/Batch、轮询及哈希核验下载，没有导入 Engine 数据库或复制生成/QA 实现。

两条业务链路实际通过：概念方案的 Mock Provider；以及原 Case 工作流 → 明确虚构但声明已审核的 SKU/参考素材 → 计划批准 → Engine 确定性合成 → 图片业务批准 → 提案 ZIP → 草稿修订 → NEEDS_REVIEW。确定性合成是实际图像组合操作，不是付费生成模型。浏览器验收使用固定 Mock 图片，页面明确标注；不据此声称真实视觉质量或商业效果。

付费 OpenAI/Oracle 图像 Provider 和生产环境认证部署未验证。Engine 不可用、未批准或参数错误不会阻塞原 Case 分析。所有模拟审批只作用于隔离验收案例，未替用户批准原版本 9 案例，未发送邮件。

## 修复与失败保留

开发期间迁移元数据与新增收据表不同步导致首次全量 2 失败；冻结 schema 后重跑通过。概念预览身份规则更新期间有旧测试预期失败，按实际 Engine 合约修正后通过。浏览器发现过日期序列化及可访问标签问题，修复后重跑。真实 HTTP 测试发现旧测试 PNG CRC 错误、非规范 logo 变更名称、确定性 compositor 的 Provider/概念身份差异；修正固定测试图、输入枚举和精确状态映射后验证成功。失败日志保留本地，没有当作首次成功。

独立复核还找到并修复：未知提交结果误回 queued、生成图反向作为产品源图、比较 SKU 过期、计划执行配置变更、数据保留时遗漏请求收据、blocked 任务仍有远端活跃批次。回归覆盖这些边界。

## 保留限制

Agent 语义建议有宿主输入契约和原句校验，本轮没有新增付费语义 Agent 调用。部分失败修订只恢复失败数量，成功旧资产保留历史，但不自动合并不同计划版本的审批。无法证实的远端结果保持待对账；不提供绕过授权的强制重试。产品 verified 是授权用户提供的事实状态，不代表系统独立认证了制造能力。

本地全链路交付已测试；生产上线、真实付费生成、第三方服务许可、真实产品视觉质量与买家转化结果不属于已验证范围。
