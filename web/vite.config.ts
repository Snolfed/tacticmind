/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The built interface goes into the Python package (tacticmind/web/static), so the game
// runs with `python main.py` without Node.js. In `npm run dev` mode, /api and /fonts requests
// go to the Python server started with `python main.py --no-window`.
const backend = "http://127.0.0.1:8517";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../tacticmind/web/static",
    emptyOutDir: true,
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 800,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/fonts": { target: backend, changeOrigin: true },
    },
  },
  test: {
    environment: "node",
  },
});
