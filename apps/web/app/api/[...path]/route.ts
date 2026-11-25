import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { lastHop } from "@/lib/clientIp";

const API = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
const HOP = new Set(["connection", "keep-alive", "transfer-encoding", "content-encoding", "content-length"]);
const MAX_BODY = 26_214_400; // the same ceiling as the API (MAX_BODY_BYTES, 25 MB)
const BLOCKED = ["/api/auth/login", "/api/webhooks", "/api/tools"];

/** The request body, read with a ceiling, so a caller cannot stream gigabytes into this server. Returns null when the body is too large. */
async function readCapped(request: Request): Promise<ArrayBuffer | null> {
  const declared = request.headers.get("content-length");
  if (declared !== null && !(Number(declared) <= MAX_BODY)) return null;
  if (!request.body) return new ArrayBuffer(0);
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_BODY) { await reader.cancel(); return null; }
    chunks.push(value);
  }
  const out = new Uint8Array(total);
  let at = 0;
  for (const c of chunks) { out.set(c, at); at += c.byteLength; }
  return out.buffer;
}

/** Forward /api/* to the private API. Adds the session from the cookie. Mutations need the x-booklantern header, which a cross site page cannot send. */
async function forward(request: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  // Normalise the path first (a segment such as ".." would otherwise slip past the checks and be resolved later, on the way to the API), then check it.
  const target = new URL("/api/" + path.join("/"), "http://local.invalid").pathname;
  if (!target.startsWith("/api/") || BLOCKED.some((b) => target === b || target.startsWith(b + "/"))) return NextResponse.json({ error: { message: "Not found." } }, { status: 404 });
  if (!["GET", "HEAD"].includes(request.method) && request.headers.get("x-booklantern") !== "1") {
    return NextResponse.json({ error: { message: "Missing request header." } }, { status: 400 });
  }
  const token = (await cookies()).get("sx_session")?.value;
  if (!token) return NextResponse.json({ error: { message: "Sign in to continue." } }, { status: 401 }); // before any body is read
  const url = new URL(request.url);
  // One connection per request: the API closes the connection after it answers an unexpected error, and a pooled socket reused right after
  // it made the next request fail with a 502.
  const headers: Record<string, string> = { accept: request.headers.get("accept") ?? "*/*", connection: "close" };
  const ct = request.headers.get("content-type");
  if (ct) headers["content-type"] = ct;
  const fn = request.headers.get("x-filename");
  if (fn) headers["x-filename"] = fn.slice(0, 200);
  if (token) headers["x-session"] = token;
  const ip = lastHop(request.headers.get("x-forwarded-for"));
  if (ip) headers["x-forwarded-for"] = ip;
  const body = ["GET", "HEAD"].includes(request.method) ? undefined : await readCapped(request);
  if (body === null) return NextResponse.json({ error: { message: "The request is too large." } }, { status: 413 });
  const send = () => fetch(`${API}${target}${url.search}`, {
    method: request.method, headers, body, signal: request.signal, cache: "no-store",
  });
  let upstream: Response;
  try {
    try {
      upstream = await send();
    } catch (first) {
      if (request.signal.aborted || !["GET", "HEAD"].includes(request.method)) throw first;
      upstream = await send(); // a reading request is safe to repeat once if the connection was closed under it
    }
  } catch {
    return NextResponse.json({ error: { message: "The server is not reachable. Check that the API is running." } }, { status: 502 });
  }
  const out = new Headers();
  upstream.headers.forEach((v, k) => { if (!HOP.has(k.toLowerCase())) out.set(k, v); });
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { forward as GET, forward as POST, forward as PUT, forward as PATCH, forward as DELETE };
export const dynamic = "force-dynamic";
