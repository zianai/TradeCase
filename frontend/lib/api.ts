export type Row = Record<string, unknown>;
export function row(value: unknown): Row {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Row)
    : {};
}
export function rows(value: unknown): Row[] {
  return Array.isArray(value) ? value.map(row) : [];
}
export function list(value: unknown): Row[] {
  if (Array.isArray(value)) return rows(value);
  const data = row(value);
  for (const key of [
    "items",
    "cases",
    "approvals",
    "tasks",
    "artifacts",
    "follow_ups",
    "events",
    "risks",
    "sources",
  ]) {
    if (Array.isArray(data[key])) return rows(data[key]);
  }
  return [];
}
export function text(value: unknown, fallback = "—"): string {
  if (value === undefined || value === null || value === "") return fallback;
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
export function id(value: Row): string {
  return text(
    value.id ?? value.case_id ?? value.task_id ?? value.approval_id,
    "",
  );
}
export function date(value: unknown): string {
  if (!value) return "未设定";
  const parsed = new Date(String(value));
  return Number.isNaN(parsed.valueOf())
    ? String(value)
    : parsed.toLocaleString("zh-CN", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
function token() {
  return typeof window === "undefined"
    ? ""
    : sessionStorage.getItem("tradecase-token") || "";
}
export async function api<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (token()) headers.set("Authorization", "Bearer " + token());
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch("/api" + path, {
    ...options,
    headers,
    cache: "no-store",
  });
  const body = response.headers
    .get("content-type")
    ?.includes("application/json")
    ? await response.json().catch(() => null)
    : await response.text();
  if (!response.ok) {
    const detail = row(body).detail;
    const message = Array.isArray(detail)
      ? detail
          .map((value) => {
            const error = row(value);
            return `${Array.isArray(error.loc) ? error.loc.join(".") : "输入"}: ${text(error.msg, "参数不符合要求")}`;
          })
          .join("；")
          .slice(0, 2000)
      : text(detail, "请求失败（" + response.status + "）").slice(0, 2000);
    throw new ApiError(
      response.status,
      response.status === 401
        ? "需要有效的工作区访问令牌。请在连接设置中登录。"
        : response.status === 409
          ? "操作未应用，请核对当前版本与质量门禁：" + message
          : message,
    );
  }
  return body as T;
}
export function mutate<T = unknown>(
  path: string,
  body: unknown = {},
  method = "POST",
  key?: string,
) {
  return api<T>(path, {
    method,
    headers: { "Idempotency-Key": key || crypto.randomUUID() },
    body: JSON.stringify(body),
  });
}
export async function download(path: string, filename: string) {
  const headers = new Headers();
  if (token()) headers.set("Authorization", "Bearer " + token());
  const response = await fetch("/api" + path, { headers, cache: "no-store" });
  if (!response.ok)
    throw new ApiError(response.status, "导出失败，请刷新后重试。");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
export async function streamCaseEvents(
  caseId: string,
  after: number,
  onEvent: (event: Row) => void,
  signal: AbortSignal,
) {
  let cursor = after;
  while (!signal.aborted) {
    const headers = new Headers({
      Accept: "text/event-stream",
      "Last-Event-ID": String(cursor),
    });
    if (token()) headers.set("Authorization", "Bearer " + token());
    // Cancel an established stream through its reader. Aborting fetch after
    // headers can also reject the browser's internal stream promises (WebKit).
    const connection = new AbortController();
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    const cancel = () => {
      if (reader) void reader.cancel().catch(() => {});
      else connection.abort();
    };
    signal.addEventListener("abort", cancel, { once: true });
    if (signal.aborted) cancel();
    try {
      const response = await fetch(
        `/api/cases/${encodeURIComponent(caseId)}/events`,
        { headers, signal: connection.signal, cache: "no-store" },
      );
      if (
        response.status === 401 ||
        response.status === 403 ||
        response.status === 404
      )
        return;
      if (
        !response.ok ||
        !response.body ||
        !response.headers.get("content-type")?.includes("text/event-stream")
      )
        throw new Error("Event connection unavailable");
      reader = response.body.getReader();
      void reader.closed.catch(() => {});
      const decoder = new TextDecoder();
      let buffer = "";
      try {
        while (!signal.aborted) {
          const next = await reader.read();
          if (next.done || signal.aborted) break;
          buffer += decoder
            .decode(next.value, { stream: true })
            .replace(/\r\n/g, "\n");
          let end;
          while ((end = buffer.indexOf("\n\n")) >= 0) {
            const block = buffer.slice(0, end);
            buffer = buffer.slice(end + 2);
            const data = block
              .split("\n")
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trimStart())
              .join("\n");
            if (data) {
              try {
                const event = row(JSON.parse(data));
                cursor = Math.max(cursor, Number(event.sequence) || 0);
                onEvent(event);
              } catch {
                /* Durable polling recovers malformed events. */
              }
            }
          }
        }
      } finally {
        await reader.cancel().catch(() => {});
        reader.releaseLock();
      }
    } catch {
      if (signal.aborted) return;
    } finally {
      signal.removeEventListener("abort", cancel);
    }
    // Server streams are bounded. Reconnect from the durable sequence, not zero.
    await new Promise<void>((resolve) => {
      const timer = setTimeout(done, 2000);
      function done() {
        clearTimeout(timer);
        signal.removeEventListener("abort", done);
        resolve();
      }
      signal.addEventListener("abort", done, { once: true });
      if (signal.aborted) done();
    });
  }
}
