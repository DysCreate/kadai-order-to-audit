/**
 * Cloudflare Worker that serves the built SPA and forwards `/api/*` to the
 * Django service on Render.
 *
 * - Only `/api/*` is proxied; every other path is handled by the static-asset
 *   binding, so the Worker never becomes an open proxy.
 * - `X-Real-IP` is set from Cloudflare's `CF-Connecting-IP`. Without it every
 *   visitor reaches Django through one Render proxy address and the login
 *   throttle would share a single rate-limit bucket.
 * - Upstream and network errors return a JSON 502 instead of an HTML error
 *   page, because these routes are consumed as an API.
 */

interface Env {
  /** Origin of the Django service, e.g. https://kadai-api.onrender.com */
  API_ORIGIN: string;
  /** Must match TRUSTED_PROXY_SECRET on Django; set with `wrangler secret put`. */
  TRUSTED_PROXY_SECRET?: string;
}

/** Responses from the API are sensitive (session cookies, invoices). */
function withApiHeaders(response: Response): Response {
  const headers = new Headers(response.headers);
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("Cache-Control", "no-store");
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function jsonError(status: number, detail: string): Response {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname !== "/api" && !url.pathname.startsWith("/api/")) {
      return jsonError(404, "Not found.");
    }

    let apiOrigin: URL;
    try {
      apiOrigin = new URL(env.API_ORIGIN);
    } catch {
      return jsonError(502, "The API is not configured.");
    }
    // Refuse to send session cookies and credentials over cleartext.
    if (apiOrigin.protocol !== "https:" && apiOrigin.hostname !== "localhost") {
      return jsonError(502, "The API must be configured with HTTPS.");
    }

    const target = new URL(url.pathname + url.search, apiOrigin);
    const headers = new Headers(request.headers);
    const clientIp = request.headers.get("CF-Connecting-IP");
    if (clientIp) {
      headers.set("X-Real-IP", clientIp);
    } else {
      headers.delete("X-Real-IP");
    }
    if (env.TRUSTED_PROXY_SECRET) {
      headers.set("X-Kadai-Proxy-Secret", env.TRUSTED_PROXY_SECRET);
    } else {
      headers.delete("X-Kadai-Proxy-Secret");
    }
    headers.set("X-Forwarded-Proto", "https");
    headers.set("X-Forwarded-Host", url.host);

    let upstream: Response;
    try {
      upstream = await fetch(target, {
        method: request.method,
        headers,
        body:
          request.method === "GET" || request.method === "HEAD"
            ? undefined
            : request.body,
        redirect: "manual",
      });
    } catch {
      return jsonError(502, "The API is unavailable. Please try again.");
    }

    return withApiHeaders(upstream);
  },
};
