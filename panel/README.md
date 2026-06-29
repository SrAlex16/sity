# Sity Monitor — Panel de Control

Dashboard de monitorización en tiempo real para la Raspberry Pi 4.
Estética cyberpunk, datos del sistema reales, integrado en el repo de Sity.

## Stack

- Electron (frameless window, fullscreen al arrancar)
- TypeScript + CSS puro (sin frameworks)
- systeminformation — métricas de CPU, RAM, red, disco y procesos
- IPC seguro: contextIsolation activado, nodeIntegration desactivado

## Funcionalidades

- CPU: uso en %, temperatura, gráfico de línea en tiempo real
- RAM: usado/total en GB, %, gráfico de barras
- Red: DL/UL en Mbps, gráfico de línea doble (eth0)
- Disco: R/W en IO/s, gráfico de línea doble
- Procesos: lista de los 60 más activos, ordenados por CPU,
  coloreados por nivel de uso (azul → verde → amarillo → rojo)
- Servicios: barra de estado de sity-backend, caddy, cloudflared
- Alerta: pop-up automático cuando sity-backend cae, con log de
  journalctl y botón de restart (sin contraseña via sudoers)
- Autoarranque: fullscreen al encender la Pi via /etc/xdg/autostart/

## Arranque en desarrollo

```bash
cd panel
npm install
npm run build
DISPLAY=:0 npx electron . --no-sandbox
```

## Requisitos del sistema

- Node.js 18+
- Regla sudoers para restart sin contraseña:

```bash
sudo visudo -f /etc/sudoers.d/sity-panel
```

```
alex ALL=(ALL) NOPASSWD: /bin/systemctl restart sity-backend
alex ALL=(ALL) NOPASSWD: /bin/systemctl restart caddy
alex ALL=(ALL) NOPASSWD: /bin/systemctl restart cloudflared
```

- Archivo de autoarranque en `/etc/xdg/autostart/sity-monitor.desktop`

## Estructura

```text
panel/
├── index.html          # estructura HTML + modal de error
├── styles.css          # estilos cyberpunk completos
├── package.json
├── tsconfig.json
└── src/
    ├── main.ts         # proceso principal: IPC, métricas, servicios
    ├── preload.ts      # API segura expuesta al renderer
    └── renderer.ts     # lógica de UI, gráficos canvas, polling
```
