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
