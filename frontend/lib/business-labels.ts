// Turns stored machine values into the wording business users read. Unknown
// values stay visible behind a neutral label, so a new backend enum can never
// be silently presented as a known business meaning.
import { Row, row, rows, text } from "@/lib/api";

function lookup(table: Record<string, string>, value: unknown, other: string) {
  const key = text(value, "");
  return table[key] || table[key.toLowerCase()] || (key ? other : "");
}

export function caseCustomer(c: Row): string {
  const inquiry = row(c.inquiry);
  return text(
    inquiry.buyer_company ?? inquiry.buyer_company_hint ?? c.buyer_company,
    "",
  );
}
export function caseProduct(c: Row): string {
  const inquiry = row(c.inquiry);
  return text(c.product ?? inquiry.product ?? inquiry.product_summary, "");
}
/** “客户 · 询盘主题”. Never falls back to an internal case ID. */
export function caseHeadline(c: Row): string {
  const customer = caseCustomer(c);
  const topic = text(c.title, "") || caseProduct(c);
  if (customer && topic)
    return topic.toLowerCase().includes(customer.toLowerCase())
      ? topic
      : `${customer} · ${topic}`;
  return customer || topic || "未命名询盘";
}

const taskOfScope: Record<string, string> = {
  draft_review: "回复草稿待审核",
  mail_send: "邮件发送待授权",
  crm_sync: "CRM 同步待授权",
};
export const approvalTask = (scope: unknown) =>
  lookup(taskOfScope, scope, "事项待审核") || "事项待审核";

const decisions: Record<
  string,
  { label: string; tone: string; advice: string }
> = {
  high_priority: {
    label: "优先跟进",
    tone: "good",
    advice: "评分达到优先跟进线，且依据覆盖充分。",
  },
  normal_priority: {
    label: "正常跟进",
    tone: "neutral",
    advice: "评分达到正常跟进线，可按常规节奏推进。",
  },
  low_priority: {
    label: "暂缓跟进",
    tone: "neutral",
    advice: "当前评分偏低；资料补齐后可以重新评估。",
  },
  needs_review: {
    label: "需要人工判断",
    tone: "warn",
    advice: "现有依据不足以自动给出结论，请人工核对。",
  },
};
/** 0 is “not assessed yet” until an assessment exists, never “low value”. */
export function priorityInfo(c: Row) {
  const assessment = row(c.assessment);
  const decision = decisions[text(assessment.decision, "")];
  const score = Number(assessment.score ?? c.priority);
  if (decision)
    return {
      ...decision,
      detail: assessment.score != null ? `评分 ${score} / 100` : "",
    };
  if (Number(c.priority) > 0)
    return {
      label: `人工标记 ${Number(c.priority)}`,
      tone: "neutral",
      advice: "优先级由人工设定，尚无系统评估。",
      detail: "",
    };
  return {
    label: "待评估",
    tone: "neutral",
    advice: "尚未完成评估，不代表客户价值低。",
    detail: "",
  };
}

const signalNames: Record<string, string> = {
  verified_identity: "企业身份核实",
  buyer_role_evidence: "采购角色依据",
  product_fit_evidence: "产品匹配依据",
  inquiry_specificity: "询盘具体程度",
  contactability: "联系方式可用性",
};
const signalValues: Record<string, { label: string; status: string }> = {
  supported: { label: "有依据支持", status: "SUPPORTED" },
  contradicted: { label: "存在相反依据", status: "BLOCKED" },
  unknown: { label: "尚无依据", status: "PENDING" },
};
const reasonNames: Record<string, string> = {
  INSUFFICIENT_EVIDENCE_COVERAGE: "依据覆盖不足",
  IDENTITY_NOT_SUPPORTED: "企业身份尚未得到依据支持",
  BUYER_ROLE_NOT_SUPPORTED: "采购角色尚未得到依据支持",
  ENTITY_NOT_SELECTED: "尚未确认对应的企业",
  ENTITY_NOT_SUPPORTED: "所选企业缺少依据",
  ENTITY_AMBIGUOUS: "存在同名或多个候选企业",
  BUYER_UNRESOLVED: "买家身份尚未确定",
  ENTITY_FIELD_CONFLICT: "企业资料之间存在冲突",
  INQUIRY_DOMAIN_CONFLICT: "询盘邮箱与企业域名不一致",
};
export const missingLabel = (value: unknown) =>
  signalNames[text(value, "")] || text(value, "");
