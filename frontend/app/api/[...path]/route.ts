import { NextRequest } from "next/server";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
const LIMIT = 11 * 1024 * 1024;
async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  if (
    path.some(
      (part) =>
        part === "." ||
        part === ".." ||
        part.includes("/") ||
        part.includes("\\"),
    )
  ) {
    return Response.json({ detail: "Invalid API path" }, { status: 400 });
  }
  const base = new URL(
    process.env.TRADECASE_API_URL || "http://127.0.0.1:8000",
  );
  if (
    !["http:", "https:"].includes(base.protocol) ||
    base.username ||
    base.password
  ) {
    return Response.json(
      { detail: "API origin configuration is invalid" },
      { status: 503 },
    );
  }
  const target = new URL(
    "/api/" + path.map(encodeURIComponent).join("/") + request.nextUrl.search,
    base,
  );
  const headers = new Headers();
  for (const name of [
    "authorization",
    "content-type",
    "accept",
    "idempotency-key",
    "last-event-id",
  ]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    let body: ArrayBuffer | undefined;
    if (!["GET", "HEAD"].includes(request.method)) {
      if (Number(request.headers.get("content-length") || 0) > LIMIT) {
        return Response.json(
          { detail: "Upload exceeds 10 MiB" },
          { status: 413 },
        );
      }
      const chunks: Uint8Array[] = [];
      let bytes = 0;
      const reader = request.body?.getReader();
      if (reader) {
        while (true) {
          const next = await reader.read();
          if (next.done) break;
          bytes += next.value.byteLength;
          if (bytes > LIMIT) {
            await reader.cancel();
            return Response.json(
              { detail: "Upload exceeds 10 MiB" },
              { status: 413 },
            );
          }
          chunks.push(next.value);
        }
      }
      const merged = new Uint8Array(bytes);
      let offset = 0;
      for (const chunk of chunks) {
        merged.set(chunk, offset);
        offset += chunk.length;
      }
      body = merged.buffer;
    }
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "error",
      signal: request.signal,
    });
    const responseHeaders = new Headers({
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    });
    for (const name of [
      "content-type",
      "content-disposition",
      "x-accel-buffering",
    ]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch {
    return Response.json(
      { detail: "无法连接业务服务。请检查 API 地址和服务状态。" },
      { status: 502 },
    );
  }
}
export {
  proxy as GET,
  proxy as POST,
  proxy as PATCH,
  proxy as PUT,
  proxy as DELETE,
  proxy as HEAD,
};
