import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      '/chat': { target: 'http://localhost:8000', changeOrigin: true },
      '/audio': { target: 'http://localhost:8000', changeOrigin: true },
      '/settings': { target: 'http://localhost:8000', changeOrigin: true },
      '/debug': { target: 'http://localhost:8000', changeOrigin: true },
      '/health': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
});
