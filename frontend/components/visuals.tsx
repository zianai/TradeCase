"use client";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, download, id, mutate, row, rows, Row, text } from "@/lib/api";
import {
  assetKindLabel,
  changeList,
  changeOptions,
  factStatusLabel,
  missingInputList,
  qaSummary,
  strategyLabel,
  structuralOptions,
} from "@/lib/business-labels";

const intents: Record<string, string> = {
  product_comparison: "多款产品对比",
  oem_preview: "OEM 定制预览",
  packaging_preview: "包装预览",
  spec_illustration: "规格示意",
  odm_concept: "ODM 概念探索",
  buyer_presentation: "买家视觉提案",
};
const statuses: Record<string, string> = {
  suggested: "建议",
  needs_input: "需要补充资料",
  draft: "计划草稿",
  awaiting_plan_approval: "等待计划审批",
  queued: "已排队",
  running: "制作中",
  qa_pending: "等待自动检查",
  awaiting_asset_review: "等待图片业务审核",
  awaiting_review: "待图片审核",
  not_recommended: "无需出图",
  approved: "已批准",
  rejected: "已拒绝",
  attached_to_proposal: "已加入提案",
  blocked: "已阻断",
  failed: "失败",
  cancelled: "已取消",
  reconciling: "正在核对远端结果",
};
function QaConclusion({ qa }: { qa: unknown }) {
  const summary = qaSummary(qa);
  return (
    <div className="qa-conclusion">
      <p>{summary.headline}</p>
      {summary.passed.length > 0 && (
        <small>已检查：{summary.passed.join("、")}</small>
      )}
      {summary.issues.length > 0 && (
        <ul>
          {summary.issues.map((issue) => (
            <li key={issue}>{issue}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
const humanList = (s: unknown) =>
  Array.isArray(s) ? s.map((v) => text(v)).join("、") : text(s);
const label = (s: unknown) => statuses[text(s)] || text(s);
const split = (s: string) =>
  s
    .split(/[,，\n]/)
    .map((v) => v.trim())
    .filter(Boolean);

function AssetImage({ path, alt }: { path: string; alt: string }) {
  const [url, setUrl] = useState(""),
    [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl = "";
    setUrl("");
    setError("");
    if (
      !/^\/api\/visual-(?:source-)?assets\/[a-zA-Z0-9_-]+\/content$/.test(path)
    ) {
      setError("素材预览地址无效");
      return;
    }
    void fetch(path, {
      headers: {
        Authorization:
          "Bearer " + (sessionStorage.getItem("tradecase-token") || ""),
      },
      signal: controller.signal,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("无法读取图片，请核对访问权限");
        if (
          !/^image\/(png|jpeg|webp)$/.test(
            response.headers.get("content-type") || "",
          )
        )
          throw new Error("图片类型不受支持");
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError((e as Error).message);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);
  if (error) return <p className="muted">{error}</p>;
  return url ? (
    <img className="visual-image" src={url} alt={alt} />
  ) : (
    <p className="muted">正在读取图片…</p>
  );
}

export function VisualRecommendations({
  caseId,
  onOpen,
}: {
  caseId: string;
  onOpen: () => void;
}) {
  const [suggestions, setSuggestions] = useState<Row[]>([]);
  useEffect(() => {
    let active = true;
    void api(`/cases/${encodeURIComponent(caseId)}/visuals`)
      .then((v) => {
        if (active)
          setSuggestions(
            rows(row(v).suggestions).filter(
              (s) => text(s.status) !== "not_recommended",
            ),
          );
      })
      .catch(() => {
        if (active) setSuggestions([]);
      });
    return () => {
      active = false;
    };
  }, [caseId]);
  if (!suggestions.length) return null;
  return (
    <section className="visual-recommendation" aria-label="视觉建议">
      <div>
        <span className="eyebrow">建议</span>
        <h2>可选的产品视觉方案</h2>
        <p>{text(suggestions[0].reason)}</p>
      </div>
      <button className="button secondary compact" onClick={onOpen}>
        查看视觉建议
      </button>
    </section>
  );
}

export default function VisualWorkspace({
  caseId,
  caseVersion,
  canReview,
  onChange,
}: {
  caseId: string;
  caseVersion: number;
  canReview: boolean;
  onChange: () => void;
}) {
  const prefix = `/cases/${encodeURIComponent(caseId)}/visuals`;
  const [data, setData] = useState<Row>({}),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [loaded, setLoaded] = useState(false);
  const [productId, setProductId] = useState(""),
    [intent, setIntent] = useState("oem_preview"),
    [requirement, setRequirement] = useState("");
  const [selectedSources, setSelectedSources] = useState<string[]>([]),
    [revisionTask, setRevisionTask] = useState<Row | null>(null),
    [selectedAssets, setSelectedAssets] = useState<string[]>([]);
  const [comments, setComments] = useState<Record<string, string>>({}),
    [authorization, setAuthorization] = useState<Record<string, boolean>>({}),
    [preview, setPreview] = useState(false);
  const [concept, setConcept] = useState(false),
    [allowed, setAllowed] = useState<string[]>([]),
    [preserved, setPreserved] = useState<string[]>([
      "product_structure",
      "dimensions",
    ]),
    [otherPreserve, setOtherPreserve] = useState("");
  const conceptPlan = intent === "odm_concept" || concept;
  const refresh = useCallback(async () => {
    try {
      setData(row(await api(prefix)));
      setLoaded(true);
    } catch (e) {
      setError((e as Error).message);
      setLoaded(true);
    }
  }, [prefix]);
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 5000);
    return () => clearInterval(timer);
  }, [refresh]);
  const action = async (path: string, body: unknown, message: string) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await mutate(path, body);
      await refresh();
      setNotice(message);
      onChange();
      return result;
    } catch (e) {
      setError((e as Error).message);
      return null;
    } finally {
      setBusy(false);
    }
  };
  const products = rows(data.products),
    tasks = rows(data.tasks),
    sources = rows(data.source_assets);
  const product = products.find((p) => id(p) === productId);
  const importProduct = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const result = await action(
      prefix + "/products",
      {
        sku: f.get("sku"),
        name: f.get("name"),
        dimensions: f.get("dimensions"),
        material: f.get("material"),
        colors: split(String(f.get("colors"))),
        structure: split(String(f.get("structure"))),
        customization: split(String(f.get("customization"))),
        source: f.get("source"),
        fact_status: f.get("fact_status"),
        expected_version: products.find(
          (p) => text(p.sku) === String(f.get("sku")),
        )?.version,
        external_use: f.get("external_use") === "on",
      },
      "产品资料已保存；事实状态保持你的标注。",
    );
    if (result) {
      setProductId(id(row(result)));
      setSelectedSources([]);
    }
  };
  const uploadSource = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget,
      f = new FormData(form),
      file = f.get("file");
    if (
      !(file instanceof File) ||
      file.size === 0 ||
      file.size > 2 * 1024 * 1024
    ) {
      setError("请选择不超过 2 MiB 的 PNG、JPEG 或 WebP 文件。");
      return;
    }
    f.set("authorized", String(f.get("authorized") === "on"));
    f.set("external_use", String(f.get("external_use") === "on"));
    setBusy(true);
    setError("");
    try {
      await api(prefix + "/assets", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: f,
      });
      await refresh();
      setNotice("参考素材已保存，授权信息随素材记录。");
      form.reset();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const createPlan = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const finalAllowed = allowed.filter(
      (v) => conceptPlan || changeOptions.some((o) => o.value === v),
    );
    const payload = {
      product_id: productId,
      intent,
      requirement,
      source_asset_ids: selectedSources,
      allowed_changes: finalAllowed,
      preserve: [
        ...preserved.filter((v) => !finalAllowed.includes(v)),
        ...split(otherPreserve),
      ],
      variants: Number(f.get("variants")),
      budget_usd: Number(f.get("budget_usd")),
      concept: conceptPlan,
      evidence_refs: [],
    };
    const result = await action(
      revisionTask
        ? `/visual-tasks/${id(revisionTask)}/revisions`
        : prefix + "/tasks",
      revisionTask ? { version: revisionTask.version, plan: payload } : payload,
      "计划已保存。请核对计划后单独批准执行。",
    );
    if (result) {
      setRevisionTask(null);
      setPreview(false);
    }
  };
  if (!loaded) return <div className="loading">正在读取视觉任务…</div>;
  const toggle = (
    setter: (update: (old: string[]) => string[]) => void,
    value: string,
    on: boolean,
  ) => setter((old) => (on ? [...old, value] : old.filter((v) => v !== value)));
  const productName = (candidate: Row | undefined) => {
    if (!candidate) return "未选择产品";
    const name = text(row(candidate.data).name, "");
    return name ? `${text(candidate.sku)} · ${name}` : text(candidate.sku);
  };
  return (
    <div className="visual-workspace">
      <header className="panel content-panel">
        <span className="eyebrow">视觉任务</span>
        <h2>产品图片与买家提案</h2>
        <p>
          可选步骤。先批准制作计划，再逐张审核图片；图片用于沟通展示，不能当作产品事实的证据。
        </p>
        <p className="visual-mode">
          {data.engine_mode === "mock"
            ? "模拟制作 · 使用测试素材，不是真实生成的图片"
            : data.engine_mode === "http"
              ? "图片制作服务已连接 · 实际结果以任务回执为准"
              : "图片制作服务未连接 · 可先整理资料和计划，询盘流程不受影响"}
        </p>
      </header>
      {error && (
        <div className="notice danger" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <p className="visual-notice" role="status">
          {notice}
        </p>
      )}
      <section className="panel content-panel">
        <div className="panel-heading">
          <h2>任务、计划与结果审核</h2>
          <button className="text-button" onClick={() => void refresh()}>
            刷新状态
          </button>
        </div>
        {!tasks.length && (
          <p className="muted">尚未创建视觉任务，原业务流程可以照常完成。</p>
        )}
        {tasks.map((t) => {
          const plan = row(t.plan),
            p = row(plan.data),
            assets = rows(t.assets),
            tid = id(t);
          return (
            <article className="visual-task" key={tid}>
              <div className="panel-heading">
                <div>
                  <h3>
                    {intents[text(t.intent)] || "视觉任务"} ·{" "}
                    {text(
                      row(p.product).name,
                      text(row(p.product).sku, "产品待确认"),
                    )}
                  </h3>
                  <span className="muted">任务第 {text(t.version)} 版</span>
                </div>
                <strong className="visual-state">{label(t.status)}</strong>
              </div>
              {Boolean(row(t.data).truth_stale) && (
                <p role="alert">
                  产品资料已更新；旧计划和图片需要重新评估，请创建修订计划。
                </p>
              )}
              {Array.isArray(p.missing_inputs) &&
                p.missing_inputs.length > 0 && (
                  <p role="status">
                    需补充：{missingInputList(p.missing_inputs)}
                  </p>
                )}
              {Boolean(row(t.data).error) && (
                <p role="status">{text(row(t.data).error)}</p>
              )}
              <dl className="visual-facts">
                <div>
                  <dt>买家需求</dt>
                  <dd>{text(p.requirement ?? t.requirement)}</dd>
                </div>
                <div>
                  <dt>产品资料</dt>
                  <dd>
                    {text(row(p.product).sku, "产品")} · 资料第{" "}
                    {text(p.product_version, "—")} 版 ·{" "}
                    {factStatusLabel(row(p.product).fact_status)}
                  </dd>
                </div>
                <div>
                  <dt>可以修改</dt>
                  <dd>{changeList(p.allowed_changes)}</dd>
                </div>
                <div>
                  <dt>必须保持</dt>
                  <dd>{changeList(p.preserve)}</dd>
                </div>
                <div>
                  <dt>数量 / 预算上限（尚未报价）</dt>
                  <dd>
                    {text(p.variants)} 张 / ${text(p.budget_usd)}
                  </dd>
                </div>
                <div>
                  <dt>交付性质</dt>
                  <dd>
                    {p.output_is_concept || p.concept
                      ? "输出为概念 / 定制预览，仅供沟通，不证明量产或认证"
                      : "保留产品主体的预览图 · 仍需逐张审核"}
                  </dd>
                </div>
              </dl>
              <details className="tech-details">
                <summary>技术追溯信息（完整计划与版本）</summary>
                <p className="mono">
                  任务 {tid} · 产品资料快照 {text(plan.truth_snapshot_id)}
                </p>
                <pre className="visual-json">{JSON.stringify(t, null, 2)}</pre>
              </details>
              {text(t.status) === "awaiting_plan_approval" && (
                <div className="visual-approval">
                  <p>
                    批准后，图片制作服务将按此计划执行，费用不超过上述上限。批准计划不等于批准图片，图片还要逐张审核。
                  </p>
                  <label className="visual-check">
                    <input
                      type="checkbox"
                      checked={authorization[tid + text(plan.hash)] || false}
                      onChange={(e) =>
                        setAuthorization((old) => ({
                          ...old,
                          [tid + text(plan.hash)]: e.target.checked,
                        }))
                      }
                    />
                    我已核对产品、参考素材、修改范围及预算，并授权传递必要产品资料
                  </label>
                  <button
                    className="button"
                    disabled={
                      busy ||
                      !canReview ||
                      !authorization[tid + text(plan.hash)] ||
                      Boolean(row(t.data).truth_stale)
                    }
                    onClick={() =>
                      void action(
                        `/visual-tasks/${tid}/approve-plan`,
                        {
                          version: t.version,
                          plan_hash: plan.hash,
                          data_processing_authorized: true,
                        },
                        "计划已批准，视觉任务已进入执行队列。",
                      )
                    }
                  >
                    批准此版本计划并排队
                  </button>
                </div>
              )}
              <div className="button-row">
                {["queued", "running", "reconciling", "qa_pending"].includes(
                  text(t.status),
                ) && (
                  <button
                    className="button secondary compact"
                    disabled={busy}
                    onClick={() =>
                      void action(
                        `/visual-tasks/${tid}/sync`,
                        { version: t.version },
                        "已核对远端任务状态。",
                      )
                    }
                  >
                    核对执行状态
                  </button>
                )}
                {!["cancelled", "approved", "attached_to_proposal"].includes(
                  text(t.status),
                ) && (
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() =>
                      void action(
                        `/visual-tasks/${tid}/cancel`,
                        { version: t.version },
                        "已记录取消请求。远端执行状态仍以回执为准。",
                      )
                    }
                  >
                    取消任务
                  </button>
                )}
                {[
                  "rejected",
                  "needs_input",
                  "failed",
                  "blocked",
                  "cancelled",
                  "approved",
                  "awaiting_plan_approval",
                  "awaiting_asset_review",
                ].includes(text(t.status)) && (
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() => {
                      setRevisionTask(t);
                      setProductId(text(t.product_id, ""));
                      setIntent(text(t.intent));
                      setConcept(Boolean(p.concept));
                      setAllowed(
                        Array.isArray(p.allowed_changes)
                          ? p.allowed_changes.map(String)
                          : [],
                      );
                      {
                        const kept = Array.isArray(p.preserve)
                          ? p.preserve.map(String)
                          : [];
                        const known = structuralOptions.map(
                          (o) => o.value as string,
                        );
                        setPreserved(kept.filter((v) => known.includes(v)));
                        setOtherPreserve(
                          kept.filter((v) => !known.includes(v)).join(", "),
                        );
                      }
                      setRequirement(text(p.requirement ?? t.requirement, ""));
                      setSelectedSources(
                        Array.isArray(p.source_asset_ids)
                          ? (p.source_asset_ids as string[])
                          : [],
                      );
                      setPreview(true);
                      document
                        .getElementById("visual-plan-form")
                        ?.scrollIntoView({ behavior: "smooth" });
                    }}
                  >
                    创建修订计划
                  </button>
                )}
              </div>
              {assets.length > 0 && (
                <>
                  <h4>图片业务审核</h4>
                  <p className="muted">
                    对照原始素材，检查产品编号、授权、结构、参数和文字声明。制作完成或自动检查通过，都不代表业务已批准。
                  </p>
                  <div className="visual-gallery">
                    {assets.map((a) => (
                      <figure key={id(a)}>
                        <AssetImage
                          path={text(
                            a.content_url,
                            `/api/visual-assets/${id(a)}/content`,
                          )}
                          alt={`${intents[text(t.intent)]}候选图`}
                        />
                        <figcaption>
                          <strong>{label(a.status)}</strong>
                          <QaConclusion qa={a.qa} />
                          <details className="tech-details">
                            <summary>技术追溯信息</summary>
                            <p className="mono">{text(a.content_hash)}</p>
                            <pre className="visual-json">
                              {JSON.stringify(a.qa, null, 2)}
                            </pre>
                          </details>
                        </figcaption>
                        {text(a.status) === "approved" ? (
                          <label className="visual-check">
                            <input
                              type="checkbox"
                              disabled={
                                text(a.plan_id) !== text(plan.id) ||
                                Boolean(row(t.data).truth_stale)
                              }
                              checked={selectedAssets.includes(id(a))}
                              onChange={(e) =>
                                setSelectedAssets((old) =>
                                  e.target.checked
                                    ? [...old, id(a)]
                                    : old.filter((v) => v !== id(a)),
                                )
                              }
                            />
                            选入买家提案
                          </label>
                        ) : (
                          <>
                            <label>
                              图片审核意见
                              <textarea
                                value={comments[id(a)] || ""}
                                onChange={(e) =>
                                  setComments((old) => ({
                                    ...old,
                                    [id(a)]: e.target.value,
                                  }))
                                }
                                rows={2}
                              />
                            </label>
                            <div className="button-row">
                              {["approve", "reject"].map((decision) => (
                                <button
                                  className={
                                    decision === "approve"
                                      ? "button secondary compact"
                                      : "text-button"
                                  }
                                  key={decision}
                                  disabled={
                                    busy ||
                                    !canReview ||
                                    ![
                                      "awaiting_asset_review",
                                      "approved",
                                      "rejected",
                                    ].includes(text(t.status)) ||
                                    text(a.plan_id) !== text(plan.id)
                                  }
                                  onClick={() =>
                                    void action(
                                      `/visual-tasks/${tid}/reviews`,
                                      {
                                        version: t.version,
                                        asset_id: id(a),
                                        asset_hash: a.content_hash,
                                        decision,
                                        comment: comments[id(a)] || "",
                                      },
                                      decision === "approve"
                                        ? "图片业务审核已批准。"
                                        : "图片已拒绝；可创建修订计划。",
                                    )
                                  }
                                >
                                  {decision === "approve"
                                    ? "批准图片"
                                    : "拒绝图片"}
                                </button>
                              ))}
                            </div>
                          </>
                        )}
                      </figure>
                    ))}
                  </div>
                  <button
                    className="button"
                    disabled={
                      busy ||
                      !canReview ||
                      !assets.some(
                        (a) =>
                          text(a.status) === "approved" &&
                          text(a.plan_id) === text(plan.id) &&
                          !row(t.data).truth_stale &&
                          selectedAssets.includes(id(a)),
                      )
                    }
                    onClick={() =>
                      void action(
                        `/visual-tasks/${tid}/attach`,
                        {
                          version: t.version,
                          asset_ids: assets
                            .filter(
                              (a) =>
                                text(a.status) === "approved" &&
                                text(a.plan_id) === text(plan.id) &&
                                !row(t.data).truth_stale &&
                                selectedAssets.includes(id(a)),
                            )
                            .map(id),
                          case_version: caseVersion,
                          update_draft: true,
                        },
                        "已保存买家提案和报告修订，并更新跟进草稿；草稿需重新审核，邮件未发送。",
                      )
                    }
                  >
                    将选中批准素材加入提案与跟进草稿
                  </button>
                </>
              )}
            </article>
          );
        })}
      </section>
      {rows(data.proposals).length > 0 && (
        <section className="panel content-panel">
          <h2>已审核的买家提案</h2>
          {rows(data.proposals).map((p) => (
            <article className="visual-row" key={id(p)}>
              <div>
                <h3>{text(row(row(p.data).product).name, "买家提案")}</h3>
                <p>{text(row(p.data).requirement)}</p>
                <dl className="visual-facts">
                  <div>
                    <dt>产品编号</dt>
                    <dd>{text(row(row(p.data).product).sku)}</dd>
                  </div>
                  <div>
                    <dt>已批准素材</dt>
                    <dd>{rows(row(p.data).assets).length} 张</dd>
                  </div>
                  <div>
                    <dt>已记录尺寸 / 材质</dt>
                    <dd>
                      {text(row(row(p.data).product).dimensions)} /{" "}
                      {text(row(row(p.data).product).material)}
                    </dd>
                  </div>
                  <div>
                    <dt>方案性质</dt>
                    <dd>
                      {row(p.data).concept
                        ? "概念方案，制造可行性待确认"
                        : "已审核预览，非产品实拍证明"}
                    </dd>
                  </div>
                </dl>
                {Boolean(row(p.data).mock) && (
                  <p className="visual-mode">
                    模拟验收素材，不代表真实生成结果。
                  </p>
                )}
                <p>{text(row(p.data).disclaimer)}</p>
                <p>需要买家确认：{humanList(row(p.data).buyer_questions)}</p>
                <p>
                  需要供应商确认：{humanList(row(p.data).supplier_questions)}
                </p>
                <details className="tech-details">
                  <summary>技术追溯信息（提案原始记录）</summary>
                  <pre className="visual-json">
                    {JSON.stringify(p, null, 2)}
                  </pre>
                </details>
              </div>
              <button
                className="button secondary compact"
                onClick={() =>
                  void download(
                    `/visual-proposals/${id(p)}/export`,
                    `buyer-proposal-${id(p)}.zip`,
                  ).catch((e) => setError((e as Error).message))
                }
              >
                下载提案素材包
              </button>
            </article>
          ))}
        </section>
      )}
      <section className="panel content-panel" aria-label="视觉需求建议">
        <div className="panel-heading">
          <h2>视觉需求建议</h2>
          <button
            className="text-button"
            onClick={() => {
              setPreview(true);
              document
                .getElementById("visual-plan-form")
                ?.scrollIntoView({ behavior: "smooth" });
            }}
          >
            手动创建视觉任务
          </button>
        </div>
        {rows(data.suggestions).length ? (
          rows(data.suggestions).map((s, i) => (
            <article className="visual-row" key={i}>
              <div>
                <h3>{intents[text(s.intent)] || "当前询盘无需出图"}</h3>
                <p>{text(s.reason)}</p>
                {Boolean(s.requirement_quote) && (
                  <blockquote>{text(s.requirement_quote)}</blockquote>
                )}
                <p className="muted">
                  制作方式：{strategyLabel(s.strategy)} · {label(s.status)}
                </p>
                {Array.isArray(s.missing_inputs) &&
                  s.missing_inputs.length > 0 && (
                    <p>需补充：{missingInputList(s.missing_inputs)}</p>
                  )}
              </div>
              {text(s.status) !== "not_recommended" && (
                <button
                  className="button secondary compact"
                  onClick={() => {
                    setIntent(text(s.intent));
                    setRequirement(text(s.requirement_quote, ""));
                    setPreview(true);
                  }}
                >
                  准备此方案
                </button>
              )}
            </article>
          ))
        ) : (
          <p className="muted">
            没有必须生成的视觉任务；你可以继续原有草稿审核流程。
          </p>
        )}
      </section>
      <section className="panel content-panel">
        <h2>产品资料与授权素材</h2>
        <p className="muted">
          填写已知资料；未知字段可留空。系统会阻止资料或授权不足的真实产品预览。
        </p>
        <details>
          <summary>新增 / 更新产品资料</summary>
          <form className="visual-form" onSubmit={importProduct}>
            <label>
              SKU / 产品编号
              <input name="sku" required maxLength={100} />
            </label>
            <label>
              产品名称
              <input name="name" required maxLength={200} />
            </label>
            <label>
              尺寸
              <input name="dimensions" placeholder="未确认可留空" />
            </label>
            <label>
              材质
              <input name="material" placeholder="未确认可留空" />
            </label>
            <label>
              可选颜色（逗号分隔）
              <input name="colors" />
            </label>
            <label>
              结构特征（逗号分隔）
              <input name="structure" />
            </label>
            <label>
              已确认定制能力（逗号分隔）
              <input name="customization" />
            </label>
            <label>
              事实状态
              <select
                aria-label="事实状态"
                name="fact_status"
                defaultValue="unverified"
              >
                <option value="unverified">未核实</option>
                <option value="supplier_claim">供应商声明</option>
                <option value="verified">已核实</option>
                <option value="concept">概念</option>
              </select>
            </label>
            <label className="visual-wide">
              事实来源与核验依据
              <textarea name="source" required rows={2} />
            </label>
            <label className="visual-check visual-wide">
              <input name="external_use" type="checkbox" />
              这些产品资料允许用于对外提案
            </label>
            <button className="button secondary compact" disabled={busy}>
              保存产品资料
            </button>
          </form>
        </details>
        {products.map((p) => (
          <div className="visual-row" key={id(p)}>
            <div>
              <strong>{productName(p)}</strong>
              <p className="muted">
                资料第 {text(p.version)} 版 ·{" "}
                {factStatusLabel(row(p.data).fact_status)} ·{" "}
                {text(row(p.data).source)}
              </p>
            </div>
            <button
              className="text-button"
              onClick={() => {
                setProductId(id(p));
                setSelectedSources([]);
                setPreview(true);
              }}
            >
              用于新计划
            </button>
          </div>
        ))}
        <details>
          <summary>上传真实产品图 / 已授权品牌标识 / 包装素材</summary>
          <form className="visual-form" onSubmit={uploadSource}>
            <label>
              关联产品
              <select aria-label="关联产品" name="product_id" required>
                <option value="">请选择产品</option>
                {products.map((p) => (
                  <option key={id(p)} value={id(p)}>
                    {text(p.sku)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              素材类型
              <select aria-label="素材类型" name="kind">
                <option value="product">真实产品图</option>
                <option value="logo">品牌标识</option>
                <option value="packaging">包装素材</option>
              </select>
            </label>
            <label className="visual-wide">
              图片文件（PNG / JPEG / WebP，最大 2 MiB）
              <input
                name="file"
                type="file"
                accept="image/png,image/jpeg,image/webp"
                required
              />
            </label>
            <label className="visual-wide">
              素材来源与授权说明
              <input name="source" required />
            </label>
            <label className="visual-check">
              <input type="checkbox" name="authorized" />
              已取得使用授权
            </label>
            <label className="visual-check">
              <input type="checkbox" name="external_use" />
              允许对外使用
            </label>
            <button className="button secondary compact" disabled={busy}>
              保存参考素材
            </button>
          </form>
        </details>
        {sources.length > 0 && (
          <details>
            <summary>查看原始素材（{sources.length}）</summary>
            <div className="visual-gallery">
              {sources.map((a) => (
                <figure key={id(a)}>
                  <AssetImage
                    path={text(
                      a.content_url,
                      `/api/visual-assets/${id(a)}/content`,
                    )}
                    alt={`参考素材 ${assetKindLabel(a.kind)}`}
                  />
                  <figcaption>
                    {assetKindLabel(a.kind)} ·{" "}
                    {a.authorized ? "已授权" : "未授权"} ·{" "}
                    {a.external_use ? "允许外用" : "不可外用"}
                    <details className="tech-details">
                      <summary>技术追溯信息</summary>
                      <small className="mono">{text(a.content_hash)}</small>
                    </details>
                  </figcaption>
                </figure>
              ))}
            </div>
          </details>
        )}
      </section>
      <section className="panel content-panel" id="visual-plan-form">
        <h2>{revisionTask ? "创建修订计划" : "准备生成计划"}</h2>
        <p>保存计划不产生费用。计划会记录当前这一版产品资料和所选素材。</p>
        <details
          open={preview}
          onToggle={(e) => setPreview(e.currentTarget.open)}
        >
          <summary>填写视觉需求与执行约束</summary>
          <form className="visual-form" onSubmit={createPlan}>
            <label>
              使用产品
              <select
                aria-label="使用产品"
                required
                value={productId}
                onChange={(e) => {
                  setProductId(e.target.value);
                  setSelectedSources([]);
                }}
              >
                <option value="">请选择产品</option>
                {products.map((p) => (
                  <option key={id(p)} value={id(p)}>
                    {productName(p)} · 资料第 {text(p.version)} 版
                  </option>
                ))}
              </select>
            </label>
            <label>
              视觉用途
              <select
                aria-label="视觉用途"
                value={intent}
                onChange={(e) => setIntent(e.target.value)}
              >
                {Object.entries(intents).map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="visual-wide">
              对应的买家需求
              <textarea
                required
                value={requirement}
                onChange={(e) => setRequirement(e.target.value)}
                rows={2}
                maxLength={2000}
                placeholder="只描述相关产品视觉需求，不填写买家邮箱或个人联系方式"
              />
            </label>
            <fieldset className="visual-wide visual-options">
              <legend>可以修改的内容</legend>
              {[
                ...changeOptions,
                ...(conceptPlan ? structuralOptions : []),
              ].map((option) => (
                <label className="visual-check" key={option.value}>
                  <input
                    type="checkbox"
                    checked={allowed.includes(option.value)}
                    onChange={(e) =>
                      toggle(setAllowed, option.value, e.target.checked)
                    }
                  />
                  {option.label}
                </label>
              ))}
              {!conceptPlan && (
                <p className="muted">
                  修改结构、尺寸或材质需要勾选下方的“仅作为概念方案”。
                </p>
              )}
            </fieldset>
            <fieldset className="visual-wide visual-options">
              <legend>必须保持不变</legend>
              {structuralOptions.map((option) => (
                <label className="visual-check" key={option.value}>
                  <input
                    type="checkbox"
                    disabled={allowed.includes(option.value) && conceptPlan}
                    checked={
                      preserved.includes(option.value) &&
                      !(allowed.includes(option.value) && conceptPlan)
                    }
                    onChange={(e) =>
                      toggle(setPreserved, option.value, e.target.checked)
                    }
                  />
                  {option.label}
                </label>
              ))}
              <label className="visual-wide">
                其他必须保持的内容（可选，用逗号分隔）
                <input
                  value={otherPreserve}
                  onChange={(e) => setOtherPreserve(e.target.value)}
                />
              </label>
            </fieldset>
            <label>
              图片数量
              <input
                name="variants"
                type="number"
                min={1}
                max={8}
                defaultValue={1}
                required
              />
            </label>
            <label>
              预算上限（美元）
              <input
                name="budget_usd"
                type="number"
                min={0.01}
                max={100}
                step={0.01}
                defaultValue={1}
                required
              />
            </label>
            <fieldset className="visual-wide">
              <legend>选择参考素材</legend>
              {sources
                .filter(
                  (a) =>
                    intent === "product_comparison" ||
                    text(a.product_id) === productId,
                )
                .map((a) => (
                  <label className="visual-check" key={id(a)}>
                    <input
                      type="checkbox"
                      checked={selectedSources.includes(id(a))}
                      onChange={(e) =>
                        setSelectedSources((old) =>
                          e.target.checked
                            ? [...old, id(a)]
                            : old.filter((v) => v !== id(a)),
                        )
                      }
                    />
                    {text(
                      products.find(
                        (product) => id(product) === text(a.product_id),
                      )?.sku,
                    )}{" "}
                    · {assetKindLabel(a.kind)} · {text(a.source, "来源未记录")}{" "}
                    ·{" "}
                    {a.authorized && a.external_use ? "已授权外用" : "授权不足"}
                  </label>
                ))}
              {!sources.some((a) => text(a.product_id) === productId) && (
                <p className="muted">此产品尚无参考素材。</p>
              )}
            </fieldset>
            <label className="visual-check visual-wide">
              <input
                name="concept"
                type="checkbox"
                checked={intent === "odm_concept" || concept}
                onChange={(e) => setConcept(e.target.checked)}
                disabled={intent === "odm_concept"}
              />
              仅作为概念方案，不宣称已量产或已验证
            </label>
            {product && (
              <p className="muted visual-wide">
                当前产品：{productName(product)} · 资料状态：
                {factStatusLabel(row(product.data).fact_status)}
              </p>
            )}
            <button className="button" disabled={busy || !productId}>
              保存并预览计划
            </button>
            {revisionTask && (
              <button
                type="button"
                className="text-button"
                onClick={() => setRevisionTask(null)}
              >
                取消修订
              </button>
            )}
          </form>
        </details>
      </section>
    </div>
  );
}
