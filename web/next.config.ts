import type { NextConfig } from "next";

/**
 * The web app talks to the API on its own origin.
 *
 * `/api/...` is proxied to the backend, which is what makes the session cookie work: a cookie is
 * attached by the browser on requests to the origin that set it, and `localhost:3000` calling
 * `127.0.0.1:8000` is a *different site* - so a `SameSite=Lax` cookie is simply not sent, every
 * request arrives signed out, and the API answers 401. Proxying removes CORS, preflights and the
 * cross-site cookie problem in one move, and it is how the app is deployed behind one hostname too.
 *
 * Override the destination with `API_PROXY_TARGET` when the API is somewhere else.
 */
const API_PROXY_TARGET = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_PROXY_TARGET}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
