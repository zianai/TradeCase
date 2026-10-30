# TradeCase — Visual Task 集成升级实施方案

**文档类型：** 产品需求 + 系统架构 + 工程实施规格  
**目标实施者：** Codex  
**升级方式：** 在现有 TradeCase 上增量开发  
**外部依赖：** Creative Engine（独立服务）  
**目标：** 将外贸询盘分析、产品匹配、视觉提案、人工审核和跟进准备连接成完整的业务工作流。

---

## 1. 项目背景与升级目标

### 1.1 现有项目基础

TradeCase 已完成 V1 离线业务闭环。

已知基线：

- 开发分支：`codex/tradecase-v1`
- 最近报告提交：`e446f94`
- 315 项测试通过。
- 七组合成 Case 严格校验通过。
- 已实现询盘解析、买家研究、证据评分、两类合规检查、英文草稿、人工任务和可恢复报告。
- 三个 Skill 已同步到 Codex / Claude 项目目录。
- 真实邮件发送次数为 0。

上述为此前的开发进度报告，Codex 必须在当前仓库中重新核验，不能假设仓库状态仍然完全一致。

### 1.2 当前存在的业务缺口

现有 TradeCase 主要围绕信息调查和文本交付。

在外贸业务中，部分询盘需要更进一步的产品视觉方案，例如：

- 买家要求 OEM Logo 定制。
- 买家想比较不同颜色、材质和包装。
- 买家需要查看多个 SKU 的差异。
- 买家询问尚未生产的 ODM 产品方案。
- 销售人员需要准备可视化买家提案。

TradeCase 应能识别上述需求并创建适当的 Visual Task。

### 1.3 升级后的核心目标

形成如下闭环：

**Inquiry → Buyer Research → Product Match → Visual Opportunity → Visual Task → Creative Engine → Visual Review → Buyer Proposal → Follow-up Draft**

原有不需要图片的询盘，仍然沿用原流程。

Visual Task 是可选业务分支，不是所有 Case 的强制步骤。

### 1.4 明确不做的事情

- 不把 Creative Engine 的生图功能复制到 TradeCase。
- 不在 TradeCase 内重新开发 Oracle MCP 或图像 Provider。
- 不重新开发通用 Agent ReAct Loop。
- 不改变现有证据评分的事实来源规则。
- 不把 AI 生成图作为证明买家或产品真实性的证据。
- 不自动发送邮件。
- 不自动将图片发送给外部客户。
- 不自动发布电商素材。
- 不为了新增 Visual Task 重写现有全部工作流。

---

## 2. TradeCase 升级后的模块划分

### 2.1 保留原有核心模块

保留已实现的：

1. Inquiry Parser
2. Buyer Research
3. Evidence & Confidence
4. Compliance Checker
5. Follow-up Draft
6. Human Task
7. Report & Artifact

这些模块继续作为 TradeCase 的事实与业务基础。

### 2.2 新增六个组件

| 新模块 | 作用 |
|---|---|
| Visual Opportunity Detector | 判断某个 Case 是否值得创建视觉任务 |
| Product Context Resolver | 整理与图片相关的产品事实和素材 |
| Visual Task Manager | 创建、审批、追踪视觉任务 |
| Creative Engine Client | 调用独立的 Creative Engine |
| Visual Result Reconciler | 接收、校验并关联生成结果 |
| Buyer Proposal Builder | 将已审核图片组织成买家提案材料 |

这些模块形成独立的 Visual Domain。

不允许把它们全部塞进原有的询盘解析或报告生成逻辑。

---

## 3. Visual Task 在现有工作流中的位置

推荐业务流程：

```text
Inquiry Received
        │
        ▼
Inquiry Parsing
        │
        ▼
Buyer Research
        │
        ▼
Evidence Validation
        │
        ▼
Product Requirement Extraction
        │
        ├────────────────────┐
        ▼                    ▼
Compliance Check     Visual Opportunity
        │                    │
        │              No / Suggested
        │                    │
        │               User Decision
        │                    │
        │               Visual Planning
        │                    │
        │               Creative Engine
        │                    │
        │                Visual QA
        │                    │
        │               Human Review
        │                    │
        └──────────┬─────────┘
                   ▼
           Buyer Proposal
                   │
                   ▼
            Follow-up Draft
                   │
                   ▼
               Case Report
```

