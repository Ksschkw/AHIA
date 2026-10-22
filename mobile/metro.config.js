// Learn more https://docs.expo.io/guides/customizing-metro
const { getDefaultConfig } = require("expo/metro-config");
const http = require("http");
const https = require("https");

/** @type {import('expo/metro-config').MetroConfig} */
const config = getDefaultConfig(__dirname);

if (!config.resolver.assetExts.includes("wasm")) {
  config.resolver.assetExts.push("wasm");
}

const TARGET_API = process.env.API_PROXY_TARGET || "https://p01--ahia-api--qw5xhkblp8hy.code.run";

config.server = {
  ...config.server,
  enhanceMiddleware: (metroMiddleware) => {
    return (req, res, next) => {
      const url = req.url || "";
      if (url.startsWith("/api/") || url.startsWith("/shop/")) {
        try {
          const targetUrl = new URL(TARGET_API);
          const isHttps = targetUrl.protocol === "https:";
          const client = isHttps ? https : http;

          const headers = { ...req.headers };
          headers.host = targetUrl.host;
          delete headers.origin;
          delete headers.referer;

          const proxyReq = client.request(
            {
              protocol: targetUrl.protocol,
              hostname: targetUrl.hostname,
              port: targetUrl.port || (isHttps ? 443 : 80),
              method: req.method,
              path: url,
              headers,
            },
            (proxyRes) => {
              res.writeHead(proxyRes.statusCode || 500, proxyRes.headers);
              proxyRes.pipe(res, { end: true });
            }
          );

          proxyReq.on("error", (err) => {
            if (!res.headersSent) {
              res.writeHead(502, { "Content-Type": "application/json" });
              res.end(JSON.stringify({ error: { message: "API proxy error: " + err.message } }));
            }
          });

          req.pipe(proxyReq, { end: true });
          return;
        } catch (e) {
          if (!res.headersSent) {
            res.writeHead(500, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ error: { message: "Proxy configuration error" } }));
          }
          return;
        }
      }
      return metroMiddleware(req, res, next);
    };
  },
};

module.exports = config;
