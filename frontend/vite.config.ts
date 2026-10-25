import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Fejlesztéskor (npm run dev) a backend a WSL-ben fut (localhost:8070); élesben a FastAPI szolgálja ki a dist-et.
const api = process.env.API_URL ?? "http://localhost:8070";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": api, "/files": api, "/images": api, "/health": api },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
