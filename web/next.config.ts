import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: {
    optimizePackageImports: ["lucide-react", "@assistant-ui/react"],
  },
  allowedDevOrigins:["127.0.0.1",'192.168.11.118','localhost'],
};

export default nextConfig;