**关键：Visual Task 必须异步执行。**

买家研究和合规分析不能因为生图耗时或服务不可用而被阻塞。

如果 Visual Task 尚未完成，Case Report 可以先生成，并明确标注视觉任务正在等待审批或执行。

视觉结果完成后，可以生成新的 Report Revision，但不能覆盖旧报告及其证据快照。

### 3.1 与 LangGraph 的关系

如果现有版本已经使用 LangGraph，应在业务图中加入轻量级的 `visual_opportunity` 和 `visual_dispatch` 节点。

LangGraph 只负责：

- 判断何时提出视觉任务。
- 创建并记录异步任务。
- 判断业务是否需要等待人工审核。
- 接收最终任务状态并更新 Case。

长时间运行的图像生成由 Creative Engine 自己的 Worker 执行。

如果现有版本还没有实际落地 LangGraph，则优先使用现有的 Workflow Orchestrator 增量扩展，不要为了新增 Visual Task 先进行一次大规模框架迁移。

---

## 4. Visual Opportunity Detector

这是此次升级最重要的业务智能模块之一。

它决定一个询盘是否具有视觉方案价值。

### 4.1 触发机制

支持两种触发：

**自动建议**

系统在询盘解析、需求提取和产品匹配后，判断是否存在值得出图的业务需求。

只生成建议，不自动产生费用。

**用户主动创建**

用户可以在任何 Case 中手动选择创建视觉任务。

手动创建也必须通过产品事实与权限校验。

### 4.2 建议的视觉意图分类

| Visual Intent | 典型触发条件 | 默认策略 |
|---|---|---|
| `product_comparison` | 买家比较多个产品或型号 | reuse / compose |
| `oem_preview` | Logo、颜色或表面工艺定制 | compose / edit |
| `packaging_preview` | 定制彩盒、标签、外包装 | compose / edit |
| `spec_illustration` | 需要展示尺寸、配置、结构差异 | reuse / compose |
| `odm_concept` | 需要探索新的产品造型 | generate |
| `buyer_presentation` | 需要将素材整理成可视化提案 | reuse / compose |

这里的策略只是默认值，最终由 Creative Engine 根据参考素材和约束确定。

### 4.3 不需要出图的场景

例如：

- 只询问价格。
- 只询问 MOQ。
- 只询问交期。
- 只询问付款条款。
- 产品图片已经充分且满足沟通目的。
- 缺乏必要事实或授权，无法形成可信方案。

系统应返回 `not_recommended` 或 `needs_input`，并解释原因。

不得为了提高生图调用量而强制触发视觉任务。

### 4.4 建议生成机制

推荐“规则优先 + Agent 语义判断”。

确定性规则检查明显的定制诉求、已有素材及必要事实。

Agent 分析复杂或隐含的买家诉求，并生成：

- 视觉意图。
- 推荐理由。
- 对应的买家需求证据。
- 期望生成的视觉成果。
- 缺少的必要素材。
- 是否适合生成。
- 估计的业务价值等级。

Agent 不直接提交生成任务。

所有建议先经过 Schema 验证和规则门控。

每个 Case 默认展示优先级最高的少量建议，避免产生大量无意义任务。

---

## 5. Product Context Resolver

Visual Task 必须建立在真实的产品信息之上。

现有买家背调证据与产品事实应明确区分。

### 5.1 产品资料来源

支持：

- 用户输入的产品资料。
- 产品目录中的真实 SKU。
- 上传的产品规格表。
- 已确认的报价资料。
- 真实产品图片。
- 已授权的 Logo 和包装素材。
- 已确认的供应商定制能力。

本阶段可采用轻量级产品目录和 CSV / JSON / 文件导入，不要求自研完整 PIM 或 ERP。

### 5.2 产品事实快照

每次创建 Visual Task 前，生成不可变的 Product Truth Snapshot。

至少包含：

- SKU 或产品标识。
- 产品名称。
- 尺寸和材质。
- 可选颜色。
- 已确认的结构特征。
- 已确认的定制能力。
- 事实来源。
- 事实状态。
- 素材引用。

