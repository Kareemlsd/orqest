import type { NextConfig } from "next";

/**
 * Backend origin resolution:
 *  - In docker-compose the backend is reachable as `polymath-backend:8000`.
 *  - For local dev (npm run dev on host), fall back to localhost:8000.
 *  - Overridable via BACKEND_URL (server) / NEXT_PUBLIC_BACKEND_URL (client).
 */
const backendUrl =
  process.env.BACKEND_URL ??
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/backend/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
