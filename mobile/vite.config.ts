import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import mkcert from 'vite-plugin-mkcert';

declare const process: { env: Record<string, string | undefined> };

export default defineConfig(({ command }) => ({
  plugins: [
    react(),
    ...(command === 'serve' && process.env.NODE_ENV !== 'test' ? [mkcert()] : []),
  ],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
  envDir: '../',   // read .env from repo root, same file as the backend uses
  server: {
    host: true,
    port: 5174,
    proxy: {
      '/chat': { target: 'http://localhost:8000', changeOrigin: true },
      '/audio': { target: 'http://localhost:8000', changeOrigin: true },
      '/settings': { target: 'http://localhost:8000', changeOrigin: true },
      '/debug': { target: 'http://localhost:8000', changeOrigin: true },
      '/health': { target: 'http://localhost:8000', changeOrigin: true },
      '/events': { target: 'http://localhost:8000', changeOrigin: true },
      '/achievements': { target: 'http://localhost:8000', changeOrigin: true },
      '/auth': { target: 'http://localhost:8000', changeOrigin: true },
      '/captures': { target: 'http://localhost:8000', changeOrigin: true },
      '/notifications': { target: 'http://localhost:8000', changeOrigin: true },
      '/uploads': { target: 'http://localhost:8000', changeOrigin: true },
      '/files': { target: 'http://localhost:8000', changeOrigin: true },
      '/bug-report': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
}));
