/// <reference types="vitest/config" />
import { defineConfig, type Plugin } from "vite";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// Ship PDF.js fonts/CMaps/decoders locally; previews must also work offline.
function pdfAssets(): Plugin {
  const directory = fileURLToPath(new URL("./node_modules/pdfjs-dist/", import.meta.url));
  const folders = ["cmaps", "standard_fonts", "wasm"];
  return {
    name: "pdfjs-assets",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const match = /^\/pdfjs\/(cmaps|standard_fonts|wasm)\/([\w.-]+)$/.exec(request.url?.split("?")[0] ?? "");
        if (!match || match[2] === "." || match[2] === "..") return next();
        try {
          const content = readFileSync(`${directory}${match[1]}/${match[2]}`);
          response.setHeader("Content-Type", match[2].endsWith(".wasm") ? "application/wasm" : "application/octet-stream");
          response.end(content);
        } catch { next(); }
      });
    },
    generateBundle() {
      for (const folder of folders) for (const filename of readdirSync(`${directory}${folder}`)) {
        this.emitFile({ type: "asset", fileName: `pdfjs/${folder}/${filename}`, source: readFileSync(`${directory}${folder}/${filename}`) });
      }
    },
  };
}
import react from "@vitejs/plugin-react";

const host = process.env.TAURI_DEV_HOST;

// Tauri expects a fixed dev port and leaves the Rust console uncleared.
export default defineConfig({
  plugins: [react(), pdfAssets()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
    watch: { ignored: ["**/src-tauri/**"] },
  },
  envPrefix: ["VITE_", "TAURI_ENV_"],
  build: {
    target: "es2022",
    sourcemap: !!process.env.TAURI_ENV_DEBUG,
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
