"use client";

import {
  FormEvent,
  ReactNode,
  ReactElement,
  cloneElement,
  isValidElement,
  useId,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import ModalOverlay from "./modal-overlay";
import { applyDraftTone, DraftTone } from "@/lib/draft-tone";
import { usePathname, useRouter } from "next/navigation";
import {
  api,
  date,
  download,
  id,
  list,
  mutate,
  row,
  rows,
  Row,
  streamCaseEvents,
  text,
} from "@/lib/api";

const labels: Record<string, string> = {
  NEW: "新询盘",
  RESEARCHING: "调查中",
  NEEDS_INPUT: "待补充",
  NEEDS_REVIEW: "待人工审核",
  READY_TO_FOLLOW_UP: "可跟进",
  FOLLOW_UP_IN_PROGRESS: "跟进中",
  CLOSED: "已关闭",
  FAILED: "失败",
  PENDING: "待处理",
  READY: "就绪",
  RUNNING: "执行中",
  WAITING_HUMAN: "等待审核",
  SUCCEEDED: "已完成",
  CANCELLED: "已取消",
  BLOCKED: "已阻断",
  APPROVED: "已批准",
  REJECTED: "已拒绝",
  COMPLETE: "已完成",
  COMPLETED: "已完成",
  DONE: "已完成",
  OPEN: "待跟进",
  PARTIAL: "部分完成",
  UNKNOWN: "未知",
  SUPPORTED: "有来源支持",
  VERIFIED: "已核实",
  INFERENCE: "推断",
  FACT: "事实",
  STALE: "版本失效",
  EXPIRED: "已过期",
  REQUEST_CHANGES: "要求修改",
  REQUEST_EVIDENCE: "要求补证据",
  INVALIDATED: "版本失效",
  NOT_CONNECTED: "未接入",
  CHANGES_REQUESTED: "要求修改 / 补证据",
  DISABLED: "未启用",
  AVAILABLE: "可用",
  UNAVAILABLE: "未接入",
  DELIVERY_UNCERTAIN: "回执待核对",
};
const statusText = (value: unknown) =>
  labels[text(value, "").toUpperCase()] || text(value);
function scopeLabel(value: unknown) {
  const key = text(value, "draft_review");
  return (
    (
      {
        draft_review: "草稿审核",
        mail_send: "邮件发送授权",
        crm_sync: "CRM 同步授权",
      } as Record<string, string>
    )[key] || key
  );
}
function Badge({ value }: { value: unknown }) {
  const status = text(value, "UNKNOWN").toUpperCase();
  const tone =
    /FAIL|REJECT|UNCERTAIN|BLOCK|EXPIRED|STALE|INVALIDATED|CONFLICT/.test(
      status,
    )
      ? "danger"
      : /REVIEW|HUMAN|PENDING|PARTIAL|INPUT|CHANGES|EVIDENCE/.test(status)
        ? "warn"
        : /SUCCEEDED|APPROVED|COMPLETE|FOLLOW_UP|VERIFIED|SUPPORTED|AVAILABLE/.test(
              status,
            ) && status !== "UNAVAILABLE"
          ? "good"
          : "neutral";
  return (
    <span className={`badge ${tone}`}>
      <i />
      {statusText(status)}
    </span>
  );
}
function Icon({ name }: { name: string }) {
  const paths: Record<string, ReactNode> = {
    dashboard: (
      <>
        <rect x="3" y="3" width="7" height="7" />
        <rect x="14" y="3" width="7" height="7" />
        <rect x="3" y="14" width="7" height="7" />
        <rect x="14" y="14" width="7" height="7" />
      </>
    ),
    cases: (
      <>
        <path d="M3 7h18v13H3zM3 7V4h7l2 3" />
        <path d="M8 12h8M8 16h5" />
      </>
    ),
    approvals: (
      <>
        <path d="M7 3h10v4h3v14H4V7h3zM7 7h10M8 14l3 3 5-6" />
      </>
    ),
    followups: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v6l4 2" />
      </>
    ),
    sources: (
      <>
        <path d="M3 5c4-2 6-2 9 0 3-2 5-2 9 0v15c-4-2-6-2-9 0-3-2-5-2-9 0zM12 5v15" />
      </>
    ),
    settings: (
      <>
        <circle cx="12" cy="12" r="4" />
        <path d="m10 2 4 0 1 3 3 1 3 3-2 3 1 4-3 3-4-1-3 3-4-2v-4l-3-3 2-4 4-1z" />
      </>
    ),
    plus: <path d="M12 5v14M5 12h14" />,
    arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
    refresh: (
      <>
        <path d="M20 7v5h-5M4 17v-5h5" />
        <path d="M6 7a7 7 0 0 1 12-2l2 3M4 16l2 3a7 7 0 0 0 12-2" />
      </>
    ),
    shield: (
      <>
        <path d="m12 2 9 4v6c0 5-6 9-9 10-3-1-9-5-9-10V6zM8 12l3 3 5-6" />
      </>
    ),
    close: <path d="m6 6 12 12M6 18 18 6" />,
  };
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name] || paths.cases}
    </svg>
  );
}
function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <span className="empty-line" />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
function ErrorBox({ error }: { error: string }) {
  return error ? (
    <div className="notice danger" role="alert">
      {error}
    </div>
  ) : null;
}
function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  const labelId = useId();
  const hintId = useId();
  const control = isValidElement(children)
    ? cloneElement(
        children as ReactElement<{
          "aria-labelledby"?: string;
          "aria-describedby"?: string;
        }>,
        {
          "aria-labelledby": labelId,
          "aria-describedby": hint ? hintId : undefined,
        },
      )
    : children;
  return (
    <label className="field">
      <span id={labelId}>{label}</span>
      {control}
      {hint && <small id={hintId}>{hint}</small>}
    </label>
  );
}
function Details({ value }: { value: unknown }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
}
function Note({ children }: { children: ReactNode }) {
  return <div className="notice">{children}</div>;
}

export default function Workbench() {
  const path = usePathname();
  const router = useRouter();
  const section = path.split("/")[1] || "dashboard";
  const caseId = section === "cases" ? path.split("/")[2] : undefined;
  const [cases, setCases] = useState<Row[]>([]),
    [approvals, setApprovals] = useState<Row[]>([]),
    [followups, setFollowups] = useState<Row[]>([]);
  const [settings, setSettings] = useState<Row>({}),
    [me, setMe] = useState<Row>({}),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const [showImport, setShowImport] = useState(false),
    [showConnection, setShowConnection] = useState(false),
    [token, setToken] = useState("");
  const [revision, setRevision] = useState(0),
    [notice, setNotice] = useState("");
  const refreshEpoch = useRef(0);
  const refresh = useCallback(async () => {
    const epoch = ++refreshEpoch.current;
    const credential = sessionStorage.getItem("tradecase-token");
    const stillCurrent = () =>
      epoch === refreshEpoch.current &&
      credential === sessionStorage.getItem("tradecase-token");
    setLoading(true);
    setError("");
    try {
      const [c, a, f, s, u] = await Promise.all([
        api("/cases"),
        api("/approvals"),
        api("/follow-ups"),
        api("/settings"),
        api("/me"),
      ]);
      if (!stillCurrent()) return;
      setCases(list(c));
      setApprovals(list(a));
      setFollowups(list(f));
      setSettings(row(s));
      setMe(row(u));
    } catch (e) {
      if (!stillCurrent()) return;
      setCases([]);
      setApprovals([]);
      setFollowups([]);
      setSettings({});
      setError((e as Error).message);
    } finally {
      if (stillCurrent()) setLoading(false);
    }
  }, []);
  useEffect(() => {
    setToken(sessionStorage.getItem("tradecase-token") || "");
    void refresh();
  }, [refresh, revision]);
  const changed = () => {
    setRevision((x) => x + 1);
  };
  const pending = approvals.filter((a) =>
    ["PENDING", "WAITING_HUMAN"].includes(text(a.status).toUpperCase()),
  );
  const openFollowups = followups.filter(
    (f) =>
      !["DONE", "COMPLETED", "CANCELLED"].includes(
        text(f.status).toUpperCase(),
      ),
  );
  const nav = [
    { key: "dashboard", label: "工作台", sub: "Overview", icon: "dashboard" },
    { key: "cases", label: "询盘案件", sub: "Cases", icon: "cases" },
    {
      key: "approvals",
      label: "决策收件箱",
      sub: "Decisions",
      icon: "approvals",
    },
    {
      key: "follow-ups",
      label: "跟进计划",
      sub: "Follow-ups",
      icon: "followups",
    },
    { key: "sources", label: "来源与知识", sub: "Sources", icon: "sources" },
    { key: "settings", label: "工作区设置", sub: "Settings", icon: "settings" },
  ];
  const current = nav.find((n) => n.key === section) || nav[0];
  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        跳到主要内容
      </a>
      <aside className="sidebar">
        <Link href="/" className="brand">
          <span className="brand-mark" aria-hidden="true">
            T<span>↗</span>
          </span>
          <span className="brand-text">
            TradeCase<small>询盘调查与转化</small>
          </span>
          <span className="sr-only brand-accessible">
            TradeCase 询盘调查与转化
          </span>
        </Link>
        <div className="workspace-label">
          <span className="workspace-dot" />
          业务工作区<span className="mono">01</span>
        </div>
        <nav aria-label="主导航">
          {nav.map((n) => (
            <Link
              key={n.key}
              href={n.key === "dashboard" ? "/" : "/" + n.key}
              className={section === n.key ? "nav-item active" : "nav-item"}
              aria-label={`${n.label} ${n.sub}`}
              title={n.label}
              aria-current={section === n.key ? "page" : undefined}
            >
              <Icon name={n.icon} />
              <span>
                {n.label}
                <small>{n.sub}</small>
              </span>
              {n.key === "approvals" && pending.length > 0 && (
                <b>{pending.length}</b>
              )}
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <Icon name="shield" />
          <p>
            每一步，都有依据。<small>证据可追溯 · 人工掌握决定权</small>
          </p>
          <button
            className="connection"
            onClick={() => setShowConnection(true)}
          >
            <span className={error ? "dot off" : "dot"} />
            {token ? "工作区连接" : "配置工作区连接"}
            <span>↗</span>
          </button>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div>
            <span className="breadcrumb">工作区</span>
            <span className="separator">/</span>
            <strong>{caseId ? "Case 详情" : current.label}</strong>
          </div>
          <div className="topbar-actions">
            <button
              className="icon-button"
              onClick={changed}
              aria-label="刷新数据"
              title="刷新数据"
            >
              <Icon name="refresh" />
            </button>
            <span className="avatar" aria-label="当前工作区用户">
              TC
            </span>
          </div>
        </header>
        <main id="main" className="main">
          {notice && (
            <div className="notice good" role="status">
              {notice}
              <button className="text-button" onClick={() => setNotice("")}>
                关闭
              </button>
            </div>
          )}
          <ErrorBox error={error} />
          {error && (
            <button
              className="button secondary"
              onClick={() => setShowConnection(true)}
            >
              连接设置
            </button>
          )}
          <div className="safety-strip">
            <Icon name="shield" />
            <span>
              {settings.outbound_enabled === true
                ? "外部动作仍需逐项审批与版本校验"
                : "真实外发关闭"}
            </span>
            <span className="muted">
              {["fake", "offline", "demo"].includes(
                text(
                  settings.runtime_mode ??
                    settings.agent_provider ??
                    settings.runtime,
                  "",
                ).toLowerCase(),
              )
                ? "当前为离线模拟环境 · 来源与结果标明合成状态"
                : "草稿批准不等于发送授权"}
            </span>
          </div>
          {loading && cases.length === 0 && (
            <div className="loading" role="status">
              正在读取工作区…
            </div>
          )}
          {section === "dashboard" && (
            <Dashboard
              cases={cases}
              approvals={pending}
              followups={openFollowups}
              onImport={() => setShowImport(true)}
            />
          )}
          {section === "cases" && !caseId && (
            <CaseList
              cases={cases}
              onImport={() => setShowImport(true)}
              loading={loading}
              onChange={changed}
            />
          )}
          {section === "cases" && caseId && (
            <CaseDetail
              key={caseId}
              caseId={caseId}
              canReview={["admin", "reviewer"].includes(text(me.role))}
              revision={revision}
              onChange={changed}
              onNotice={setNotice}
            />
          )}
          {section === "approvals" && (
            <>
              <PageHeading
                eyebrow="HUMAN DECISIONS"
                title="把判断留给人"
                description="对照原文、证据与当前草稿，审核每一个需要明确决定的事项。"
              />
              <ApprovalList approvals={approvals} onChange={changed} />
            </>
          )}
          {section === "follow-ups" && (
            <>
              <PageHeading
                eyebrow="NEXT CONVERSATION"
                title="让每一次沟通都有后续"
                description="已安排的下一步、负责人和到期时间。"
              />
              <Followups items={followups} onChange={changed} />
            </>
          )}
          {section === "sources" && <Sources settings={settings} />}
          {section === "settings" && (
            <Settings
              settings={settings}
              onConnect={() => setShowConnection(true)}
              hasToken={Boolean(token)}
            />
          )}
        </main>
        <footer className="footer">
          TradeCase <span>以证据支持判断，以审核保护承诺。</span>
          <span>数据以业务服务为准</span>
        </footer>
      </div>
      {showImport && (
        <ImportDialog
          maxUploadBytes={Number(settings.max_upload_bytes) || 2 * 1024 * 1024}
          demoEnabled={settings.demo_enabled === true}
          onClose={() => setShowImport(false)}
          onCreated={(newId) => {
            setShowImport(false);
            changed();
            router.push("/cases/" + newId);
          }}
        />
      )}
      {showConnection && (
        <ModalOverlay
          onClose={() => setShowConnection(false)}
          returnFocusSelector=".connection"
        >
          <section
            className="modal small"
            role="dialog"
            aria-modal="true"
            aria-labelledby="connection-title"
          >
            <button
              className="modal-close icon-button"
              aria-label="关闭连接设置"
              onClick={() => setShowConnection(false)}
            >
              <Icon name="close" />
            </button>
            <span className="eyebrow">WORKSPACE ACCESS</span>
            <h2 id="connection-title">连接工作区</h2>
            <p className="muted">
              输入管理员为你的工作区配置的访问令牌。令牌仅保存在当前浏览器标签页会话，不会进入网址。
            </p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                sessionStorage.setItem("tradecase-token", token.trim());
                setCases([]);
                setApprovals([]);
                setFollowups([]);
                setSettings({});
                router.push("/");
                setShowConnection(false);
                changed();
              }}
            >
              <Field label="访问令牌">
                <input
                  autoFocus
                  type="password"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  autoComplete="off"
                  name="access-token"
                />
              </Field>
              <div className="button-row">
                <button className="button" type="submit">
                  连接工作区
                </button>
                <button
                  className="button secondary"
                  type="button"
                  onClick={() => {
                    sessionStorage.removeItem("tradecase-token");
                    setCases([]);
                    setApprovals([]);
                    setFollowups([]);
                    setSettings({});
                    router.push("/");
                    setToken("");
                    setShowConnection(false);
                    changed();
                  }}
                >
                  退出当前连接
                </button>
              </div>
            </form>
          </section>
        </ModalOverlay>
      )}
    </div>
  );
}

