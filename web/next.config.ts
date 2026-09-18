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
  // The floating development indicator is a tool for the person writing the code, and it sits on top
  // of the interface for everybody else. Turned off rather than explained away: it never appears in a
  // production build, so nothing is hidden by doing so.
  devIndicators: false,

  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_PROXY_TARGET}/api/:path*`,
      },
      {
        // **One path, not the whole prefix.** `/shop/:path*` proxied every request under it, including
        // the pages themselves - so a customer opening the link a trader sent them got the API's raw
        // JSON instead of the shop, and the shopfront was broken in production while every check that
        // did not look at the content type stayed green. The only thing the browser needs from the API
        // under this prefix is the list a customer sends.
        source: "/shop/:slug/requests",
        destination: `${API_PROXY_TARGET}/shop/:slug/requests`,
      },
    ];
  },
};

export default nextConfig;