事实状态区分：

`verified / supplier_claim / unverified / concept`

只有具有足够证据、且允许用于该交付用途的信息，才能被用于真实产品承诺。

### 5.3 不完整信息的处理

不能用模型猜测填补事实空缺。

例如买家希望把普通狗笼改成自动升降式狗笼，但目前没有可制造性确认。

系统可以创建 `odm_concept`，展示明确标识的概念方案；不能把生成效果图描述成已量产产品。

### 5.4 图像素材关联

源图片必须有：

- Asset ID。
- 文件类型及 Hash。
- 产品关联。
- 来源说明。
- 授权状态。
- 是否属于真实产品素材。
- 是否允许外部使用。

上传文档、网页内容和图片内嵌文字都属于不可信输入，不允许它们直接覆盖系统指令或执行规则。

---

## 6. Visual Task 数据模型

在保留原有 Case、Task、Attempt 和 Artifact 语义的前提下，新增 Visual Task 业务实体。

建议以独立表或领域模型实现，不要将全部视觉字段直接追加到通用 Task 表。

### 6.1 VisualTask

建议字段：

```json
{
  "id": "vt-001",
  "case_id": "case-001",
  "task_type": "visual_production",
  "intent": "oem_preview",
  "status": "awaiting_plan_approval",
  "skill": "buyer-proposal",
  "product_ref": "SKU-001",
  "truth_snapshot_id": "truth-v3",
  "evidence_refs": ["evidence-01"],
  "source_asset_ids": ["asset-01"],
  "fidelity": "controlled",
  "delivery_target": "buyer_proposal",
  "requested_variants": 3,
  "requires_human_approval": true,
  "creative_engine_batch_id": null
}
```

字段示例是 TradeCase 新增契约，不是现有实现。

### 6.2 数据表建议

新增：

- `visual_tasks`
- `visual_task_events`
- `visual_task_assets`
- `visual_plan_snapshots`
- `visual_reviews`
- `creative_engine_runs`

其中：

`visual_tasks` 保存业务任务与当前状态。

`visual_plan_snapshots` 保存每次提交前已批准的计划及版本。

`creative_engine_runs` 保存外部 Batch ID、请求幂等键、同步游标、远端状态和最近一次同步时间。

`visual_task_assets` 保存图片资产关联，不复制原有事实证据语义。

`visual_reviews` 保存审核人、审核时间、决定、意见及所对应的图片版本。

状态变化记录到事件表，支持审计。

### 6.3 状态模型

建议使用以下本地状态：

```text
suggested
    ↓
needs_input / draft
    ↓
awaiting_plan_approval
    ↓
queued
    ↓
running
    ↓
qa_pending
    ↓
awaiting_asset_review
    ↓
approved / rejected
    ↓
attached_to_proposal
```

另外支持：

`blocked / failed / cancelled / reconciling`

注意，Creative Engine 有自己的 Batch 和 Asset 状态。

TradeCase 不应强行让两个系统使用完全相同的枚举，而应在 Adapter 中维护版本化状态映射。

远端 `completed` 不等于 TradeCase 的 `approved`。

图片生成完成后，必须继续经过业务审批。

---

## 7. Creative Engine 集成协议

### 7.1 集成方式

采用独立 HTTP Client Adapter。

TradeCase 通过标准化的 REST API 调用 Creative Engine。

不直接导入 Creative Engine 的内部数据库或业务实现。

假设 TradeCase 的现有主要后端仍采用 Python，可使用：

- `httpx`：异步 HTTP。
- `Pydantic`：输入输出验证。
- 现有任务与存储基础设施：持久化。
- 现有 CLI / Web：业务交互。

实际依赖和路径以仓库审计为准。

### 7.2 逻辑接口

Creative Engine 已规划的 API 包括：

```text
POST /v1/briefs
POST /v1/briefs/:id/plan

POST /v1/batches
GET  /v1/batches/:id

GET  /v1/assets/:id
POST /v1/assets/:id/review

POST /v1/exports
GET  /v1/exports/:id

GET  /v1/events
```

这些是前一轮 Creative Engine 的设计契约。

Codex 必须核验实际实现，并固定双方共享的 API Schema 版本。

