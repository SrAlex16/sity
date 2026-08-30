import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import mkcert from 'vite-plugin-mkcert';

export default defineConfig({
  plugins: [react(), mkcert()],
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
    },
  },
});
