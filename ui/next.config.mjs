/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export: no runtime Node process — the build output (out/) is served by the central
  // Spring server's static resources (ADR-0004: one JVM in production).
  output: 'export',
};

export default nextConfig;