如果接口尚未落地，先通过 Contract Fixture 和 Mock Creative Engine 完成 TradeCase 侧集成，再与真实服务进行契约验证。

不得把 Mock 成功表述为真实生图已经集成成功。

### 7.3 TradeCase → Creative Engine

示例业务请求：

```json
{
  "source": {
    "system": "tradecase",
    "case_id": "case-001",
    "visual_task_id": "vt-001"
  },
  "skill": "buyer-proposal",
  "intent": "oem_preview",
  "product": {
    "id": "SKU-001",
    "truth_snapshot_id": "truth-v3"
  },
  "reference_assets": ["asset-front"],
  "evidence_refs": ["evidence-01"],
  "constraints": {
    "fidelity": "controlled",
    "allowed_changes": [
      "authorized_logo",
      "color"
    ],
    "preserve": [
      "product_structure",
      "dimensions"
    ]
  },
  "delivery_target": "buyer_proposal",
  "variants": 3,
  "requires_human_approval": true
}
```

示例仅用于定义交互语义。

实际 API 调用必须符合双方确认的 OpenAPI Schema。

### 7.4 数据最小化

TradeCase 不应把完整买家背调报告、买家邮箱和个人联系方式全部传给图像引擎。

Creative Engine 只需要相关的：

- 产品事实。
- 视觉需求。
- 目标市场或使用场景。
- 已授权参考素材。
- 设计约束。
- 必要的交付规范。

买家敏感信息在 TradeCase 内保存。

跨服务素材访问必须通过受控文件通道，不能将本地任意文件路径当作远端有效地址。

### 7.5 认证与传输

至少实现：

- 服务认证 Token。
- 本地最小权限配置。
- 上传文件大小与类型限制。
- 安全的文件读取与导出。
- 请求超时。
- Idempotency Key。
- API 版本校验。
- 错误码映射。
- 请求关联 ID。

如果后续启用回调 Webhook，必须验证签名并防止事件重放。

### 7.6 异步状态同步

推荐实现：

1. TradeCase 提交 Batch。
2. 保存 Creative Engine Batch ID。
3. 返回本地 VisualTask ID。
4. 后台 Worker 定时同步远端状态。
5. 更新本地事件与任务状态。
6. 通过现有实时事件通道通知前端。
7. 任务完成后接收并校验资产清单。

可以兼容 Webhook，但轮询恢复机制仍需保留，避免由于回调丢失造成永久卡单。

网络中断时，优先按幂等键和 Batch ID 查询之前的操作结果，不能立即重复提交付费任务。

---

## 8. Visual Plan 审批机制

不能从“AI 建议出图”直接跳转到“开始收费生成”。

必须增加计划确认环节。

### 8.1 用户能够审查的内容

- 为什么需要该图片。
- 基于哪个买家需求。
- 使用哪个 SKU。
- 参考图是否正确。
- 产品哪些属性允许修改。
- 哪些内容必须保持不变。
- 图片数量与用途。
- 预计费用及预算上限。
- 交付结果是否属于 Concept。

### 8.2 用户确认后才执行

Visual Plan 的审批与最终图片审核分开管理。

**Plan Approval：** 授权执行、预算和修改范围。

**Asset Approval：** 确认生成结果适合进入实际业务交付物。

任何未通过的任务都不能跳过对应门控。

如果计划被修改，应重新生成计划版本或重新请求确认。

---

## 9. Visual Result 与现有证据系统的关系

这是必须严格设计的边界。

### 9.1 两种独立对象

**Evidence**

用于支持关于买家、产品、企业、法规、市场的事实判断。

**VisualAsset**

用于沟通、展示和辅助设计。

两者可以有来源关联，但不能互相替代。

AI 图片不得自动成为买家真实性、产品实际存在、工厂制造能力或产品认证的证据。

### 9.2 结果回收

Creative Engine 返回图片后，TradeCase 需要：

- 校验图片文件或资产引用。
- 检查关联的 VisualTask。
- 检查所用产品事实快照是否仍然有效。
- 保存生成版本与 QA 报告。
- 检查是否需要人工审核。
- 设置业务可用状态。

如果生成期间产品参数发生更新，旧任务结果必须标记为需要重新评估，而不能静默归入最新产品。

