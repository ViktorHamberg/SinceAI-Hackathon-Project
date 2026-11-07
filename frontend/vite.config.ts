import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

const backendPort = process.env.FORECAST_API_PORT ?? '8000';
if (!/^\d+$/.test(backendPort) || Number(backendPort) < 1 || Number(backendPort) > 65535) {
  throw new Error('FORECAST_API_PORT must be an integer port from 1 to 65535.');
}
const proxy = { '/api': { target: `http://127.0.0.1:${Number(backendPort)}` } };
const root = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig({
  root,
  plugins: [react()],
  server: {
    host: '127.0.0.1', port: 5173, strictPort: true, proxy,
    fs: {
      strict: true, allow: [root],
      deny: ['.env', '.env.*', '*.{crt,pem}', '**/.git/**', '**/data/**', '**/baseline_output/**'],
    },
  },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy },
  test: { environment: 'jsdom', setupFiles: ['./src/test/setup.ts'], maxWorkers: 2 },
});
