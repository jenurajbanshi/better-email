import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During dev, proxy API calls to the FastAPI backend so the SPA and API share
// an origin (keeps CORS simple and mirrors the single-container prod deploy).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