### 9.3 双重审核

Creative Engine 负责通用视觉 QA，例如产品外观变化、构图和图像异常。

TradeCase 负责业务审核，例如：

- 是否符合询盘要求。
- 是否对应正确的 SKU。
- 是否使用了未授权的买家 Logo。
- 是否暗示未经确认的制造能力。
- 是否出现错误参数或认证声明。
- 是否与报价、合同或邮件描述冲突。

最终是否可用于买家提案，由 TradeCase 的业务审核控制。

---

## 10. Buyer Proposal Builder

在视觉审核通过后，生成可视化买家提案材料。

### 10.1 提案内容

建议支持：

- 买家需求摘要。
- 推荐的产品或 SKU。
- 产品实拍或已确认产品素材。
- 已审核的定制效果。
- 不同方案的对比。
- 已确认的产品规格。
- 需要买家确认的问题。
- 需要供应商确认的问题。
- 概念图免责声明。
- 可用于邮件跟进的素材附件清单。

### 10.2 与现有报告集成

现有 Case Report 增加可选 `Visual Proposal` 区块。

必须保证：

- 未创建 Visual Task 时，不产生空白章节或兼容性错误。
- Visual Task 运行中时，报告可继续生成。
- 审核失败时，报告记录任务问题而不是引用失败图片。
- 审核通过时，可以生成新的报告版本并关联图片。
- 所有关联内容都有可追踪的来源与版本。

### 10.3 与英文邮件草稿集成

允许 Follow-up Draft 引用已批准的图片与产品方案。

例如：

- 提示附上 OEM 效果预览。
- 提示买家确认颜色和 Logo 位置。
- 提示某个方案仍需工厂可行性确认。

草稿不得将概念图描述成已经生产或已经通过验证的真实产品。

保留原有的人工发送限制。

**邮件生成与邮件发送属于两件独立操作。**

本次只做到交付材料准备和草稿生成，不自动发送任何真实邮件。

---

## 11. TradeCase 前端升级

建议保留原有 Case 工作台的信息架构。

新增两个视觉入口。

### 11.1 入口 A：Case 内的智能建议

在 Case 详情页增加 `Recommended Actions`。

根据询盘与研究结果，展示与视觉有关的推荐动作。

例如：

**建议创建 OEM 产品定制预览**

原因：买家明确询问木纹颜色与 Logo 定制。

所需资料：现有产品正面图、买家 Logo、定制确认信息。

用户可以查看方案或选择暂不生成。

### 11.2 入口 B：Visual Tasks 面板

在 Case 中增加 `Visuals` 选项卡或子面板。

应包含以下功能：

| 功能 | 交互 |
|---|---|
| Create Visual Task | 主动创建视觉任务 |
| Review Visual Plan | 预览并审批生成计划 |
| Task Status | 查看批量任务进度 |
| Visual Gallery | 查看生成候选图 |
| Compare | 原图与生成图对比 |
| Review | 批准、拒绝、提出修改要求 |
| Attach to Proposal | 选择批准素材加入提案 |
| Export | 下载审核通过的素材包 |

### 11.3 推荐用户操作路径

打开某个 Case 后：

1. 查看系统识别的视觉机会。
2. 选择需要创建的视觉方案。
3. 补充系统指出的必要资料。
4. 预览 Visual Plan 和预算。
5. 确认执行。
6. 在 Visual Gallery 查看结果。
7. 审核、选择或修改图片。
8. 将已批准素材加入 Buyer Proposal。
9. 生成更新后的报告和跟进邮件草稿。

前端优先复用现有设计系统，不额外开发一套 Creative Engine 的复制界面。

---

## 12. CLI 与 Agent 接口

TradeCase 原有的 CLI 能力必须保留。

建议增加：

```text
tradecase visual suggest --case <id>

tradecase visual plan --case <id> \
  --intent oem_preview

tradecase visual create --case <id> \
  --plan <path>

tradecase visual status <visual-task-id>

tradecase visual approve-plan <visual-task-id>

tradecase visual review <visual-task-id>

tradecase visual revise <visual-task-id> \
  --instructions <text>

tradecase visual attach <visual-task-id>

tradecase visual export <visual-task-id>
```

