# RasPad 3 audio workaround

Este directorio documenta el workaround de audio usado en Sity para que el RasPad 3 saque sonido por HDMI.

## Problema raíz

El RasPad 3 no tiene señal HPD funcional para esta configuración. HPD significa `Hot Plug Detect`: es el pin físico que le dice a la Raspberry que hay una pantalla HDMI conectada.

Como HPD está siempre a `0`, el driver `vc4-hdmi` del kernel no activa el modo PCM normal. En su lugar, solo expone el formato:

```text
IEC958_SUBFRAME_LE
```

Ese formato es S/PDIF encapsulado, no PCM normal.

PipeWire no puede usarlo como mezclador de escritorio normal, así que el HDMI no aparece como salida de audio usable para aplicaciones normales.

## Problema adicional: Vivaldi

Vivaldi corre como proceso 32-bit en este sistema.

Eso significa que usa ALSA directo y no PipeWire/PulseAudio de forma normal.

Además, Vivaldi escribe en el dispositivo ALSA `default`, que por defecto acaba apuntando a la tarjeta de sonido con índice más bajo.

Por eso se usa `/etc/asound.conf` para redirigir `default` al Loopback.

## Arquitectura final

```text
Vivaldi / ALSA default
        |
        | /etc/asound.conf redirige default -> Loopback
        v
  hw:Loopback,0,0
        |
        | snd-aloop kernel loopback
        v
  hw:Loopback,1,0
        |
        v
  arecord -f S16_LE
        |
        v
  pcm2iec958.py
        |
        v
  aplay -D hw:vc4hdmi0,0 -f IEC958_SUBFRAME_LE
        |
        v
  HDMI audio
```

## Componentes

### snd-aloop

`snd-aloop` es un módulo del kernel que crea una tarjeta de sonido virtual con un loopback interno.

Lo que se escribe en el device 0 aparece en el device 1.

Se carga en cada arranque mediante:

```text
/etc/modules-load.d/snd-aloop.conf
```

Contenido esperado:

```text
snd-aloop
```

### /etc/asound.conf

Redirige el dispositivo ALSA `default` al Loopback por nombre, no por número de card.

Esto evita depender de que Loopback sea siempre `card 0`.

Ejemplo:

```text
pcm.!default {
    type hw
    card Loopback
    device 0
}

ctl.!default {
    type hw
    card Loopback
}
```

### pcm2iec958.py

Script Python ubicado normalmente en:

```text
/home/alex/.local/bin/pcm2iec958.py
```

Convierte PCM `S16_LE` a `IEC958_SUBFRAME_LE`.

Para el silencio envía ceros puros, no preambles IEC958, para evitar ruido en el receptor HDMI.

### hdmi-audio-forward.service

Servicio systemd de usuario ubicado normalmente en:

```text
~/.config/systemd/user/hdmi-audio-forward.service
```

Mantiene vivo el pipeline:

```text
arecord -D hw:Loopback,1,0 -f S16_LE -r 48000 -c 2
  | python3 pcm2iec958.py
  | aplay -D hw:vc4hdmi0,0 -f IEC958_SUBFRAME_LE -r 48000 -c 2 -t raw
```

Tiene un `ExecStartPre` que espera a que Loopback exista antes de arrancar:

```text
until aplay -l | grep -q Loopback; do sleep 1; done
```

### WirePlumber

WirePlumber debe ignorar Loopback para evitar que cree nodos que ruteen el micrófono en bucle.

Archivo:

```text
~/.config/wireplumber/main.lua.d/51-default-sink.lua
```

Objetivo:

- Evitar que Loopback se convierta en fuente default.
- Evitar feedback.
- Mantener el micrófono real de webcam separado del audio del sistema.

### cmdline.txt

En:

```text
/boot/firmware/cmdline.txt
```

Se usa:

```text
vc4.force_hotplug=1
```

Esto ayuda a la detección DRM, aunque no soluciona el audio HDMI por sí solo.

---

## VLC

### Problema

VLC es 64-bit y usa PipeWire/PulseAudio.

Configurar solo:

```text
aout=alsa
```

no fue suficiente.

El sistema tiene un hook en:

```text
/etc/alsa/conf.d/99-pulse.conf
```

Cuando detecta PipeWire-pulse activo, ese hook sobreescribe el dispositivo ALSA `default` para que apunte a PulseAudio.

Eso anula `/etc/asound.conf`.

Resultado:

```text
VLC -> ALSA default -> PulseAudio/PipeWire -> fuera del pipeline
```

### Solución

En:

```text
~/.config/vlc/vlcrc
```

Configurar explícitamente:

```text
aout=alsa
alsa-audio-device=hw:Loopback,0
```

Así VLC bypasea el hook de PulseAudio y escribe directamente al Loopback.

Después el pipeline normal lo captura:

```text
VLC
  -> hw:Loopback,0
  -> hw:Loopback,1
  -> pcm2iec958.py
  -> vc4hdmi0
  -> HDMI
```

---

## Lo que no funcionó

### hdmi_force_edid_audio=1

En `config.txt`, esta opción eliminó el perfil `output:hdmi-stereo` del driver.

No solucionó el problema.

### PipeWire con perfil pro-audio del Loopback

WirePlumber exponía la captura del Loopback como fuente default.

Resultado: el micrófono entraba en bucle de feedback.

### module-null-sink de PipeWire

El monitor del null sink capturaba ceros en PipeWire 1.2.7.

### ~/.asoundrc con pcm.default pulse

El plugin de PulseAudio es 64-bit y Vivaldi es 32-bit.

Incompatible.

### pw-record del monitor

El null sink en PipeWire-pulse no enrutaba el audio al monitor correctamente.

---

## Comandos útiles

Estado del pipeline:

```bash
systemctl --user status hdmi-audio-forward.service
```

Reiniciar pipeline:

```bash
systemctl --user restart hdmi-audio-forward.service
```

Ver tarjetas ALSA:

```bash
aplay -l
aplay -L
```

Ver PipeWire:

```bash
wpctl status
pactl list short sinks
pactl list short sources
```

Probar salida HDMI directa:

```bash
speaker-test -D hw:vc4hdmi0,0 -c 2 -r 48000 -F S32_LE -t sine
```

---

## Advertencias para Sity

Sity no debe tocar automáticamente estos archivos:

```text
/etc/asound.conf
/etc/modules-load.d/snd-aloop.conf
/home/alex/.local/bin/pcm2iec958.py
~/.config/systemd/user/hdmi-audio-forward.service
~/.config/wireplumber/main.lua.d/51-default-sink.lua
~/.config/vlc/vlcrc
```

Si alguna futura tool de Sity gestiona audio, debe:

- Detectar Loopback como dispositivo virtual.
- No usar Loopback como micrófono real.
- No cambiar el default sink/source sin confirmación.
- No modificar WirePlumber sin plan previo.
- No romper el pipeline HDMI.
- Registrar cambios en audit logs.

---

## Estado deseado

```text
Vivaldi funciona con audio HDMI.
VLC funciona con audio HDMI.
YouTube funciona en Vivaldi.
El micrófono real sigue siendo la Full HD webcam.
Loopback solo se usa como puente de audio del sistema.
```
