import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import electron from 'vite-plugin-electron'
import renderer from 'vite-plugin-electron-renderer'

export default defineConfig(({ command }) => ({
  plugins: [
    react(),
    electron([
      {
        entry: 'electron/main.ts',
        vite: {
          build: {
            sourcemap: command === 'serve',
            minify: command !== 'serve',
            outDir: 'dist-electron',
            rollupOptions: {
              external: ['systeminformation'],
            },
          },
        },
      },
      {
        entry: 'electron/preload.ts',
        onstart({ reload }) {
          reload()
        },
        vite: {
          build: {
            sourcemap: command === 'serve' ? 'inline' : undefined,
            minify: command !== 'serve',
            outDir: 'dist-electron',
          },
        },
      },
    ]),
    renderer(),
  ],
}))
