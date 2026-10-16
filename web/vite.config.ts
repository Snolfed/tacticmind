/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Zbudowany interfejs trafia do pakietu Pythona (tacticmind/web/static), więc gra
// działa po `python main.py` bez Node.js. W trybie `npm run dev` zapytania /api i /fonts
// idą do serwera Pythona uruchomionego poleceniem `python main.py --no-window`.
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
