import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// npm run dev: this dev server on :5173, API calls forwarded to the backend on :8000.
// npm run build: the app in dist/, served by the backend itself.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
});
