import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Lifted from counseling-graph-cscl pattern: GH Pages deploys under
// /discourse-lens/, local dev stays at /. envDir set explicitly to avoid the
// known Vite gotcha where root != project root silently swallows VITE_* vars.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  envDir: __dirname,
  base: mode === "ghpages" ? "/discourse-lens/" : "/",
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  define: {
    __STATIC_MODE__: JSON.stringify(mode === "ghpages"),
  },
  server: {
    port: 5173,
  },
  build: {
    outDir: path.resolve(__dirname, "dist"),
    emptyOutDir: true,
  },
}));