function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  );
}
function Dashboard({
  cases,
  approvals,
  followups,
  onImport,
}: {
  cases: Row[];
  approvals: Row[];
  followups: Row[];
  onImport: () => void;
}) {
  const researching = cases.filter(
    (c) => text(c.status) === "RESEARCHING",
  ).length;
  const due = followups.filter(
    (f) => f.due_at && new Date(String(f.due_at)).getTime() <= Date.now(),
  ).length;
  return (
    <>
      <PageHeading
        eyebrow="YOUR TRADE DESK"
        title="从一封询盘，走向下一次机会。"
        description="查看正在推进的案件，处理需要你判断的事项。"
        action={
          <button className="button" onClick={onImport}>
            <Icon name="plus" />
            导入询盘
          </button>
        }
      />
      <div className="stats-band">
        <Link href="/cases">
          <span>全部询盘</span>
          <strong>{cases.length.toString().padStart(2, "0")}</strong>
          <small>客户机会与调查记录</small>
        </Link>
        <Link href="/approvals">
          <span>等待你的判断</span>
          <strong className="accent">
            {approvals.length.toString().padStart(2, "0")}
          </strong>
          <small>证据、风险与草稿审核</small>
        </Link>
        <Link href="/cases?status=RESEARCHING">
          <span>正在调查</span>
          <strong>{researching.toString().padStart(2, "0")}</strong>
          <small>进度和证据持续保存</small>
        </Link>
        <Link href="/follow-ups">
          <span>已到期跟进</span>
          <strong>{due.toString().padStart(2, "0")}</strong>
          <small>有待推进的下一步</small>
        </Link>
      </div>
      <div className="dashboard-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">CASE QUEUE</span>
              <h2>近期询盘</h2>
            </div>
            <Link href="/cases" className="text-link">
              查看全部 ↗
            </Link>
          </div>
          <CasesTable cases={cases.slice(0, 6)} />
        </section>
        <section className="decision-column">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">YOUR NEXT MOVE</span>
              <h2>需要关注</h2>
            </div>
          </div>
          {approvals.length ? (
            approvals.slice(0, 3).map((a) => (
              <Link
                key={id(a)}
                href={`/cases/${text(a.case_id)}?tab=draft`}
                className="decision-preview"
              >
                <span className="mini-label">人工审核</span>
                <h3>{text(a.title, scopeLabel(a.scope ?? a.action_scope))}</h3>
                <p>
                  Case {text(a.case_id).slice(0, 12)} · 版本{" "}
                  {text(a.case_version)}
                </p>
                <span className="text-link">
                  查看证据与草稿 <Icon name="arrow" />
                </span>
              </Link>
            ))
          ) : (
            <Empty title="暂时没有待审核项">
              调查完成后，需要你判断的证据与草稿会出现在这里。
            </Empty>
          )}
          <div className="method-note">
            <span>01 — 04</span>
            <h3>好的跟进，始于清楚的判断。</h3>
            <p>询盘 → 调查 → 审核 → 跟进</p>
            <p>事实有出处，推断有标记，未知保持未知。</p>
          </div>
        </section>
      </div>
    </>
  );
}
function CaseList({
  cases,
  onImport,
  loading,
  onChange,
}: {
  cases: Row[];
  onImport: () => void;
  loading: boolean;
  onChange: () => void;
}) {
  const [query, setQuery] = useState(""),
    [status, setStatus] = useState(""),
    [tag, setTag] = useState(""),
    [offset, setOffset] = useState(0),
    [items, setItems] = useState<Row[]>(cases),
    [selected, setSelected] = useState<Set<string>>(new Set()),
    [fetching, setFetching] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    setStatus(new URLSearchParams(window.location.search).get("status") || "");
  }, []);
  useEffect(() => {
    let active = true;
    const timer = setTimeout(async () => {
      setFetching(true);
      try {
        const queryParams = new URLSearchParams({
          q: query,
          status,
          tag,
          limit: "50",
          offset: String(offset),
        });
        if (!status) queryParams.delete("status");
        if (!tag) queryParams.delete("tag");
        const value = await api("/cases?" + queryParams);
        if (active) {
          setItems(list(value));
          setError("");
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      } finally {
        if (active) setFetching(false);
      }
    }, 250);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [query, status, tag, offset, cases]);
  const toggle = (identity: string) =>
    setSelected((old) => {
      const next = new Set(old);
      if (next.has(identity)) next.delete(identity);
      else next.add(identity);
      return next;
    });
  const batch = async () => {
    setBusy(true);
    setError("");
    const results = await Promise.allSettled(
      [...selected].map((identity) => mutate(`/cases/${identity}/run`)),
    );
    const failures = results.filter((result) => result.status === "rejected");
    if (failures.length)
      setError(
        `${failures.length} 个案件未能开始调查，请查看案件详情；成功提交的任务已保存。`,
      );
    setSelected(new Set());
    setBusy(false);
    onChange();
  };
  return (
    <>
      <PageHeading
        eyebrow="CASE DIRECTORY"
        title="询盘案件"
        description="每一个客户机会，都有完整的证据、判断与跟进记录。"
        action={
          <button className="button" onClick={onImport}>
            <Icon name="plus" />
            导入询盘
          </button>
        }
      />
      <section className="panel">
        <div className="toolbar">
          <input
            aria-label="搜索询盘"
            placeholder="搜索客户、产品、邮箱或案件标题…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOffset(0);
              setSelected(new Set());
            }}
          />
          <select
            aria-label="按状态筛选"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
              setSelected(new Set());
            }}
          >
            <option value="">全部状态</option>
            {[
              "NEW",
              "RESEARCHING",
              "NEEDS_INPUT",
              "NEEDS_REVIEW",
              "READY_TO_FOLLOW_UP",
              "FOLLOW_UP_IN_PROGRESS",
              "CLOSED",
              "FAILED",
            ].map((value) => (
              <option key={value} value={value}>
                {statusText(value)}
              </option>
            ))}
          </select>
          <input
            className="tag-filter"
            aria-label="按标签筛选"
            placeholder="标签"
            value={tag}
            onChange={(e) => {
              setTag(e.target.value);
              setOffset(0);
              setSelected(new Set());
            }}
          />
        </div>
        {selected.size > 0 && (
          <div className="batch-toolbar">
            <span>已选择 {selected.size} 个新建 / 失败案件</span>
            <button
              className="button secondary compact"
              disabled={busy}
              onClick={() => void batch()}
            >
              调查所选（{selected.size}）
            </button>
            <button
              className="text-button"
              onClick={() => setSelected(new Set())}
            >
              清空选择
            </button>
          </div>
        )}
        <ErrorBox error={error} />
        <CasesTable
          cases={items}
          loading={loading || fetching}
          selected={selected}
          toggle={toggle}
        />
        <div className="pagination">
          <span>
            本页 {items.length} 个案件 · 第 {offset / 50 + 1} 页
          </span>
          <div className="button-row">
            <button
              className="button secondary compact"
              disabled={offset === 0 || fetching}
              onClick={() => {
                setOffset((v) => Math.max(0, v - 50));
                setSelected(new Set());
              }}
            >
              上一页
            </button>
            <button
              className="button secondary compact"
              disabled={items.length < 50 || fetching}
              onClick={() => {
                setOffset((v) => v + 50);
                setSelected(new Set());
              }}
            >
              下一页
            </button>
          </div>
        </div>
      </section>
    </>
  );
}