export const reasonLabel = (value: unknown) =>
  lookup(reasonNames, value, "其他需核对的原因（见技术追溯）");
export function signalRows(assessment: Row) {
  return Object.entries(row(assessment.signals)).map(([key, raw]) => {
    const signal = row(raw);
    const value = signalValues[text(signal.value, "unknown")];
    return {
      key,
      name: signalNames[key] || "其他评估项",
      label: value?.label || "待核实",
      status: value?.status || "PENDING",
      rationale: text(signal.rationale, ""),
      evidenceIds: Array.isArray(signal.evidence_ids)
        ? signal.evidence_ids.map(String)
        : [],
    };
  });
}

const sourceTypes: Record<string, string> = {
  user_provided: "用户提供",
  government: "政府机构",
  platform_official: "平台官方",
  official_site: "企业官网",
  registry: "企业注册库",
  news: "新闻报道",
  directory: "企业名录",
  search_snippet: "搜索结果摘要",
};
export const sourceTypeLabel = (value: unknown) =>
  lookup(sourceTypes, value, "其他来源") || "来源类型未记录";

const licenses: Record<string, string> = {
  permitted: "已获准使用",
  SYNTHETIC: "合成演示资料",
  synthetic: "合成演示资料",
  unknown: "许可未确认",
  restricted: "使用受限",
};
export const licenseLabel = (value: unknown) =>
  lookup(licenses, value, "见技术追溯") || "未记录";

const taskTypes: Record<string, string> = {
  parse_inquiry: "解析询盘",
  plan_research: "制定调查计划",
  identity_research: "核实企业身份",
  company_profile_research: "调查公司背景",
  buying_intent_research: "判断采购意向",
  normalize_entities: "整理企业信息",
  merge_evidence: "汇总证据",
  resolve_conflicts: "处理资料冲突",
  evidence_gate: "检查证据是否充分",
  lead_qualification: "评估客户优先级",
  compliance_checks: "检查市场与平台规则",
  draft_response: "撰写回复草稿",
  deterministic_quality_gate: "检查草稿质量",
  prepare_approval: "准备人工审核",
  visual_opportunity: "判断是否需要图片",
  visual_dispatch: "安排图片任务",
};
export const taskLabel = (value: unknown) =>
  lookup(taskTypes, value, "其他处理步骤") || "处理步骤";

const eventTypes: Record<string, string> = {
  "case.created": "询盘已创建",
  "case.status": "询盘状态已更新",
  "task.created": "处理步骤已安排",
  "task.claimed": "处理步骤已开始",
  "task.succeeded": "处理步骤已完成",
  "task.failed": "处理步骤失败",
  "task.waiting_human": "等待人工处理",
  "agent.finished": "自动调查已结束",
  "artifact.version": "生成了新版本内容",
  "approval.requested": "已发起人工审核",
  "visual.plan.created": "图片计划已创建",
  "visual.plan.approved": "图片计划已批准",
  "visual.synced": "已核对图片制作进度",
  "visual.asset.reviewed": "图片已审核",
  "visual.proposal.attached": "图片已加入买家提案",
};
export const eventLabel = (value: unknown) =>
  lookup(eventTypes, value, "其他系统记录") || "系统记录";

const riskCategories: Record<string, string> = {
  country: "目标市场规则",
  platform: "销售平台规则",
};
export const riskCategoryLabel = (value: unknown) =>
  lookup(riskCategories, value, "其他规则") || "规则检查";
const severities: Record<string, string> = {
  critical: "严重",
  high: "高风险",
  medium: "中等风险",
  low: "低风险",
  info: "提示",
};
export const severityLabel = (value: unknown) =>
  lookup(severities, value, "待评估") || "待评估";

const claimSubjects: Record<string, string> = {
  inquiry: "询盘",
  buyer: "买家",
  company: "公司",
  product: "产品",
};
export const claimSubjectLabel = (value: unknown) => {
  const key = text(value, "");
  return claimSubjects[key] || (/^[a-z0-9_.:-]+$/i.test(key) ? "" : key);
};

export const changeOptions = [
  { value: "color", label: "颜色" },
  { value: "authorized_logo", label: "已授权的品牌标识" },
  { value: "background", label: "背景" },
  { value: "packaging", label: "包装" },
  { value: "layout", label: "版式" },
] as const;
export const structuralOptions = [
  { value: "product_structure", label: "产品结构" },
  { value: "dimensions", label: "尺寸" },
  { value: "material", label: "材质" },
] as const;
const changeNames: Record<string, string> = Object.fromEntries(
  [...changeOptions, ...structuralOptions].map((o) => [o.value, o.label]),
);
export const changeLabel = (value: unknown) =>
  changeNames[text(value, "")] || text(value, "");