以上为目标命令语义，最终命令名称需与仓库现有 CLI 风格保持一致。

所有命令支持结构化 JSON 输出。

其中 `suggest` 和 `plan` 默认不执行付费生图。

提交、审批、取消和导出等写操作必须检查权限及任务状态。

### 12.1 API 设计

TradeCase 对前端提供本地业务 API，例如：

```text
POST /api/v1/cases/:id/visual/suggestions

POST /api/v1/cases/:id/visual-tasks
GET  /api/v1/cases/:id/visual-tasks

GET  /api/v1/visual-tasks/:id
POST /api/v1/visual-tasks/:id/approve-plan
POST /api/v1/visual-tasks/:id/cancel

POST /api/v1/visual-tasks/:id/revisions
POST /api/v1/visual-tasks/:id/reviews

POST /api/v1/visual-tasks/:id/attach
POST /api/v1/visual-tasks/:id/export
```

这些端点对接 TradeCase 的业务状态与权限模型，不应直接暴露 Creative Engine 的内部操作。

---

## 13. 故障处理与可恢复性

Visual Task 涉及外部服务和付费资源，必须具有与现有 TradeCase 一致的可恢复设计。

### 13.1 Creative Engine 不可用

TradeCase 必须：

- 仍能完成询盘分析。
- 仍能创建和保存视觉建议。
- 明确报告外部服务不可用。
- 不伪造完成图片。
- 允许用户在服务恢复后重新提交。

### 13.2 任务超时

任务状态进入 `reconciling`。

先查询远端是否接受或完成任务。

只有确认安全、符合幂等和预算约束后，才能重试。

### 13.3 部分图片失败

保留已成功生成的资产。

允许仅针对失败的子任务重新执行。

不能因为批次部分失败就重复生成所有图片。

### 13.4 用户取消任务

停止创建新的子任务，并尝试调用远端取消能力。

已经开始且无法取消的 Provider 操作，应正确记录其后续结果与费用。

不得虚假显示已完全撤销。

### 13.5 图片审核失败

记录问题、原图及拒绝原因。

如果需要修改，创建新 Revision。

不覆盖旧版图片。

### 13.6 重复提交

使用业务任务 ID、VisualPlan Hash、计划版本及幂等键控制重复请求。

保证本地状态可靠，并在外部系统支持的范围内实现幂等提交。

---

## 14. 安全、合规与权限

至少设置三个权限门控：

**Execution Gate**

确认允许调用付费 Provider，检查预算和数据处理授权。

**Fact Gate**

检查生成方案使用的产品事实是否足够可信，禁止将未经核实的信息包装成真实承诺。

**External Delivery Gate**

确认图片已经经过人工审核，且允许提供给买家。

此外需要：

- 不向 Creative Engine 传递无关买家隐私。
- 不在日志里保存 API Key 或浏览器 Cookie。
- 仅允许引用当前项目授权的素材。
- 禁止任意文件路径访问。
- 限制图片文件大小和类型。
- 检查 Logo 和品牌使用授权。
- 检查概念方案与真实产品之间的标识。
- 维护审批日志。
- 支持关闭 Visual Task 功能而不影响现有业务。

Oracle 相关能力由 Creative Engine 内部管理，TradeCase 不直接调用网页生图或绕过第三方服务限制。

---

## 15. 配置与部署

建议提供以下配置语义：

```text
TRADECASE_VISUAL_ENABLED=false

CREATIVE_ENGINE_BASE_URL=
CREATIVE_ENGINE_API_TOKEN=
CREATIVE_ENGINE_API_VERSION=v1

VISUAL_DEFAULT_SKILL=buyer-proposal
VISUAL_REQUIRE_PLAN_APPROVAL=true
VISUAL_REQUIRE_ASSET_APPROVAL=true

VISUAL_MAX_VARIANTS_PER_TASK=8
VISUAL_MAX_BUDGET_PER_BATCH=
VISUAL_SYNC_INTERVAL_SECONDS=15
```

具体配置名及预算单位由 Codex 与现有配置体系统一。

默认关闭真实 Provider 执行，待服务连接、权限、模型与预算校验完成后再启用。

支持 Mock Creative Engine，以便本地无凭据运行全部业务流程。

