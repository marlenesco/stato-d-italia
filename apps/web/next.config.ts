import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  turbopack: { root: path.resolve(__dirname) },
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;