function CasesTable({
  cases,
  loading = false,
  selected,
  toggle,
}: {
  cases: Row[];
  loading?: boolean;
  selected?: Set<string>;
  toggle?: (identity: string) => void;
}) {
  if (!cases.length)
    return (
      <Empty title={loading ? "正在加载询盘" : "尚无符合条件的询盘"}>
        导入真实询盘开始调查，或选择明确标记的合成案例演示。
      </Empty>
    );
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>客户 / 询盘</th>
            <th>状态</th>
            <th>优先级</th>
            <th>最近更新</th>
            <th>
              <span className="sr-only">打开案件</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            <tr key={id(c)}>
              <td>
                {toggle && ["NEW", "FAILED"].includes(text(c.status)) && (
                  <input
                    className="case-checkbox"
                    type="checkbox"
                    aria-label={`选择案件 ${text(c.title)}`}
                    checked={selected?.has(id(c)) || false}
                    onChange={() => toggle(id(c))}
                  />
                )}
                <Link href={`/cases/${id(c)}`} className="case-name">
                  {text(c.title ?? c.buyer_company, "未命名询盘")}
                </Link>
                <div className="table-sub">
                  {text(
                    c.buyer_country ??
                      row(c.inquiry).buyer_country ??
                      row(c.inquiry).target_country,
                    "地区待确认",
                  )}{" "}
                  ·{" "}
                  {text(
                    c.product ??
                      row(c.inquiry).product ??
                      row(c.inquiry).product_summary,
                    "产品待确认",
                  )}
                  {Array.isArray(c.tags) &&
                    c.tags.map((tag) => (
                      <span className="case-tag" key={String(tag)}>
                        {String(tag)}
                      </span>
                    ))}
                  {(c.is_synthetic === true || c.synthetic === true) && (
                    <span className="synthetic-tag">合成</span>
                  )}
                </div>
              </td>
              <td>
                <Badge value={c.status} />
              </td>
              <td>
                <span className="priority">{text(c.priority, "待评估")}</span>
              </td>
              <td className="muted">{date(c.updated_at ?? c.created_at)}</td>
              <td>
                <Link
                  className="row-arrow"
                  href={`/cases/${id(c)}`}
                  aria-label={`打开${text(c.title, "询盘")}`}
                >
                  <Icon name="arrow" />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ImportDialog({
  onClose,
  onCreated,
  maxUploadBytes,
  demoEnabled,
}: {
  onClose: () => void;
  onCreated: (id: string) => void;
  maxUploadBytes: number;
  demoEnabled: boolean;
}) {
  const [mode, setMode] = useState("text"),
    [title, setTitle] = useState(""),
    [content, setContent] = useState(""),
    [company, setCompany] = useState(""),
    [email, setEmail] = useState(""),
    [country, setCountry] = useState(""),
    [product, setProduct] = useState("");
  const [fixture, setFixture] = useState("case_strong"),
    [file, setFile] = useState<File | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const requestKey = useRef<string>("");
  useEffect(() => {
    requestKey.current = crypto.randomUUID();
  }, []);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      let result: unknown;
      if (mode === "file") {
        if (!file) throw new Error("请选择 .eml 或 .txt 询盘文件。");
        if (file.size > maxUploadBytes)
          throw new Error(
            `文件不能超过 ${Math.round(maxUploadBytes / 1024 / 1024)} MiB。`,
          );
        const form = new FormData();
        form.set("file", file);
        form.set("title", title || file.name);
        result = await api("/cases/import", {
          method: "POST",
          headers: { "Idempotency-Key": requestKey.current },
          body: form,
        });
      } else {
        result = await mutate(
          "/cases",
          {
            title:
              title || (mode === "demo" ? "合成演示 · Harbor Toys" : "新询盘"),
            raw_content: content,
            source_type: "text",
            ...(company ? { buyer_company: company } : {}),
            ...(email ? { buyer_email: email } : {}),
            ...(country ? { buyer_country: country } : {}),
            ...(product ? { product } : {}),
            ...(mode === "demo" ? { fixture } : {}),
          },
          "POST",
          requestKey.current,
        );
      }
      const newId = id(row(result));
      if (!newId)
        throw new Error("服务未返回 Case ID，请检查案件列表后再重试。");
      onCreated(newId);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <ModalOverlay onClose={onClose} returnFocusSelector=".page-heading .button">
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-title"
      >
        <button
          className="modal-close icon-button"
          onClick={onClose}
          aria-label="关闭导入"
        >
          <Icon name="close" />
        </button>
        <span className="eyebrow">START A CASE</span>
        <h2 id="import-title">把询盘放到工作台上</h2>
        <p className="muted">
          原文会保留。任何缺失与不确定信息，都需要在调查中确认。
        </p>
        <div className="segmented" aria-label="导入方式">
          {[
            ["text", "粘贴 / 手动录入"],
            ["file", "上传邮件"],
            ...(demoEnabled ? [["demo", "合成演示"]] : []),
          ].map(([v, l]) => (
            <button
              key={v}
              className={mode === v ? "selected" : ""}
              onClick={() => setMode(v)}
            >
              {l}
            </button>
          ))}
        </div>
        <form onSubmit={submit}>
          <Field label="案件标题">
            <input
              autoFocus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="例如：Harbor Toys · 木制玩具采购"
              maxLength={240}
            />
          </Field>
          {mode === "text" && (
            <>
              <Field label="询盘原文">
                <textarea
                  required
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  rows={6}
                  placeholder="粘贴客户询盘，保留原始需求和联系方式…"
                  maxLength={200000}
                />
              </Field>
              <div className="form-grid">
                <Field label="客户公司（可选）">
                  <input
                    value={company}
                    onChange={(e) => setCompany(e.target.value)}
                  />
                </Field>
                <Field label="客户邮箱（可选）">
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </Field>
                <Field label="国家 / 地区（可选）">
                  <input
                    value={country}
                    onChange={(e) => setCountry(e.target.value)}
                  />
                </Field>
                <Field label="产品（可选）">
                  <input
                    value={product}
                    onChange={(e) => setProduct(e.target.value)}
                  />
                </Field>
              </div>
            </>
          )}
          {mode === "file" && (
            <Field
              label="询盘文件"
              hint={`支持 UTF-8 .eml、.txt，最大 ${Math.round(maxUploadBytes / 1024 / 1024)} MiB。邮件附件仅登记，不运行其中内容。`}
            >
              <input
                type="file"
                accept=".eml,.txt"
                required
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
            </Field>
          )}
          {mode === "demo" && (
            <>
              <Note>
                演示内容为合成数据，仅用于离线验证；不代表真实公司、法规或在线调查成功。
              </Note>
              <Field label="演示场景">
                <select
                  value={fixture}
                  onChange={(e) => setFixture(e.target.value)}
                >
                  {[
                    ["case_strong", "证据充分"],
                    ["case_name_collision", "同名企业歧义"],
                    ["case_missing_platform", "平台信息缺失"],
                    ["case_regulation_unknown", "规则未覆盖"],
                    ["case_inferred_email", "推断邮箱"],
                    ["case_prompt_injection", "提示注入"],
                    ["case_resume_after_failure", "失败后恢复"],
                  ].map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </Field>
            </>
          )}
          <ErrorBox error={error} />
          <div className="modal-footer">
            <span className="muted">创建案件不会发送任何邮件。</span>
            <button className="button" type="submit" disabled={busy}>
              {busy ? "正在保存…" : "创建案件"}
              <Icon name="arrow" />
            </button>
          </div>
        </form>
      </section>
    </ModalOverlay>
  );
}

function CaseDetail({
  caseId,
  canReview,
  revision,
  onChange,
  onNotice,
}: {
  caseId: string;
  canReview: boolean;
  revision: number;
  onChange: () => void;
  onNotice: (v: string) => void;
}) {
  const [data, setData] = useState<Row>({}),
    [tasks, setTasks] = useState<Row[]>([]),
    [evidence, setEvidence] = useState<Row>({}),
    [risks, setRisks] = useState<Row[]>([]),
    [artifacts, setArtifacts] = useState<Row[]>([]),
    [events, setEvents] = useState<Row[]>([]),
    [approvals, setApprovals] = useState<Row[]>([]),
    [followups, setFollowups] = useState<Row[]>([]),
    [related, setRelated] = useState<Row[]>([]);
  const [tab, setTab] = useState("research"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true);
  const after = useRef(0);
  const prefix = "/cases/" + encodeURIComponent(caseId);
  const refresh = useCallback(async () => {
    try {
      const results = await Promise.all([
        api(prefix),
        api(prefix + "/tasks"),
        api(prefix + "/evidence"),
        api(prefix + "/risks"),
        api(prefix + "/artifacts"),
        api(prefix + "/events?format=json&after=" + after.current),
        api("/approvals?case_id=" + encodeURIComponent(caseId)),
        api("/follow-ups?case_id=" + encodeURIComponent(caseId)),
      ]);
      void api(prefix + "/related")
        .then((value) => setRelated(list(value)))
        .catch(() => setRelated([]));
      setData(row(results[0]));
      setTasks(list(results[1]));
      setEvidence({ ...row(results[2]), conflicts: row(results[0]).conflicts });
      setRisks(list(results[3]).map((r) => ({ ...row(r.data), ...r })));
      setArtifacts(list(results[4]));
      const ev = list(results[5]);
      setEvents((old) => {
        const merged = new Map(
          [...old, ...ev].map((event) => [
            text(event.event_id ?? event.id),
            event,
          ]),
        );
        return [...merged.values()]
          .sort((a, b) => Number(a.sequence) - Number(b.sequence))
          .slice(-1000);
      });
      after.current = Math.max(
        after.current,
        ...ev.map((e) => Number(e.sequence) || 0),
      );
      setApprovals(list(results[6]).filter((a) => text(a.case_id) === caseId));
      setFollowups(list(results[7]).filter((f) => text(f.case_id) === caseId));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [prefix, caseId]);
  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("tab");
    if (requested) setTab(requested);
    void refresh();
  }, [refresh, revision]);
  useEffect(() => {
    const controller = new AbortController();
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    void streamCaseEvents(
      caseId,
      after.current,
      (event) => {
        after.current = Math.max(after.current, Number(event.sequence) || 0);
        setEvents((old) =>
          old.some(
            (e) =>
              text(e.event_id ?? e.id) === text(event.event_id ?? event.id),
          )
            ? old
            : [...old, event],
        );
        if (!refreshTimer)
          refreshTimer = setTimeout(() => {
            refreshTimer = undefined;
            void refresh();
          }, 500);
      },
      controller.signal,
    ).catch(() => {});
    const timer = setInterval(() => {
      void refresh();
    }, 5000);
    return () => {
      controller.abort();
      clearInterval(timer);
      if (refreshTimer) clearTimeout(refreshTimer);
    };
  }, [caseId, refresh]);
  const act = async (path: string, body: unknown = {}) => {
    setBusy(true);
    try {
      await mutate(path, body);
      await refresh();
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const inquiry = row(data.inquiry);
  const claims = rows(evidence.claims);
  const sources = rows(evidence.sources);
  const pending = approvals.filter(
    (a) => text(a.status).toUpperCase() === "PENDING",
  );
  const isSynthetic =
    data.synthetic === true ||
    data.is_synthetic === true ||
    inquiry.is_synthetic === true;
  const navigateTab = (value: string) => {
    setTab(value);
    window.history.replaceState(null, "", `/cases/${caseId}?tab=${value}`);
  };
  if (loading) return <div className="loading">正在读取案件…</div>;
  return (
    <>
      <Link href="/cases" className="back-link">
        ← 返回询盘案件
      </Link>
      <PageHeading
        eyebrow={"CASE / " + caseId.slice(0, 16)}
        title={text(data.title, "询盘详情")}
        description={`${text(inquiry.buyer_company ?? inquiry.buyer_company_hint ?? data.buyer_company, "客户待确认")} · ${text(inquiry.buyer_country ?? inquiry.target_country ?? data.buyer_country, "国家待确认")}`}
        action={
          pending.length ? (
            <button className="button" onClick={() => navigateTab("draft")}>
              查看待审核项 <span>{pending.length}</span>
            </button>
          ) : ["READY_TO_FOLLOW_UP", "FOLLOW_UP_IN_PROGRESS"].includes(
              text(data.status),
            ) ? (
            <button className="button" onClick={() => navigateTab("timeline")}>
              安排下一步跟进
              <Icon name="arrow" />
            </button>
          ) : (
            <button
              className="button"
              disabled={busy || text(data.status) === "RESEARCHING"}
              onClick={() => void act(prefix + "/run")}
            >
              {busy
                ? "正在提交…"
                : text(data.status) === "NEW"
                  ? "开始调查"
                  : "恢复 / 更新调查"}
              <Icon name="arrow" />
            </button>
          )
        }
      />
      <div className="case-status">
        <Badge value={data.status} />
        <span>版本 {text(data.version)}</span>
        <span>更新于 {date(data.updated_at)}</span>
        {isSynthetic && (
          <strong className="synthetic-tag">合成演示 · 非真实调查</strong>
        )}
      </div>
      <ErrorBox error={error} />
      <CaseMetadata
        caseData={data}
        prefix={prefix}
        onChange={() => {
          void refresh();
          onChange();
        }}
        related={related}
      />
      <div className="case-tabs" role="tablist" aria-label="案件详情">
        {[
          ["research", "调查与证据"],
          ["risks", "风险与规则"],
          ["draft", "邮件草稿与审核"],
          ["runs", "执行记录"],
          ["timeline", "跟进时间线"],
        ].map(([v, l]) => (
          <button
            key={v}
            role="tab"
            aria-selected={tab === v}
            className={tab === v ? "active" : ""}
            onClick={() => navigateTab(v)}
          >
            {l}
            {v === "draft" && pending.length > 0 && (
              <span>{pending.length}</span>
            )}
          </button>
        ))}
      </div>
      {tab === "research" && (
        <div className="case-grid">
          <section className="summary-panel">
            <span className="eyebrow">INQUIRY FACTS</span>
            <h2>客户询盘</h2>
            <dl className="fact-list">
              {[
                [
                  "公司",
                  inquiry.buyer_company ??
                    inquiry.buyer_company_hint ??
                    data.buyer_company,
                ],
                ["联系人", inquiry.buyer_contact ?? inquiry.contact_name],
                [
                  "国家 / 地区",
                  inquiry.buyer_country ?? inquiry.target_country,
                ],
                ["邮箱", inquiry.buyer_email],
                ["产品", inquiry.product ?? inquiry.product_summary],
                ["数量", inquiry.quantity],
                ["交期", inquiry.delivery_time ?? inquiry.requested_delivery],
                ["贸易条款", inquiry.trade_terms ?? inquiry.incoterms],
              ].map(([k, v]) => (
                <div key={String(k)}>
                  <dt>{String(k)}</dt>
                  <dd>{text(v, "待确认")}</dd>
                </div>
              ))}
            </dl>
            <details className="raw-inquiry" open>
              <summary>查看原始询盘</summary>
              <pre>
                {text(
                  inquiry.buyer_message ??
                    inquiry.raw_content ??
                    data.raw_content,
                  "原文记录暂不可用",
                )}
              </pre>
            </details>
            {rows(inquiry.files ?? inquiry.attachments).length > 0 && (
              <details>
                <summary>附件记录（不执行）</summary>
                <Details value={inquiry.files ?? inquiry.attachments} />
              </details>
            )}
          </section>
          <section className="findings-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">EVIDENCE LEDGER</span>
                <h2>结论，以及它的依据</h2>
              </div>
              <span className="count">
                {claims.length} 条主张 · {sources.length} 个来源
              </span>
            </div>
            <EvidenceView evidence={evidence} prefix={prefix} />
            {canReview && (
              <AdvancedReview
                caseData={data}
                prefix={prefix}
                onChange={() => {
                  void refresh();
                  onChange();
                }}
              />
            )}
            <ManualSourceForm
              caseData={data}
              prefix={prefix}
              onChange={() => {
                void refresh();
                onChange();
              }}
            />
            {Boolean(data.assessment) && (
              <section className="assessment-section">
                <h3>分维度评估</h3>
                <Details value={data.assessment} />
              </section>
            )}
          </section>
        </div>
      )}
      {tab === "risks" && (
        <section className="panel content-panel">
          <span className="eyebrow">RULES & CONTEXT</span>
          <h2>风险需要放回适用范围</h2>
          <p className="muted">
            规则有来源、版本和有效期。未覆盖或证据不足会保留为待审核，不构成法律上的最终判断。
          </p>
          {risks.length ? (
            risks.map((r, i) => (
              <article className="risk-row" key={text(r.id, i.toString())}>
                <div>
                  <Badge
                    value={
                      r.status ??
                      (r.requires_review ? "NEEDS_REVIEW" : "UNKNOWN")
                    }
                  />
                  <span className="mini-label">
                    {text(r.category ?? r.check_type)} ·{" "}
                    {text(r.severity, "待评估")}
                  </span>
                </div>
                <h3>{text(r.title ?? r.rule_id ?? r.summary, "规则检查")}</h3>
                <p>{text(r.rationale ?? r.description ?? r.message)}</p>
                <dl className="inline-facts">
                  <div>
                    <dt>适用地区</dt>
                    <dd>{text(r.jurisdiction ?? r.country)}</dd>
                  </div>
                  <div>
                    <dt>规则版本</dt>
                    <dd>{text(r.rule_version ?? r.version)}</dd>
                  </div>
                  <div>
                    <dt>有效期</dt>
                    <dd>{date(r.valid_until)}</dd>
                  </div>
                </dl>
                <details>
                  <summary>查看依据与来源</summary>
                  <Details value={r} />
                </details>
              </article>
            ))
          ) : (
            <Empty title="尚未生成规则检查">
              调查流程会分别检查目标市场和平台 /
              贸易条款；缺失规则会进入人工复核。
            </Empty>
          )}
        </section>
      )}
      {tab === "draft" && (
        <DraftWorkspace
          caseData={data}
          canReview={canReview}
          artifacts={artifacts}
          approvals={approvals}
          prefix={prefix}
          onChange={() => {
            void refresh();
            onChange();
          }}
          onNotice={onNotice}
        />
      )}
      {tab === "runs" && (
        <section className="panel content-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">EXECUTION HISTORY</span>
              <h2>任务与执行尝试</h2>
            </div>
            <span className="muted">工作流安排依赖，任务管理器领取执行</span>
          </div>
          {tasks.length ? (
            tasks.map((t) => (
              <article className="task-row" key={id(t)}>
                <div>
                  <h3>{text(t.task_type ?? t.type)}</h3>
                  <span className="mono muted">{id(t)}</span>
                </div>
                <Badge value={t.status} />
                <span>尝试 {text(t.attempt_count, "0")}</span>
                {text(t.status) === "FAILED" && (
                  <button
                    className="button secondary compact"
                    disabled={busy}
                    onClick={() => void act(prefix + `/tasks/${id(t)}/retry`)}
                  >
                    重试此任务
                  </button>
                )}
                <details>
                  <summary>依赖、预算与执行结果</summary>
                  <Details value={t} />
                </details>
              </article>
            ))
          ) : (
            <Empty title="尚未开始调查">
              启动调查后，任务依赖、Agent 执行与失败原因会保存于此。
            </Empty>
          )}
          <h3 className="section-label">持久事件</h3>
          <EventList events={events} />
        </section>
      )}
      {tab === "timeline" && (
        <>
          <FollowupForm
            caseId={caseId}
            onChange={() => {
              void refresh();
              onChange();
            }}
          />
          <Followups
            items={followups}
            onChange={() => {
              void refresh();
              onChange();
            }}
          />
          <section className="panel content-panel">
            <h2>案件时间线</h2>
            <EventList events={events} />
          </section>
        </>
      )}
      <div className="export-bar">
        <span>报告可追溯至原始记录</span>
        <div className="button-row">
          {["markdown", "json", "pdf"].map((format) => (
            <button
              key={format}
              className="text-button"
              onClick={() =>
                download(
                  prefix + "/export?format=" + format,
                  `tradecase-${caseId}.${format === "markdown" ? "md" : format}`,
                ).catch((e) => setError(e.message))
              }
            >
              导出 {format === "markdown" ? "Markdown" : format.toUpperCase()} ↗
            </button>
          ))}
        </div>
      </div>
    </>
  );
}

function EvidenceView({ evidence, prefix }: { evidence: Row; prefix: string }) {
  const claims = rows(evidence.claims),
    sources = rows(evidence.sources),
    links = rows(evidence.links ?? evidence.claim_evidence_links);
  const [selected, setSelected] = useState<Row | null>(null),
    [snapshot, setSnapshot] = useState(""),
    [error, setError] = useState("");
  const show = async (source: Row) => {
    setSelected(source);
    setSnapshot("");
    setError("");
    try {
      const response = await api(
        prefix +
          "/sources/" +
          text(source.id ?? source.source_id) +
          "/snapshot",
      );
      setSnapshot(
        typeof response === "string"
          ? response
          : text(
              row(response).content ?? row(response).text,
              "快照暂无可读内容",
            ),
      );
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const category = (c: Row) =>
    text(
      c.kind ?? c.assertion_type ?? c.assertion_status ?? c.status,
      "UNKNOWN",
    ).toUpperCase();
  const groups = [
    {
      label: "事实 / 来源支持",
      test: (c: Row) => ["FACT", "VERIFIED", "SUPPORTED"].includes(category(c)),
    },
    {
      label: "推断",
      test: (c: Row) => ["INFERENCE", "INFERRED"].includes(category(c)),
    },
    {
      label: "未知 / 待核实",
      test: (c: Row) =>
        !["FACT", "VERIFIED", "SUPPORTED", "INFERENCE", "INFERRED"].includes(
          category(c),
        ),
    },
  ];
  if (!claims.length && !sources.length)
    return (
      <Empty title="证据正在等待建立">
        完成调查后，每条结论会关联来源、采集时间和快照。
      </Empty>
    );
  return (
    <>
      {Array.isArray(evidence.conflicts) && evidence.conflicts.length > 0 && (
        <div className="notice danger">
          <strong>存在来源冲突，需要人工判断。</strong>
          <Details value={evidence.conflicts} />
        </div>
      )}
      {groups.map((group) => {
        const items = claims.filter(group.test);
        return (
          <div className="claim-group" key={group.label}>
            <h3>
              {group.label}
              <span>{items.length}</span>
            </h3>
            {items.length ? (
              items.map((c, i) => {
                const linked = links.filter(
                  (l) => text(l.claim_id) === text(c.id ?? c.claim_id),
                );
                const sourceIds = new Set([
                  ...linked.map((l) => text(l.source_id)),
                  ...(Array.isArray(c.source_ids)
                    ? c.source_ids.map(String)
                    : []),
                ]);
                const relevant = sources.filter(
                  (s) =>
                    sourceIds.has(text(s.id ?? s.source_id)) ||
                    (c.source_id && c.source_id === s.id),
                );
                return (
                  <article
                    className="claim"
                    key={text(c.id ?? c.claim_id, i.toString())}
                  >
                    <span className="claim-index">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <div>
                      <p>
                        {text(c.text ?? c.claim ?? c.assertion ?? c.content)}
                      </p>
                      <div className="claim-meta">
                        <Badge
                          value={c.status ?? c.assertion_status ?? c.kind}
                        />
                        <span>{text(c.subject ?? c.entity_id, "")}</span>
                      </div>
                      <div className="source-links">
                        {relevant.map((s) => (
                          <button
                            key={text(s.id ?? s.source_id)}
                            onClick={() => void show(s)}
                          >
                            ↗{" "}
                            {text(
                              s.title ??
                                s.source_title ??
                                s.url ??
                                s.source_url,
                              "查看来源",
                            )}
                          </button>
                        ))}
                      </div>
                    </div>
                  </article>
                );
              })
            ) : (
              <p className="quiet-empty">暂无此类主张</p>
            )}
          </div>
        );
      })}
      <div className="source-catalog">
        <h3>来源记录</h3>
        {sources.map((s) => (
          <button
            className="source-record"
            key={text(s.id ?? s.source_id)}
            onClick={() => void show(s)}
          >
            <span>
              <strong>
                {text(
                  s.title ?? s.source_title ?? s.url ?? s.source_url,
                  "来源",
                )}
              </strong>
              <small>
                {text(s.source_type ?? s.type)} · {date(s.captured_at)}
              </small>
            </span>
            <span>↗</span>
          </button>
        ))}
      </div>
      {selected && (
        <ModalOverlay
          onClose={() => setSelected(null)}
          returnFocusSelector=".source-catalog .source-record"
        >
          <section
            className="modal source-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="source-title"
          >
            <button
              className="modal-close icon-button"
              onClick={() => setSelected(null)}
              aria-label="关闭来源"
            >
              <Icon name="close" />
            </button>
            <span className="eyebrow">SOURCE SNAPSHOT</span>
            <h2 id="source-title">
              {text(selected.title ?? selected.source_title, "来源证据")}
            </h2>
            <dl className="fact-list">
              <div>
                <dt>原始地址</dt>
                <dd>{text(selected.url ?? selected.source_url)}</dd>
              </div>
              <div>
                <dt>采集时间</dt>
                <dd>{date(selected.captured_at)}</dd>
              </div>
              <div>
                <dt>快照 hash</dt>
                <dd className="mono">
                  {text(
                    selected.snapshot_hash ??
                      selected.sha256 ??
                      selected.content_hash,
                  )}
                </dd>
              </div>
              <div>
                <dt>许可 / 可用性</dt>
                <dd>
                  {text(
                    selected.license ??
                      selected.license_status ??
                      selected.status,
                    "未记录",
                  )}
                </dd>
              </div>
            </dl>
            {(selected.is_synthetic === true ||
              row(selected.data).synthetic === true ||
              selected.license_status === "SYNTHETIC") && (
              <Note>合成演示来源，不代表真实网页或法规。</Note>
            )}
            {row(selected.data).authority === "manual_public_snapshot" && (
              <Note>
                人工提供的网页快照，系统未执行在线抓取，来源真实性与许可仍需审核。
              </Note>
            )}
            <h3>引用片段</h3>
            <blockquote>
              {text(
                selected.excerpt ?? selected.locator,
                "请对照快照与关联主张核实",
              )}
            </blockquote>
            <ErrorBox error={error} />
            <h3>原始快照（纯文本）</h3>
            <pre className="snapshot">{snapshot || "正在读取…"}</pre>
          </section>
        </ModalOverlay>
      )}
    </>
  );
}

function normalizeArtifacts(items: Row[]): Row[] {
  return items.flatMap((a) =>
    Array.isArray(a.versions)
      ? rows(a.versions).map((v) => ({
          ...a,
          ...v,
          artifact_id: a.id,
          kind: a.kind ?? a.type,
        }))
      : [a],
  );
}
function artifactContent(a: Row): unknown {
  const content = a.content ?? a.body ?? a.text;
  if (typeof content === "string" && content.trim().startsWith("{")) {
    try {
      return JSON.parse(content);
    } catch {
      return content;
    }
  }
  return content;
}
function draftText(a: Row): string {
  const content = artifactContent(a);
  return typeof content === "string"
    ? content
    : text(
        row(content).body_text ?? row(content).body ?? row(content).content,
        "",
      );
}
function DraftWorkspace({
  caseData,
  canReview,
  artifacts,
  approvals,
  prefix,
  onChange,
  onNotice,
}: {
  caseData: Row;
  canReview: boolean;
  artifacts: Row[];
  approvals: Row[];
  prefix: string;
  onChange: () => void;
  onNotice: (v: string) => void;
}) {
  const all = normalizeArtifacts(artifacts);
  const drafts = all
    .filter((a) => /draft|reply|email/i.test(text(a.kind ?? a.type ?? a.name)))
    .sort((a, b) => Number(b.version) - Number(a.version));
  const latest = drafts[0];
  const [selectedId, setSelectedId] = useState(""),
    [editing, setEditing] = useState(false),
    [body, setBody] = useState(""),
    [subject, setSubject] = useState(""),
    [tonePreview, setTonePreview] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const selected =
    drafts.find((a) => text(a.id ?? a.version_id) === selectedId) || latest;
  useEffect(() => {
    if (latest) {
      setTonePreview("");
      setBody(draftText(latest));
      setSubject(
        text(latest.subject ?? row(artifactContent(latest)).subject, ""),
      );
    }
  }, [latest?.hash, latest?.id, latest?.version]);
  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await mutate(
        prefix + "/draft",
        { body, subject, case_version: caseData.version },
        "PATCH",
      );
      setEditing(false);
      onChange();
      onNotice("草稿已保存为新版本。旧审批已失效，需要重新审核。");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="draft-grid">
      <section className="panel content-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">REPLY WORKSPACE</span>
            <h2>英文回复草稿</h2>
          </div>
          {latest && (
            <select
              aria-label="草稿历史版本"
              value={selected ? text(selected.id ?? selected.version_id) : ""}
              onChange={(e) => {
                setSelectedId(e.target.value);
                setEditing(false);
              }}
            >
              {drafts.map((a) => (
                <option
                  key={text(a.id ?? a.version_id)}
                  value={text(a.id ?? a.version_id)}
                >
                  版本 {text(a.version)} · {date(a.created_at)}
                </option>
              ))}
            </select>
          )}
        </div>
        <ErrorBox error={error} />
        {latest ? (
          <>
            <div className="draft-meta">
              <span>
                SHA256{" "}
                <code>
                  {text(selected.hash ?? selected.content_hash).slice(0, 20)}…
                </code>
              </span>
              <span>
                {selected === latest ? "当前版本" : "历史版本 · 只读"}
              </span>
            </div>
            {editing ? (
              <>
                <div className="tone-assistance">
                  <p className="muted">
                    语气辅助只调整称呼和结尾，正文事实与承诺保持原样。
                  </p>
                  <div
                    className="button-row"
                    role="group"
                    aria-label="草稿语气预览"
                  >
                    {(
                      [
                        ["professional", "专业"],
                        ["concise", "简洁"],
                        ["warm", "友好"],
                      ] as [DraftTone, string][]
                    ).map(([tone, label]) => (
                      <button
                        key={tone}
                        className="button secondary"
                        onClick={() => {
                          setBody((current) => applyDraftTone(current, tone));
                          setTonePreview(label);
                        }}
                        disabled={busy}
                      >
                        {label}语气
                      </button>
                    ))}
                  </div>
                  {tonePreview && (
                    <p className="notice" role="status">
                      {tonePreview}语气预览 ·
                      尚未保存。请核对正文后保存新版本；现有版本和审批尚未改变。
                    </p>
                  )}
                </div>
                <Field label="邮件主题">
                  <input
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                  />
                </Field>
                <Field label="英文正文">
                  <textarea
                    rows={17}
                    value={body}
                    onChange={(e) => setBody(e.target.value)}
                    maxLength={50000}
                  />
                </Field>
                <Note>
                  保存会生成新版本并使旧批准失效。请勿加入未经验证的价格、认证、库存或交期承诺。
                </Note>
                <div className="button-row">
                  <button
                    className="button"
                    disabled={busy || !body.trim() || !subject.trim()}
                    onClick={() => void save()}
                  >
                    保存新版本
                  </button>
                  <button
                    className="button secondary"
                    onClick={() => setEditing(false)}
                  >
                    取消修改
                  </button>
                </div>
              </>
            ) : (
              <>
                <pre className="mail-draft">{draftText(selected)}</pre>
                <div className="button-row">
                  <button
                    className="button secondary"
                    onClick={() =>
                      navigator.clipboard
                        .writeText(draftText(selected))
                        .then(() =>
                          onNotice(
                            "回复草稿已复制。请在邮件工具中人工核对后发送。",
                          ),
                        )
                        .catch(() =>
                          setError(
                            "浏览器未允许剪贴板访问，请手动选择并复制草稿。",
                          ),
                        )
                    }
                  >
                    复制回复
                  </button>
                  {selected === latest && (
                    <button
                      className="button secondary"
                      onClick={() => {
                        setBody(draftText(latest));
                        setSubject(
                          text(
                            latest.subject ??
                              row(artifactContent(latest)).subject,
                            "",
                          ),
                        );
                        setTonePreview("");
                        setEditing(true);
                      }}
                    >
                      编辑草稿
                    </button>
                  )}
                </div>
              </>
            )}
            {drafts.length > 1 && (
              <details className="version-diff">
                <summary>版本差异（前一版 → 当前版）</summary>
                <LineDiff
                  before={draftText(drafts[1])}
                  after={draftText(latest)}
                />
              </details>
            )}
          </>
        ) : (
          <Empty title="草稿尚未生成">
            完成调查和质量检查后，保守的英文草稿会出现在这里。
          </Empty>
        )}
        <Note>
          批准草稿仅表示可供人工使用。外部发送需要独立的动作授权、最新版本和连接器校验。
        </Note>
        {latest && (
          <OutboundPanel
            caseData={caseData}
            canReview={canReview}
            draft={latest}
            approvals={approvals}
            prefix={prefix}
            onChange={onChange}
          />
        )}
      </section>
      <aside className="approval-column">
        <ApprovalList approvals={approvals} onChange={onChange} compact />
        {all
          .filter(
            (a) => !/draft|reply|email/i.test(text(a.kind ?? a.type ?? a.name)),
          )
          .map((a, i) => (
            <details
              className="artifact-history"
              key={text(a.id, i.toString())}
            >
              <summary>
                {text(a.kind ?? a.type, "报告")} · 版本 {text(a.version)}
              </summary>
              <pre>{draftText(a) || JSON.stringify(a.content, null, 2)}</pre>
            </details>
          ))}
      </aside>
    </div>
  );
}
function LineDiff({ before, after }: { before: string; after: string }) {
  const a = before.split("\n"),
    b = after.split("\n");
  return (
    <div className="diff">
      {a
        .filter((l) => !b.includes(l))
        .map((l, i) => (
          <div className="removed" key={"a" + i}>
            − {l || " "}
          </div>
        ))}
      {b.map((l, i) => (
        <div className={a.includes(l) ? "unchanged" : "added"} key={"b" + i}>
          {a.includes(l) ? "  " : "+ "}
          {l || " "}
        </div>
      ))}
    </div>
  );
}
function ApprovalList({
  approvals,
  onChange,
  compact = false,
}: {
  approvals: Row[];
  onChange: () => void;
  compact?: boolean;
}) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(""),
    [comments, setComments] = useState<Record<string, string>>({});
  const keys = useRef<Record<string, string>>({});
  const decide = async (a: Row, decision: string) => {
    const aid = id(a);
    setBusy(aid);
    setError("");
    try {
      const key = aid + decision + text(a.artifact_hash) + text(a.case_version);
      keys.current[key] ||= crypto.randomUUID();
      await mutate(
        `/approvals/${aid}/decide`,
        {
          decision,
          artifact_hash: a.artifact_hash,
          case_version: a.case_version,
          comment: comments[aid] || "",
        },
        "POST",
        keys.current[key],
      );
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  if (!approvals.length)
    return (
      <section className="panel">
        <Empty title="没有待审核事项">
          调查、风险或草稿需要人工决定时，会生成与具体版本绑定的审核项。
        </Empty>
      </section>
    );
  return (
    <div className={compact ? "approvals-list compact-list" : "approvals-list"}>
      <ErrorBox error={error} />
      {approvals.map((a) => {
        const aid = id(a);
        const pending = text(a.status).toUpperCase() === "PENDING";
        return (
          <article className="approval-card" key={aid}>
            <div className="approval-top">
              <span className="eyebrow">HUMAN REVIEW</span>
              <Badge value={a.status} />
            </div>
            <h3>{text(a.title, scopeLabel(a.scope ?? a.action_scope))}</h3>
            <Link
              className="text-link"
              href={`/cases/${text(a.case_id)}?tab=draft`}
            >
              查看案件与证据 ↗
            </Link>
            {Boolean(a.reason) && <p>{text(a.reason)}</p>}
            <dl className="approval-binding">
              <div>
                <dt>审核范围</dt>
                <dd>{scopeLabel(a.scope ?? a.action_scope)}</dd>
              </div>
              {Boolean(row(a.data).target) && (
                <div>
                  <dt>动作目标</dt>
                  <dd>{text(row(a.data).target)}</dd>
                </div>
              )}
              <div>
                <dt>案件版本</dt>
                <dd>{text(a.case_version)}</dd>
              </div>
              <div>
                <dt>内容 hash</dt>
                <dd className="mono">{text(a.artifact_hash)}</dd>
              </div>
              <div>
                <dt>到期时间</dt>
                <dd>{date(a.expires_at)}</dd>
              </div>
            </dl>
            {pending ? (
              <>
                <Field label="审核说明">
                  <textarea
                    rows={2}
                    value={comments[aid] || ""}
                    onChange={(e) =>
                      setComments({ ...comments, [aid]: e.target.value })
                    }
                    placeholder="记录判断依据或需要补充的信息"
                  />
                </Field>
                <div className="approval-buttons">
                  <button
                    className="button"
                    disabled={Boolean(busy)}
                    onClick={() => void decide(a, "approve")}
                  >
                    审核并批准
                  </button>
                  <button
                    className="button secondary"
                    disabled={Boolean(busy)}
                    onClick={() => void decide(a, "reject")}
                  >
                    拒绝
                  </button>
                  <button
                    className="text-button"
                    disabled={Boolean(busy)}
                    onClick={() => void decide(a, "request_changes")}
                  >
                    要求修改
                  </button>
                  <button
                    className="text-button"
                    disabled={Boolean(busy)}
                    onClick={() => void decide(a, "request_evidence")}
                  >
                    要求补证据
                  </button>
                </div>
                <small className="muted">
                  本次决定绑定以上版本；内容变化后需重新审核。
                </small>
              </>
            ) : (
              <p className="muted">
                {date(a.decided_at)} · {text(a.reviewer_id, "已记录审核人")}
                {(a.comment ?? row(a.data).comment)
                  ? " · " + text(a.comment ?? row(a.data).comment)
                  : ""}
              </p>
            )}
          </article>
        );
      })}
    </div>
  );
}
function FollowupForm({
  caseId,
  onChange,
}: {
  caseId: string;
  onChange: () => void;
}) {
  const [action, setAction] = useState(""),
    [assignee, setAssignee] = useState(""),
    [due, setDue] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <section className="panel content-panel">
      <h2>安排下一步</h2>
      <form
        className="followup-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await mutate(`/cases/${caseId}/follow-ups`, {
              next_action: action,
              assignee: assignee || undefined,
              due_at: due ? new Date(due).toISOString() : undefined,
            });
            setAction("");
            onChange();
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field label="下一步行动">
          <input
            required
            value={action}
            onChange={(e) => setAction(e.target.value)}
            placeholder="例如：确认采购数量与目的港"
          />
        </Field>
        <Field
          label="负责人 ID（可选）"
          hint="留空分配给当前用户；其他负责人必须属于本工作区。"
        >
          <input
            value={assignee}
            onChange={(e) => setAssignee(e.target.value)}
            placeholder="当前用户"
          />
        </Field>
        <Field label="到期时间（本地时区）">
          <input
            type="datetime-local"
            value={due}
            onChange={(e) => setDue(e.target.value)}
          />
        </Field>
        <button className="button secondary" disabled={busy} type="submit">
          创建跟进
        </button>
      </form>
      <ErrorBox error={error} />
    </section>
  );
}
function Followups({
  items,
  onChange,
}: {
  items: Row[];
  onChange: () => void;
}) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(""),
    [postpone, setPostpone] = useState(""),
    [due, setDue] = useState("");
  const action = async (item: Row, kind: string) => {
    setBusy(id(item));
    setError("");
    try {
      await mutate(
        kind === "complete"
          ? `/follow-ups/${id(item)}/complete`
          : `/follow-ups/${id(item)}`,
        kind === "complete"
          ? {}
          : { due_at: new Date(due).toISOString(), version: item.version },
        kind === "complete" ? "POST" : "PATCH",
      );
      setPostpone("");
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  return (
    <section className="panel content-panel">
      <ErrorBox error={error} />
      {!items.length ? (
        <Empty title="下一次跟进，还待安排">
          审核完成后会生成手动跟进任务。也可以在案件详情中自行安排。
        </Empty>
      ) : (
        <div className="followups-list">
          {items.map((f) => {
            const complete = ["DONE", "COMPLETED", "CANCELLED"].includes(
              text(f.status).toUpperCase(),
            );
            const overdue =
              !complete &&
              f.due_at &&
              new Date(String(f.due_at)).getTime() < Date.now();
            return (
              <article className="followup-row" key={id(f)}>
                <div
                  className={
                    overdue ? "followup-time overdue" : "followup-time"
                  }
                >
                  <span>{overdue ? "已到期" : "计划时间"}</span>
                  <strong>{date(f.due_at)}</strong>
                </div>
                <div className="followup-content">
                  <h3>{text(f.next_action ?? f.title)}</h3>
                  <p>{text(f.reason, "")}</p>
                  <Link
                    className="text-link"
                    href={`/cases/${text(f.case_id)}?tab=timeline`}
                  >
                    查看案件 ↗
                  </Link>
                  <span className="muted">
                    {" "}
                    · 负责人 {text(f.assignee ?? f.assignee_id, "未分配")}
                  </span>
                </div>
                <Badge value={f.status} />
                {!complete && (
                  <div className="button-row">
                    <button
                      className="button secondary compact"
                      disabled={Boolean(busy)}
                      onClick={() => void action(f, "complete")}
                    >
                      标记完成
                    </button>
                    <button
                      className="text-button"
                      onClick={() => {
                        setPostpone(id(f));
                        setDue("");
                      }}
                    >
                      推迟
                    </button>
                  </div>
                )}
                {postpone === id(f) && (
                  <form
                    className="postpone-form"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void action(f, "postpone");
                    }}
                  >
                    <Field label="新的到期时间">
                      <input
                        required
                        type="datetime-local"
                        value={due}
                        onChange={(e) => setDue(e.target.value)}
                      />
                    </Field>
                    <button
                      className="button secondary compact"
                      disabled={Boolean(busy)}
                      type="submit"
                    >
                      保存时间
                    </button>
                  </form>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
function EventList({ events }: { events: Row[] }) {
  return events.length ? (
    <ol className="event-list">
      {[...events].reverse().map((e, i) => (
        <li key={text(e.event_id ?? e.id, i.toString())}>
          <span className="event-dot" />
          <div>
            <span className="event-label">{text(e.event_type ?? e.type)}</span>
            <time>{date(e.created_at)}</time>
            <div className="event-refs">
              <span>序号 {text(e.sequence)}</span>
              {Boolean(e.task_id) && (
                <span>任务 {text(e.task_id).slice(0, 16)}</span>
              )}
              {Boolean(e.agent_run_id) && (
                <span>执行 {text(e.agent_run_id).slice(0, 16)}</span>
              )}
            </div>
            {Boolean(e.data_redacted || e.data) && (
              <details>
                <summary>事件详情</summary>
                <Details value={e.data_redacted ?? e.data} />
              </details>
            )}
          </div>
        </li>
      ))}
    </ol>
  ) : (
    <Empty title="暂无事件">已持久化的事件会在刷新和重连后恢复显示。</Empty>
  );
}
function Sources({ settings }: { settings: Row }) {
  const sources = rows(
    settings.sources ?? settings.tools ?? settings.connectors,
  );
  return (
    <>
      <PageHeading
        eyebrow="SOURCES & KNOWLEDGE"
        title="知道依据来自哪里"
        description="只使用明确可用且获得授权的来源。来源不可访问时，保留缺口与失败原因。"
      />
      <section className="panel content-panel">
        <h2>来源与工具连接</h2>
        {sources.length ? (
          sources.map((s, i) => (
            <article
              className="source-setting"
              key={text(s.name, i.toString())}
            >
              <div>
                <h3>{text(s.name ?? s.id)}</h3>
                <p>
                  {text(s.description ?? s.reason ?? s.availability_reason, "")}
                </p>
              </div>
              <Badge
                value={s.status ?? (s.available ? "AVAILABLE" : "UNAVAILABLE")}
              />
              <details>
                <summary>权限、许可与限制</summary>
                <Details value={s} />
              </details>
            </article>
          ))
        ) : (
          <Empty title="尚无已配置来源">
            请由管理员在服务端配置只读来源、许可范围和域名策略。浏览器不会自行连接付费或受限数据库。
          </Empty>
        )}
      </section>
      <KnowledgeLibrary />
    </>
  );
}
function Settings({
  settings,
  onConnect,
  hasToken,
}: {
  settings: Row;
  onConnect: () => void;
  hasToken: boolean;
}) {
  return (
    <>
      <PageHeading
        eyebrow="WORKSPACE SETTINGS"
        title="清楚的权限，明确的边界"
        description="工作区配置由服务端管理；这里展示实际生效值。"
      />
      <div className="settings-grid">
        <section className="panel content-panel">
          <span className="eyebrow">ACCESS</span>
          <h2>访问与身份</h2>
          <p>
            {hasToken ? "当前标签页已配置访问令牌。" : "尚未配置访问令牌。"}
          </p>
          <p className="muted">
            租户和角色由业务服务校验，界面不会通过自行填写租户 ID 切换权限。
          </p>
          <button className="button secondary" onClick={onConnect}>
            管理连接
          </button>
        </section>
        <section className="panel content-panel">
          <span className="eyebrow">OUTBOUND POLICY</span>
          <h2>外部动作</h2>
          <Badge
            value={
              settings.outbound_enabled === true ? "AVAILABLE" : "DISABLED"
            }
          />
          <p>
            每个发送动作必须绑定独立授权、精确内容版本和幂等键。连接未配置时，继续使用手动跟进。
          </p>
          <p className="muted">此界面不会通过草稿批准自动发送邮件。</p>
        </section>
        <section className="panel content-panel wide">
          <span className="eyebrow">ACTIVE CONFIGURATION</span>
          <h2>模型、预算与保留策略</h2>
          {Object.keys(settings).length ? (
            <Details value={settings} />
          ) : (
            <Empty title="配置尚未加载">
              连接工作区后查看生效中的模型、费用、超时与数据保留策略。
            </Empty>
          )}
        </section>
      </div>
    </>
  );
}

function OutboundPanel({
  caseData,
  canReview,
  draft,
  approvals,
  prefix,
  onChange,
}: {
  caseData: Row;
  canReview: boolean;
  draft: Row;
  approvals: Row[];
  prefix: string;
  onChange: () => void;
}) {
  const [receipts, setReceipts] = useState<Row[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [cancelReasons, setCancelReasons] = useState<Record<string, string>>({}),
    [confirmed, setConfirmed] = useState(false);
  const keys = useRef<Record<string, string>>({});
  const target = text(row(artifactContent(draft)).recipient_email, "");
  const hash = text(draft.hash ?? draft.content_hash, "");
  const enabled = caseData.outbound_enabled === true;
  const eligible = approvals.filter(
    (a) =>
      text(a.action_scope ?? a.scope) === "mail_send" &&
      a.status === "APPROVED" &&
      a.artifact_hash === hash &&
      a.case_version === caseData.version,
  );
  const load = useCallback(
    () =>
      api(prefix + "/outbound-actions")
        .then((value) => setReceipts(list(value)))
        .catch(() => {}),
    [prefix],
  );
  useEffect(() => {
    void load();
  }, [load, approvals]);
  const requestApproval = async () => {
    setBusy(true);
    setError("");
    try {
      await mutate(prefix + "/send-approval", {
        case_version: caseData.version,
        artifact_hash: hash,
        target,
        channel: "mail",
      });
      setConfirmed(false);
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const send = async (approval: Row) => {
    setBusy(true);
    setError("");
    try {
      const aid = id(approval);
      keys.current[aid] ||= crypto.randomUUID();
      await mutate(
        prefix + "/outbound-actions",
        {
          approval_id: aid,
          artifact_hash: hash,
          case_version: caseData.version,
        },
        "POST",
        keys.current[aid],
      );
      setConfirmed(false);
      await load();
      onChange();
    } catch (e) {
      setError((e as Error).message);
      await load();
    } finally {
      setBusy(false);
    }
  };
  return (
    <details className="outbound-panel">
      <summary>独立外部动作授权与回执</summary>
      <p className="muted">
        草稿审核和发送审核分别记录。发送目标固定为当前版本草稿中的收件人，不能由网页内容改变。
      </p>
      <ErrorBox error={error} />
      {!enabled ? (
        <Note>
          当前工作区关闭外发。请复制回复，在邮件工具中人工核对后发送，并在跟进计划中记录结果。
        </Note>
      ) : (
        <>
          <dl className="approval-binding">
            <div>
              <dt>发送目标</dt>
              <dd>{target || "草稿未指定收件人，禁止发送"}</dd>
            </div>
            <div>
              <dt>案件版本</dt>
              <dd>{text(caseData.version)}</dd>
            </div>
            <div>
              <dt>内容 hash</dt>
              <dd className="mono">{hash}</dd>
            </div>
          </dl>
          <label className="confirm-action">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <span>
              我已核对收件人、当前草稿及证据，并明确授权下面所选的邮件动作。
            </span>
          </label>
          <button
            className="button secondary"
            disabled={!target || !confirmed || busy}
            onClick={() => void requestApproval()}
          >
            申请此版本的发送审批
          </button>
          {eligible.map((a) => {
            const previous = receipts.find((r) => r.approval_id === id(a));
            return (
              <div key={id(a)} className="approved-send">
                <span>此版本已有独立发送审批。</span>
                <button
                  className="button"
                  disabled={!confirmed || busy || Boolean(previous)}
                  onClick={() => void send(a)}
                >
                  发送已批准的邮件
                </button>
                {previous && <Badge value={previous.status} />}
              </div>
            );
          })}
        </>
      )}
      {receipts.length > 0 && (
        <>
          <h3>持久回执</h3>
          {receipts.map((r) => (
            <article key={id(r)} className="receipt">
              <Badge value={r.status} />
              <span>{date(r.updated_at ?? r.created_at)}</span>
              {r.status === "DELIVERY_UNCERTAIN" && (
                <Note>
                  回执不确定，禁止自动重发。请先向提供商核对实际投递结果。
                </Note>
              )}
              {canReview && r.status === "PENDING" && (
                <form
                  onSubmit={async (event) => {
                    event.preventDefault();
                    setBusy(true);
                    setError("");
                    try {
                      await mutate(
                        `/outbound-actions/${encodeURIComponent(id(r))}/cancel`,
                        {
                          case_version: caseData.version,
                          reason: (cancelReasons[id(r)] || "").trim(),
                        },
                      );
                      await load();
                      onChange();
                    } catch (e) {
                      setError((e as Error).message);
                      await load();
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  <Field label="取消待执行动作的原因">
                    <input
                      required
                      maxLength={2000}
                      value={cancelReasons[id(r)] || ""}
                      onChange={(event) =>
                        setCancelReasons((current) => ({
                          ...current,
                          [id(r)]: event.target.value,
                        }))
                      }
                    />
                  </Field>
                  <button
                    className="button secondary"
                    type="submit"
                    disabled={busy || !(cancelReasons[id(r)] || "").trim()}
                  >
                    取消待执行动作
                  </button>
                  <p className="muted">
                    仅可取消尚未执行的动作；服务端再次校验权限、状态与案件版本。
                  </p>
                </form>
              )}
              <Details value={r} />
            </article>
          ))}
        </>
      )}
    </details>
  );
}

function CaseMetadata({
  caseData,
  prefix,
  onChange,
  related,
}: {
  caseData: Row;
  prefix: string;
  onChange: () => void;
  related: Row[];
}) {
  const [title, setTitle] = useState(text(caseData.title, "")),
    [priority, setPriority] = useState(Number(caseData.priority) || 0),
    [tags, setTags] = useState(
      Array.isArray(caseData.tags) ? caseData.tags.join(", ") : "",
    ),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const tagValue = Array.isArray(caseData.tags) ? caseData.tags.join(", ") : "";
  useEffect(() => {
    setTitle(text(caseData.title, ""));
    setPriority(Number(caseData.priority) || 0);
    setTags(Array.isArray(caseData.tags) ? caseData.tags.join(", ") : "");
  }, [caseData.title, caseData.priority, tagValue]);
  return (
    <details className="case-metadata">
      <summary>
        整理案件 · 标题、优先级与标签
        {related.length > 0 ? ` · ${related.length} 条关联询盘` : ""}
      </summary>
      <form
        className="metadata-form"
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError("");
          try {
            await mutate(
              prefix,
              {
                case_version: caseData.version,
                title,
                priority,
                tags: tags
                  .split(/[,，]/)
                  .map((v) => v.trim())
                  .filter(Boolean),
              },
              "PATCH",
            );
            onChange();
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field label="案件名称">
          <input
            required
            value={title}
            maxLength={300}
            onChange={(e) => setTitle(e.target.value)}
          />
        </Field>
        <Field label="优先级（0–100）">
          <input
            type="number"
            min={0}
            max={100}
            value={priority}
            onChange={(e) => setPriority(Number(e.target.value))}
          />
        </Field>
        <Field label="标签" hint="使用逗号分隔">
          <input
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="重点客户, 待确认规格"
            maxLength={1000}
          />
        </Field>
        <button className="button secondary" disabled={busy} type="submit">
          保存案件信息
        </button>
      </form>
      <ErrorBox error={error} />
      {related.length > 0 && (
        <div className="related-cases">
          <h3>可能关联的询盘</h3>
          <p className="muted">
            以下案件共享邮箱域名，仅为重复调查提示；尚未确认是同一企业，不会自动合并。
          </p>
          {related.map((c) => (
            <Link
              key={id(c)}
              className="source-record"
              href={`/cases/${id(c)}`}
            >
              <span>
                <strong>{text(c.title)}</strong>
                <small>
                  {scopeLabel(c.relation) === "shared_email_domain_unverified"
                    ? "同域名 · 身份未合并"
                    : text(c.relation)}
                </small>
              </span>
              <Badge value={c.status} />
            </Link>
          ))}
        </div>
      )}
    </details>
  );
}

function localInput(value: unknown): string {
  const dateValue = new Date(text(value, ""));
  if (Number.isNaN(dateValue.valueOf())) return "";
  return new Date(dateValue.getTime() - dateValue.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}
function KnowledgeLibrary() {
  const [entries, setEntries] = useState<Row[]>([]),
    [selected, setSelected] = useState<Row | null>(null),
    [editing, setEditing] = useState(false),
    [documentId, setDocumentId] = useState(""),
    [version, setVersion] = useState(0),
    [title, setTitle] = useState(""),
    [content, setContent] = useState(""),
    [scope, setScope] = useState("product"),
    [valid, setValid] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const scopeNames: Record<string, string> = {
    product: "产品资料",
    rules: "规则资料",
    business: "业务资料",
    email: "历史邮件",
  };
  const refresh = useCallback(async () => {
    try {
      setEntries(list(await api("/knowledge")));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  const groups = new Map<string, Row[]>();
  for (const entry of entries) {
    const current = groups.get(id(entry)) || [];
    current.push(entry);
    groups.set(id(entry), current);
  }
  for (const values of groups.values())
    values.sort((a, b) => Number(b.version) - Number(a.version));
  const view = async (identity: string, version: number) => {
    setBusy(true);
    setError("");
    try {
      setSelected(row(await api(`/knowledge/${identity}/${version}`)));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const startNew = () => {
    setDocumentId("");
    setVersion(0);
    setTitle("");
    setContent("");
    setScope("product");
    setValid(localInput(new Date(Date.now() + 30 * 86400000).toISOString()));
    setEditing(true);
    setError("");
  };
  const editSelected = () => {
    if (!selected) return;
    setDocumentId(id(selected));
    setVersion(Number(selected.version));
    setTitle(text(selected.title, ""));
    setContent(text(selected.content, ""));
    setScope(text(selected.scope, "product"));
    setValid(localInput(selected.valid_until));
    setEditing(true);
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const saved = row(
        await mutate("/knowledge", {
          title,
          content,
          scope,
          valid_until: new Date(valid).toISOString(),
          expected_version: version,
          ...(documentId ? { document_id: documentId } : {}),
        }),
      );
      setEditing(false);
      await refresh();
      await view(id(saved), Number(saved.version));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel content-panel knowledge-library">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">VERSIONED KNOWLEDGE</span>
          <h2>内部知识与规则版本</h2>
        </div>
        <button className="button secondary" onClick={startNew}>
          登记资料
        </button>
      </div>
      <p className="muted">
        资料用于提供背景，不自动成为案件证据，也不自动证明产品认证或法律合规。每个版本保留有效期、范围和内容
        hash。
      </p>
      <ErrorBox error={error} />
      {editing && (
        <form className="knowledge-form" onSubmit={submit}>
          <h3>
            {documentId ? `修订资料 · 当前版本 ${version}` : "登记新的内部资料"}
          </h3>
          <div className="form-grid">
            <Field label="资料标题">
              <input
                required
                maxLength={300}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </Field>
            <Field label="资料范围">
              <select value={scope} onChange={(e) => setScope(e.target.value)}>
                {Object.entries(scopeNames).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="有效期至（本地时区）">
              <input
                required
                type="datetime-local"
                value={valid}
                onChange={(e) => setValid(e.target.value)}
              />
            </Field>
            <Field
              label="导入文本文件（可选）"
              hint=".txt 或 .md，只读取文字；最大 100,000 字符。"
            >
              <input
                type="file"
                accept=".txt,.md"
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  try {
                    if (file.size > 400000)
                      throw new Error("文件太大，请缩减至 100,000 字符以内。");
                    const value = await file.text();
                    if (value.length > 100000)
                      throw new Error("内容超过 100,000 字符。");
                    setContent(value);
                    if (!title) setTitle(file.name);
                  } catch (error) {
                    setError((error as Error).message);
                  }
                }}
              />
            </Field>
          </div>
          <Field label="资料内容">
            <textarea
              required
              rows={8}
              value={content}
              maxLength={100000}
              onChange={(e) => setContent(e.target.value)}
            />
          </Field>
          <Note>
            保存后标记为「用户提供 · 尚未核实」。过期资料不能作为当前规则使用。
          </Note>
          <div className="button-row">
            <button className="button" disabled={busy} type="submit">
              保存资料版本
            </button>
            <button
              className="button secondary"
              type="button"
              onClick={() => setEditing(false)}
            >
              取消
            </button>
          </div>
        </form>
      )}
      {groups.size === 0 && !editing ? (
        <Empty title="尚未登记内部资料">
          登记产品说明、业务知识或规则依据，并为每一版设置有效期。
        </Empty>
      ) : (
        <div className="knowledge-list">
          {[...groups.entries()].map(([identity, versions]) => {
            const latest = versions[0];
            return (
              <article className="knowledge-row" key={identity}>
                <div>
                  <h3>{text(latest.title)}</h3>
                  <p>
                    {scopeNames[text(latest.scope)] || text(latest.scope)} ·{" "}
                    {versions.length} 个版本 · 有效期 {date(latest.valid_until)}
                  </p>
                  <span className="mini-label">用户提供 · 尚未核实</span>
                </div>
                <Badge value={latest.expired ? "EXPIRED" : "UNKNOWN"} />
                <select
                  aria-label={`知识版本 ${text(latest.title)}`}
                  defaultValue=""
                  disabled={busy}
                  onChange={(e) => {
                    if (e.target.value)
                      void view(identity, Number(e.target.value));
                  }}
                >
                  <option value="">查看版本…</option>
                  {versions.map((entry) => (
                    <option
                      key={String(entry.version)}
                      value={String(entry.version)}
                    >
                      版本 {text(entry.version)} · {date(entry.created_at)}
                    </option>
                  ))}
                </select>
              </article>
            );
          })}
        </div>
      )}
      {selected && (
        <section className="knowledge-reader">
          <div className="panel-heading">
            <div>
              <h3>
                {text(selected.title)} · 版本 {text(selected.version)}
              </h3>
              <p className="muted">
                用户提供 · 尚未核实 ·{" "}
                {selected.expired
                  ? "已过期"
                  : "截至 " + date(selected.valid_until)}
              </p>
            </div>
            {Number(selected.version) ===
              Number(groups.get(id(selected))?.[0]?.version) && (
              <button
                className="button secondary compact"
                onClick={editSelected}
              >
                修订当前版本
              </button>
            )}
          </div>
          <p className="mono">SHA256 {text(selected.content_hash)}</p>
          <pre className="snapshot">{text(selected.content)}</pre>
        </section>
      )}
    </section>
  );
}

function ManualSourceForm({
  caseData,
  prefix,
  onChange,
}: {
  caseData: Row;
  prefix: string;
  onChange: () => void;
}) {
  const [url, setUrl] = useState(""),
    [title, setTitle] = useState(""),
    [captured, setCaptured] = useState(""),
    [snapshot, setSnapshot] = useState(""),
    [excerpt, setExcerpt] = useState(""),
    [claim, setClaim] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [saved, setSaved] = useState(false);
  const key = useRef("");
  useEffect(() => {
    setCaptured(localInput(new Date().toISOString()));
    key.current = crypto.randomUUID();
  }, []);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setSaved(false);
    setError("");
    try {
      if (!snapshot.includes(excerpt))
        throw new Error("引用片段必须逐字出现在完整快照中。");
      await mutate(
        prefix + "/sources",
        {
          case_version: caseData.version,
          url,
          title,
          captured_at: new Date(captured).toISOString(),
          text: snapshot,
          excerpt,
          claim,
        },
        "POST",
        key.current,
      );
      key.current = crypto.randomUUID();
      setTitle("");
      setSnapshot("");
      setExcerpt("");
      setClaim("");
      setSaved(true);
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <details className="manual-source">
      <summary>补充人工采集的来源证据</summary>
      <p className="muted">
        适用于已获准保存的公开网页或官方记录。系统记录你提供的快照与引用，不将这次导入标记为在线抓取成功。
      </p>
      <form onSubmit={submit}>
        <div className="form-grid">
          <Field label="来源网页地址">
            <input
              required
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              maxLength={4096}
              placeholder="https://…"
            />
          </Field>
          <Field label="来源标题">
            <input
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={500}
            />
          </Field>
          <Field label="采集时间（本地时区）">
            <input
              required
              type="datetime-local"
              value={captured}
              onChange={(e) => setCaptured(e.target.value)}
            />
          </Field>
          <Field label="导入快照文本（可选）">
            <input
              type="file"
              accept=".txt,.md"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                try {
                  if (file.size > 400000) throw new Error("快照文件过大。");
                  const value = await file.text();
                  if (value.length > 100000)
                    throw new Error("快照不能超过 100,000 字符。");
                  setSnapshot(value);
                } catch (error) {
                  setError((error as Error).message);
                }
              }}
            />
          </Field>
        </div>
        <Field label="完整快照内容">
          <textarea
            required
            rows={5}
            maxLength={100000}
            value={snapshot}
            onChange={(e) => setSnapshot(e.target.value)}
          />
        </Field>
        <Field label="逐字引用片段">
          <textarea
            required
            rows={2}
            maxLength={4000}
            value={excerpt}
            onChange={(e) => setExcerpt(e.target.value)}
          />
        </Field>
        <Field label="需要核实的主张">
          <input
            required
            value={claim}
            onChange={(e) => setClaim(e.target.value)}
            maxLength={2000}
          />
        </Field>
        <Note>
          主张保留为待核实。新增证据会更新案件版本，使已有审核失效，需重新审查。
        </Note>
        <ErrorBox error={error} />
        {saved && (
          <div className="notice good" role="status">
            人工来源已保存；主张仍为待核实。
          </div>
        )}
        <button
          className="button secondary"
          type="submit"
          disabled={busy || caseData.status === "RESEARCHING"}
        >
          保存人工来源
        </button>
      </form>
    </details>
  );
}

function AdvancedReview({
  caseData,
  prefix,
  onChange,
}: {
  caseData: Row;
  prefix: string;
  onChange: () => void;
}) {
  const [input, setInput] = useState(""),
    [note, setNote] = useState(""),
    [rulesConfirmed, setRulesConfirmed] = useState(false),
    [confirmed, setConfirmed] = useState(false),
    [loaded, setLoaded] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [saved, setSaved] = useState(false),
    [lastArtifact, setLastArtifact] = useState("");
  const key = useRef("");
  useEffect(() => {
    key.current = crypto.randomUUID();
  }, []);
  const load = async () => {
    setBusy(true);
    setError("");
    try {
      const template = row(await api(prefix + "/review-inputs"));
      setInput(JSON.stringify(template.input, null, 2));
      setNote("");
      setRulesConfirmed(false);
      setConfirmed(false);
      setLoaded(true);
      setSaved(false);
      setLastArtifact(text(template.last_review_artifact_id, ""));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const payload = row(JSON.parse(input));
      await mutate(
        prefix + "/review-inputs",
        {
          ...payload,
          review_note: note,
          current_rules_confirmed: rulesConfirmed,
        },
        "POST",
        key.current,
      );
      setSaved(true);
      setConfirmed(false);
      key.current = crypto.randomUUID();
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const recompute = async () => {
    setBusy(true);
    setError("");
    try {
      await mutate(prefix + "/run");
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <details
      className="advanced-review"
      onToggle={(event) => {
        if (event.currentTarget.open && !loaded && !busy) void load();
      }}
    >
      <summary>高级人工复核 · 企业身份、评分依据与规则适用</summary>
      <p className="muted">
        仅供具有审核权限的人员使用。基于已保存的来源逐项判断实体、引用和规则，记录复核版本；不会自动生成认证、法律结论或发送授权。
      </p>
      <Note>
        先打开原始来源核对引用。每条来源的「许可已确认」和「来源角色已确认」默认均为
        false，必须在结构化输入中逐条明确确认。资料不充分时，保留 unverified /
        unknown。
      </Note>
      <div className="review-guide">
        <h3>字段与引用说明</h3>
        <dl>
          <div>
            <dt>candidates / profile</dt>
            <dd>
              候选企业与买家资料。同名不能直接合并，国家和域名冲突需保留。
            </dd>
          </div>
          <div>
            <dt>evidence_bindings</dt>
            <dd>
              已有主张和来源的引用 ID。source_permission_confirmed
              表示来源许可已核对，source_role_confirmed
              表示其官方/注册库等身份已核对。
            </dd>
          </div>
          <div>
            <dt>signals / rules</dt>
            <dd>
              评分信号与规则的依据，引用 evidence_id
              别名。规则需要适用范围、来源版本和有效日期。
            </dd>
          </div>
          <div>
            <dt>seller_context</dt>
            <dd>
              已核实的卖方资料和允许/禁止的商务表述，不填写无依据的认证与承诺。
            </dd>
          </div>
        </dl>
      </div>
      <ErrorBox error={error} />
      {loaded && (
        <form onSubmit={submit}>
          <Field
            label="高级复核输入（JSON）"
            hint={`已加载的输入自带 Case 版本，当前案件版本为 ${text(caseData.version)}。如出现冲突，请先重新加载。`}
          >
            <textarea
              className="review-json"
              rows={16}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                setSaved(false);
              }}
              spellCheck={false}
              maxLength={500000}
            />
          </Field>
          <Field label="人工复核说明">
            <textarea
              required
              rows={3}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={4000}
              placeholder="说明核对过的来源、身份判断、评分依据及仍有的不确定项。"
            />
          </Field>
          <label className="confirm-action">
            <input
              type="checkbox"
              checked={rulesConfirmed}
              onChange={(e) => setRulesConfirmed(e.target.checked)}
            />
            <span>我已确认标为现行的官方规则的来源、适用范围与有效日期。</span>
          </label>
          <label className="confirm-action">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <span>
              我已逐条核对引用与权限，并对本次人工判断负责。未确认的事项保持未知。
            </span>
          </label>
          <div className="button-row">
            <button
              className="button secondary"
              disabled={busy || !confirmed || !note.trim()}
              type="submit"
            >
              保存人工复核版本
            </button>
            <button
              className="text-button"
              type="button"
              disabled={busy}
              onClick={() => void load()}
            >
              重新加载当前输入
            </button>
            <button
              className="text-button"
              type="button"
              onClick={() =>
                navigator.clipboard
                  .writeText(input)
                  .catch(() =>
                    setError("剪贴板不可用，请手动选择 JSON 并复制。"),
                  )
              }
            >
              复制引用与复核输入
            </button>
          </div>
        </form>
      )}
      {lastArtifact && (
        <p className="mono muted">上一复核记录 {lastArtifact}</p>
      )}
      {saved && (
        <div className="notice good" role="status">
          <span>
            人工复核版本已保存，旧审批已失效。请重新计算案件以应用审核结果。
          </span>
          <button
            className="button secondary compact"
            disabled={busy}
            onClick={() => void recompute()}
          >
            重新计算案件
          </button>
        </div>
      )}
    </details>
  );
}
