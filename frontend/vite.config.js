import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the API routes to FastAPI (localhost:8000). In production
// FastAPI serves the built dist/ same-origin, so relative API paths just work.
const API = "http://localhost:8000";
const proxy = Object.fromEntries(
  ["/jobs", "/reports", "/metrics", "/audit", "/health"].map((p) => [p, API])
);

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  build: { outDir: "dist", emptyOutDir: true },
});
