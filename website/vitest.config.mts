import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src"), "server-only": path.resolve(__dirname, "unit/server-only.ts") } },
  test: {
    environment: "jsdom",
    include: ["unit/**/*.test.{ts,tsx}"],
    setupFiles: ["unit/setup.ts"],
    restoreMocks: true,
  },
});
