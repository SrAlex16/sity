import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import mkcert from 'vite-plugin-mkcert';

export default defineConfig({
  plugins: [react(), mkcert()],
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
    },
  },
});
