/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import http from "node:http";
import path from "node:path";

// The dev proxy must not pool sockets to the backend. Uvicorn closes an idle keep-alive connection
// after five seconds; the proxy, not being told, hands the next request to that socket as it dies and
// the browser gets `ECONNRESET` instead of an answer. It shows up exactly where it hurts most — a
// page polling an interview that has just gone quiet, where the gap between requests finally exceeds
// the server's patience. A fresh socket per request costs nothing in development and removes the
// whole race.
const noKeepAlive = new http.Agent({ keepAlive: false });

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      ["/api", "/dl", "/git"].map((prefix) => [
        prefix,
        { target: process.env.VITE_API_URL || "http://localhost:8100", changeOrigin: true, agent: noKeepAlive },
      ]),
    ),
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test/setup.ts"], exclude: ["e2e/**", "node_modules/**", "dist/**"] },
});
