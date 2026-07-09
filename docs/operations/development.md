# Flujo de desarrollo

Última actualización: 2026-07-08.

## Entornos

**PC / Windows (WSL):**
- Training LoRA con Unsloth + RTX 3060 Ti
- Hugging Face, scripts de training
- Edición desde IDE

**Raspberry Pi 4 (producción):**
- Backend/runtime real de Sity
- Panel de control (Electron, autoarranque)
- Home Assistant (Docker)
- Cámara, micrófono, pantalla RasPad 3
- No usar para entrenar modelos

## Flujo de trabajo habitual

1. Desarrollo con Claude Code directamente en la Pi (SSH)
2. Tests: python -m pytest --tb=short -q tests/
3. Commit + push desde la Pi
4. CI en GitHub Actions verifica automáticamente

```bash
cd ~/projects/sity
python -m pytest --tb=short -q tests/
git add -A
git commit -m "mensaje"
git push
```

## Servicios — comandos útiles

```bash
# Estado
sudo systemctl status sity-backend caddy cloudflared
docker inspect --format="{{.State.Running}}" homeassistant

# Reiniciar
sudo systemctl restart sity-backend
sudo systemctl reload caddy

# Logs
sudo journalctl -u sity-backend -n 50 --no-pager
cat ~/projects/sity/data/logs/app-$(date -u +%Y-%m-%d).jsonl | tail -20
```

## Panel de control

Tras cambios en panel/:

```bash
cd panel && npm run build && npm run package
```

El binario en release/linux-arm64-unpacked/ se actualiza.
El autoarranque (/etc/xdg/autostart/) apunta a ese binario.

## Frontend PWA (mobile/)

```bash
cd mobile && npm run build
sudo systemctl reload caddy
```

**⚠️ El build es obligatorio tras cualquier cambio en `mobile/src/` o
`mobile/public/`.** Caddy sirve directamente el contenido de
`mobile/dist/` — Vite genera nombres de archivo con hash de contenido,
así que sin rebuild el archivo en disco no cambia y ningún cambio de
código llega al navegador, Service Worker o no.

El servicio systemd `sity-frontend` es **solo el servidor de desarrollo
de Vite en el puerto 5173** — no tiene ninguna relación con lo que
Caddy sirve en producción. Reiniciarlo no reconstruye ni redespliega nada.

**Verificar que un build llegó al navegador:**
1. Comprobar que el hash de `dist/assets/index-*.js` cambió tras el build.
2. `Shift+F5` en el navegador.
3. DevTools → Sources → confirmar que el hash del bundle cargado coincide
   con el recién generado.
4. Si no coincide: DevTools → Application → Service Workers — puede haber
   una versión en "waiting to activate". Pulsar "skipWaiting" y recargar.
   (Ver docs/turn-cancellation.md §7a para el detalle completo.)

## Qué no subir a git

```
.env
data/
datasets/
work/
captures/
backend/.venv/
*/node_modules/
training/output/
reports/
```

## Regla de seguridad operativa

Si hay dos opciones y una toca runtime real, elegir primero
la opción local/mock/manual. No hacer cambios destructivos
sin confirmación clara.
