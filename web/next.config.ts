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
/**
 * Where the API actually is, with its scheme made certain.
 *
 * **This one line cost a live customer flow.** On the deployment the variable was set to a bare hostname, so
 * the rewrite destination was built as `http://...` - and a platform cannot proxy plaintext to a service that
 * serves TLS, so it answered **307** instead of proxying. The browser followed the redirect, the request body
 * was gone by the time it arrived, and the API refused it as `INVALID_REQUEST`: a customer pressed "Send my
 * list" and got a failure, on a shop that worked perfectly when called directly.
 *
 * A missing scheme is a mistake waiting to be made by whoever sets the variable next, so it is corrected here
 * rather than in a deployment instruction nobody reads at the moment they need it.
 */
//: The deployed API, used when this is a deployed build and the variable is missing or empty. Written here
//: because a deployment whose variable was never set falls back to `localhost` - which is not a configuration
//: mistake a customer should ever experience, and the exact thing that made "Send my list" fail in production.
const DEPLOYED_API = "https://p01--ahia-api--qw5xhkblp8hy.code.run";

function withScheme(target: string): string {
  const trimmed = target.trim().replace(/\/+$/, "");
  if (trimmed === "") {
    // On Vercel, the API is remote. Locally, it is on this machine.
    return process.env.VERCEL ? DEPLOYED_API : "http://127.0.0.1:8000";
  }
  // Anything that is not already a scheme is treated as a hostname, and a deployed hostname is TLS: the API
  // refuses plaintext and the platform refuses to proxy it.
  const withProtocol = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  // And plaintext to anything that is not this machine is raised to TLS rather than honoured. A remote API
  // reachable only over `http://` does not exist in this deployment, so the only thing that value can produce
  // is the failure this function was written for.
  const isLocal = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/i.test(withProtocol);
  return !isLocal && withProtocol.startsWith("http://")
    ? `https://${withProtocol.slice("http://".length)}`
    : withProtocol;
}

const API_PROXY_TARGET = withScheme(process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000");

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
    ];
  },
};

export default nextConfig;
