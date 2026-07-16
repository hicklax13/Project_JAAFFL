import { crx } from "@crxjs/vite-plugin";
import { defineConfig } from "vite";

import manifest from "./manifest.json";

// UNVERIFIED/risk (plan §5.3): @crxjs has historically been rough with "world":"MAIN" +
// document_start static entries. If the emitted dist/manifest.json drops either, fall
// back to WXT or the service-worker dynamic registration (plan-B, scripting permission).
export default defineConfig({
  plugins: [crx({ manifest })],
  build: { outDir: "dist", target: "esnext", sourcemap: true },
  server: { port: 5173, strictPort: true, hmr: { port: 5173 } },
});
