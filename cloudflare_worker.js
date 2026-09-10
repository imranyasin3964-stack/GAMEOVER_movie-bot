/**
 * 🌐 GameOver Cloud Cinema API — Cloudflare Edge Reverse Proxy Worker
 * 
 * Instructions:
 * 1. Go to https://dash.cloudflare.com -> Workers & Pages -> Create Application -> Create Worker.
 * 2. Name your worker (e.g., "gameover-cinema-api").
 * 3. Replace all default code in the worker editor with THIS file content.
 * 4. Change BACKEND_ORIGIN to your VPS IP and Port (e.g., "http://123.45.67.89:8000").
 * 5. Click "Deploy".
 * 6. (Optional) In Worker Settings -> Triggers -> Custom Domains, attach your domain (e.g. "api.yourdomain.com").
 */

// ⚙️ LINODE VPS HOSTNAME (sslip.io converts IP to valid DNS hostname so Cloudflare Error 1003 is bypassed)
const BACKEND_ORIGIN = "http://172.104.38.31.sslip.io:8000";

// CORS Headers so any website, app, or player can access the API
const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
  "Access-Control-Max-Age": "86400",
};

export default {
  async fetch(request, env, ctx) {
    // 1. Handle Pre-flight CORS OPTIONS requests
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: CORS_HEADERS,
      });
    }

    const url = new URL(request.url);
    const targetUrl = new URL(url.pathname + url.search, BACKEND_ORIGIN);

    // 2. Clone headers and forward to VPS
    const newHeaders = new Headers(request.headers);
    newHeaders.set("X-Forwarded-Host", url.hostname);
    newHeaders.set("X-Real-IP", request.headers.get("cf-connecting-ip") || "");
    newHeaders.set("Host", targetUrl.host);

    const fetchOptions = {
      method: request.method,
      headers: newHeaders,
      redirect: "manual", // Handle 302 stream redirects cleanly
    };

    if (request.method !== "GET" && request.method !== "HEAD") {
      fetchOptions.body = request.body;
    }

    try {
      const response = await fetch(targetUrl.toString(), fetchOptions);

      // 3. Handle 302 Redirect for video streaming (instant playback)
      if (response.status === 301 || response.status === 302) {
        const location = response.headers.get("location");
        const redirectHeaders = new Headers(CORS_HEADERS);
        redirectHeaders.set("Location", location);
        return new Response(null, {
          status: 302,
          headers: redirectHeaders,
        });
      }

      // 4. Return response with CORS headers and Edge Caching
      const responseHeaders = new Headers(response.headers);
      Object.entries(CORS_HEADERS).forEach(([k, v]) => responseHeaders.set(k, v));

      // Cache search & metadata results at Cloudflare Edge for 60 seconds
      if (url.pathname.includes("/api/v1/search") || url.pathname.includes("/api/v1/details")) {
        responseHeaders.set("Cache-Control", "public, max-age=60, s-maxage=300");
      }

      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: responseHeaders,
      });

    } catch (err) {
      return new Response(
        JSON.stringify({
          success: false,
          error: "Cloudflare Reverse Proxy failed to connect to VPS backend. Please ensure the FastAPI server is running on port 8000.",
          details: err.message,
        }),
        {
          status: 502,
          headers: {
            "Content-Type": "application/json",
            ...CORS_HEADERS,
          },
        }
      );
    }
  },
};