---

## 16. 工程实施任务

此次实施是一次完整功能升级，但按依赖关系分阶段开发和验收。

### P0 — 现有仓库审计与基线保护

Codex 首先检查：

- 当前分支与提交。
- 项目目录结构。
- 现有 Task、Artifact、Case Schema。
- 现有 Orchestrator 与 Agent SDK 适配。
- 现有 CLI / API / UI。
- 测试基线。
- 状态与持久化机制。

建立升级分支。

不要在未完成现状审计之前直接重构核心代码。

### P1 — Visual Domain 与 Schema

新增 VisualTask、VisualPlanSnapshot、VisualReview 和 CreativeEngineRun 等实体。

完成数据库迁移、Schema 验证、状态机及事件记录。

保持旧 Case 数据可读。

### P2 — Visual Opportunity Detector

新增视觉机会识别 Skill。

实现规则判断、Agent 辅助识别、证据绑定、建议排序及不推荐解释。

支持纯离线测试。

### P3 — Product Context Resolver

实现产品数据导入、参考素材绑定、产品事实快照和证据状态检查。

确保视觉规划不虚构真实产品事实。

### P4 — Creative Engine Adapter

实现标准 HTTP Client、错误处理、状态同步和契约测试。

先使用 Mock Creative Engine 验证，再接入实际 Creative Engine 服务。

不得直接复制 Creative Engine 的生成、调度和 QA 代码。

### P5 — Visual Task Workflow

实现计划审批、异步执行、状态恢复、取消、失败处理、预算约束和任务版本管理。

与现有 Orchestrator 集成。

### P6 — Visual QA 结果处理及 Buyer Proposal

实现结果回收、业务审核、版本追踪和 Buyer Proposal Builder。

升级 Report 和 Follow-up Draft，使其能够引用已批准的视觉素材。

不修改真实邮件发送权限。

### P7 — Web UI / CLI / API

实现 Visual Task 创建、计划审批、任务监控、图片画廊、人工审核和导出。

保证 UI 操作真实连接后端。

### P8 — 系统测试与验收

完成：

- 原有功能回归。
- 数据迁移测试。
- Visual Task 单元测试。
- Creative Engine Contract Tests。
- 模拟故障测试。
- CLI / API 集成测试。
- 浏览器 E2E。
- 真实服务可用时的端到端验证。
- 最终文档和验收报告。

每阶段完成后运行测试并提交，不把未实际验证的能力标记为完成。

---

## 17. 必须覆盖的验收 Case

| 测试场景 | 预期结果 |
|---|---|
| 普通 MOQ 询盘 | 正常完成原流程，不强制出图 |
| 买家要求 Logo 定制 | 识别 Visual Opportunity |
| 缺少 Logo 授权 | 阻止未经授权的品牌图像生产 |
| 买家要求多 SKU 比较 | 优先复用真实产品素材 |
| 买家要求 ODM 新结构 | 标记概念方案，不当作现有产品 |
| 没有完整 SKU 参数 | 明确缺失信息，不推测补齐 |
| Creative Engine 离线 | 原 Case 分析继续运行 |
| 人工未批准 Plan | 不产生付费生图请求 |
| 远端 Batch 超时 | 查询并恢复，不盲目重复收费 |
| 一批图片部分失败 | 保留成功资产，仅恢复必要任务 |
| QA 检测产品结构变化 | 阻止直接进入提案 |
| 人工拒绝图片 | 保留历史，支持 Revision |
| 图片生成后 SKU 更新 | 标记旧资产需要重新核验 |
| 未批准图片加入邮件 | 被 External Delivery Gate 拦截 |
| 已批准图片加入提案 | 创建可追踪的 Buyer Proposal |
| 无真实 Provider 凭据 | Mock 离线闭环可运行且结果清晰标识 |
| 原有合成 Case | 原有输出及严格校验不退化 |
| 邮件发送控制 | 未发生未经授权的真实邮件发送 |

---

## 18. 产品效果与评估指标

在可运行的技术闭环之外，还应记录真实的产品使用指标。

建议监测：

**业务效率**

