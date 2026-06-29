# Sity Monitor Panel

Electron dashboard for monitoring the Raspberry Pi: CPU, RAM, network, disk, process list, and service status.

## Prerequisites

- Node.js 18+
- npm 9+

## Installation

```bash
cd panel/
npm install
npm run approve-scripts   # needed once to allow electron + esbuild postinstall scripts
npm install               # re-run after approving scripts
```

## Development

```bash
npm run dev
```

## Build

```bash
npm run build
```

The packaged app lands in `dist-electron/`.

## Production (packaged binary)

```bash
npm run package
```

Produces `release/` with the platform-specific binary. On Linux aarch64:
- Binary: `release/linux-arm64/sity-monitor`
- Or AppImage: `release/Sity Monitor-1.0.0-arm64.AppImage`

## Autostart on boot

Copy the desktop entry (adjust path if needed):

```bash
sudo cp /home/alex/projects/sity/panel/sity-monitor.desktop /etc/xdg/autostart/
cp /home/alex/projects/sity/panel/sity-monitor.desktop ~/Desktop/
```

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+W` / close button | Close window |
| Minimize button | Minimize to taskbar |