export const changeList = (value: unknown) =>
  Array.isArray(value) && value.length
    ? value.map(changeLabel).filter(Boolean).join("、")
    : "未指定";

const missingInputs: Record<string, string> = {
  dimensions: "产品尺寸",
  material: "产品材质",
  structure: "产品结构",
  "verified product facts": "已核实的产品资料",
  "product external use permission": "产品资料的对外使用许可",
  "real product reference image": "真实产品参考图",
  "verified externally permitted facts for every comparison SKU":
    "每个对比产品的已核实、可对外资料",
  "structural/material/dimension changes require an explicit concept plan":
    "修改结构、材质或尺寸必须选择概念方案",
  "reference asset use authorization": "参考素材的使用授权",
  "authorized Logo": "已授权的品牌标识",
  "references from at least two SKUs": "至少两个产品的参考图",
  "confirmed customization capability": "已确认的定制能力",
  "Product facts": "产品资料",
  "Authorized reference assets": "已授权的参考素材",
  "Human plan approval": "人工批准计划",
};
export const missingInputList = (value: unknown) =>
  (Array.isArray(value) ? value : [])
    .map((item) => missingInputs[text(item, "")] || text(item, ""))
    .join("、");

const strategies: Record<string, string> = {
  reuse: "直接使用真实素材",
  compose: "保留商品主体，只合成获准修改的部分",
  edit: "以真实素材为参考进行修改",
  generate: "生成概念图，不代表实物",
  blocked: "资料不足，暂不能制作",
  "reuse/compose": "优先使用真实素材，只合成获准修改的部分",
  "compose/edit": "以真实素材为基础，修改获准的部分",
};
export const strategyLabel = (value: unknown) =>
  lookup(strategies, value, "其他制作方式") || "待确定";

const factStatuses: Record<string, string> = {
  unverified: "未核实",
  supplier_claim: "供应商声明",
  verified: "已核实",
  concept: "概念",
};
export const factStatusLabel = (value: unknown) =>
  lookup(factStatuses, value, "状态待确认") || "状态待确认";

const assetKinds: Record<string, string> = {
  product: "真实产品图",
  logo: "品牌标识",
  packaging: "包装素材",
};
export const assetKindLabel = (value: unknown) =>
  lookup(assetKinds, value, "其他素材") || "素材";

const qaChecks: Record<string, Record<string, string>> = {
  file_integrity: { pass: "文件完好" },
  dimensions: { pass: "尺寸符合要求" },
  image_content: { pass: "画面内容不为空" },
  concept_identity: { warn: "概念图：请确认画面上有“概念 / 待审核”标识" },
  vision_review: { warn: "产品外观尚未自动核验，请人工对照实物或原图" },
};
const qaChecksFailed: Record<string, string> = {
  file_integrity: "文件损坏或无法读取",
  dimensions: "尺寸不符合要求",
  image_content: "画面内容异常",
  concept_identity: "概念图标识有问题",
  vision_review: "产品外观检查未通过",
};
/** Plain QA conclusion; the raw record stays available behind technical details. */
export function qaSummary(raw: unknown) {
  const qa = row(raw);
  const status = text(qa.status, "").toLowerCase();
  const isFixture = row(qa.report).mode === "mock_fixture_not_visual_qa";
  const checks = rows(qa.checks).map((check) => {
    const name = text(check.name, "");
    const state = text(check.status, "").toLowerCase();
    return {
      name,
      state,
      label:
        qaChecks[name]?.[state] ||
        (state === "pass"
          ? qaChecksFailed[name]
            ? "检查通过"
            : "其他检查通过"
          : qaChecksFailed[name] || "有一项检查需要确认"),
    };
  });
  const passed = checks.filter((c) => c.state === "pass").map((c) => c.label);
  const issues = checks.filter((c) => c.state !== "pass").map((c) => c.label);
  const headline = !status
    ? "尚无自动检查结果"
    : isFixture
      ? "模拟测试图片，未做真实画面检查"
      : ["block", "blocked", "failed", "fail"].includes(status)
        ? "自动检查未通过，不能使用"
        : issues.length || status === "warn"
          ? "有待人工确认项"
          : "自动检查通过";
  return { headline, passed, issues, needsAttention: status !== "passed" };
}