- 从买家提出视觉需求到完成可审核提案的时间。
- 单个询盘的视觉任务数量。
- 人工补充信息次数。
- 因产品事实不足而阻止生成的次数。

**视觉质量**

- 首次生成的人工通过率。
- 产品不一致问题率。
- 单个批准资产的平均返工次数。
- 最终资产的复用率。

**系统可靠性**

- 任务成功率。
- 重复收费请求数。
- 任务恢复成功率。
- 平均生成成本。
- 外部服务故障对原有 Case 流程的影响。

**业务结果**

- 使用 Visual Proposal 后的买家回复情况。
- 买家方案确认情况。
- 样品或报价推进情况。

业务结果必须结合真实使用数据评估，不能将模拟 Case 表现解释为询盘转化率实际提升。

---

## 19. 推荐代码组织

以下为逻辑目录，仅供 Codex 按实际仓库结构映射。

```text
tradecase/
├── domain/
│   ├── cases/
│   ├── evidence/
│   └── visual/
│       ├── models
│       ├── schemas
│       ├── states
│       └── policies
│
├── services/
│   ├── buyer_research
│   ├── compliance
│   ├── visual_opportunity
│   ├── product_context
│   ├── visual_task
│   ├── visual_result
│   └── buyer_proposal
│
├── integrations/
│   └── creative_engine/
│       ├── client
│       ├── contracts
│       ├── state_mapping
│       └── mock
│
├── workflows/
│   ├── case_workflow
│   └── visual_workflow
│
├── skills/
│   └── visual_opportunity/
│
├── api/
├── cli/
├── ui/
├── migrations/
└── tests/
```

如果现有项目使用其他包组织形式，应保持原有风格。

不为符合示意目录而进行无意义的重构。

---

## 20. 最终交付要求

Codex 应交付：

1. 基于现有 TradeCase 升级的完整实现。
2. 新增 Visual Domain 和相应数据迁移。
3. Visual Opportunity Detector。
4. Product Context Resolver。
5. Creative Engine 适配接口。
6. 可恢复的 Visual Task 工作流。
7. Plan Approval 与 Asset Approval。
8. Buyer Proposal Builder。
9. Case Report 与英文草稿的视觉引用功能。
10. Web UI、CLI 和 API。
11. Mock 全链路测试及可用时的真实服务测试。
12. 完整的测试报告、架构说明和升级日志。

最终验收必须清楚区分：

- 已完成并通过测试的功能。
- 已与真实 Creative Engine 验证的功能。
- 仅通过 Mock 验证的功能。
- 因服务、凭据或环境限制而尚未验证的功能。

---

## 21. Codex 最终执行指令

请根据本方案，对当前 TradeCase 仓库进行增量升级。

首先审计现有项目，确定代码结构、工作流、数据库及测试基线，并对照之前的 `codex/tradecase-v1` 分支和提交 `e446f94` 核实实际状态。

以最小破坏性方式增加 Visual Task 业务域。

保留原有的询盘解析、买家背调、证据评分、合规检查、英文草稿、人工任务及报告能力，不因新增功能而改变其基本语义。

通过标准 API 接入独立 Creative Engine，不在 TradeCase 中重复开发图像生成器、图片批量执行器、Oracle 浏览器自动化或通用视觉 QA。

新增业务智能判断，让 TradeCase 能根据买家需求提出 Visual Task 建议，支持用户审核 VisualPlan，调用 Creative Engine，回收图片结果，完成业务审核，并将批准素材加入 Buyer Proposal 和跟进草稿。

优先保证 Product Truth、Evidence 和 VisualAsset 的边界清晰，防止模型生成内容反向污染事实证据。

**本次升级的完成标准：**

用户打开一个 TradeCase，系统可以识别买家的视觉需求，推荐适当的产品视觉任务，要求必要的素材和授权，预览并确认生成计划，调用 Creative Engine，监控生成过程，审核图片结果，最后输出与当前询盘相关、来源可追溯、已经人工批准的买家视觉提案。

在不需要图片的询盘中，原有业务流程保持正常且无需额外操作。

在 Creative Engine 不可用的情况下，TradeCase 仍能正常完成原有业务分析。

所有实现都需要实际测试、提交和记录，不允许仅输出架构设计或静态 Demo 便宣称升级完成。