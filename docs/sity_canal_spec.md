# Sity · Especificación: Canal de divulgación Tech & IA

> **Documento de referencia para cualquier dev, IA o colaborador que quiera entender esta feature sin haber estado en la conversación original.**
>
> Última actualización: junio 2026  
> Autor original: Alex (SrAlex16)  
> Contexto base: proyecto [Sity](https://github.com/SrAlex16/sity)

---

## 1. Qué es esto

Este documento especifica la integración del canal de YouTube de Sity dentro del propio proyecto Sity. No es un proyecto paralelo: es una extensión de Sity que añade nuevas **capabilities** siguiendo exactamente la misma filosofía y arquitectura que ya tiene el proyecto.

**Resumen en una frase:** Sity actúa como orquestadora de un canal de divulgación de tecnología e IA en YouTube, ayudando a generar contenido (noticias, guiones, audio, métricas) con revisión humana obligatoria en cada paso crítico.

---

## 2. Concepto del canal

### 2.1 Idea central

Canal de divulgación de **tecnología e IA para personas sin conocimientos técnicos**, presentado por Sity como personaje/identidad del canal. No tutoriales (no "cómo crear una clase en Java"), sino contexto, noticias e innovaciones explicadas de forma accesible.

**Gancho principal:** una IA hablando de IA como si fuera una persona, siendo completamente transparente sobre lo que es. Parte del contenido del canal es el propio desarrollo de Sity: decisiones de diseño, seguridad, arquitectura, etc., explicadas para no-devs.

### 2.2 Línea editorial

- Noticias e innovaciones de la semana en tech/IA.
- Contexto: "qué significa esto realmente" desde la perspectiva de un desarrollador.
- Serie paralela: "construyendo a Sity" (el desarrollo del propio proyecto como contenido).
- Tono: llano, con analogías, sin jerga, con opinión real.

### 2.3 Formato

- **Largo semanal:** 6-10 minutos, resumen de la semana.
- **Shorts derivados:** 3-4 por semana, extraídos del largo (cada noticia jugosa = un short).
- **Faceless:** voz IA (ElevenLabs) + visuales/b-roll. Sin cara en cámara.
- **Idioma:** español (España + Latam). No inglés ni otros idiomas en fase inicial.

### 2.4 Identidad de Sity en el canal

- Avatar/foto de perfil: imagen de personaje de IA, claramente no humana.
- Nunca fingir que Sity es autónoma o que publica sola. La transparencia es parte del gancho.
- Fórmula: *"Soy Sity, una IA que vive en una Raspberry Pi. Preparo estos vídeos; mi creador los revisa para que no diga tonterías."*

---

## 3. Arquitectura general del pipeline

El pipeline completo, de principio a fin, con quién hace qué:

```
[Sity]  fetch_rss_news      → recopila noticias de la semana en SQLite
[Alex]  selección editorial → marca 4-6 noticias (en chat con Sity)
[Sity]  generate_script     → genera guion en DOCX con estructura rica
[Alex]  revisión del guion  → edita el DOCX, verifica datos, añade criterio
[Sity]  generate_tts        → llama a ElevenLabs API (con confirmación de Alex)
[Alex]  revisión del audio  → escucha, aprueba o pide regenerar
[Alex/Sity] generación de imágenes → Higgsfield, Gemini u otros (a definir)
[Alex]  búsqueda de música  → sin copyright, manual o semi-auto
[Alex]  montaje de vídeo    → en el PC (Remotion/ffmpeg), o API de editor online
[Sity]  upload a YouTube    → YouTube Data API, con confirmación
[Sity]  responder comentarios → YouTube, TikTok, Twitter/X (con reglas estrictas)
[Sity]  recopilar métricas  → todas las plataformas → SQLite local
```

**Principio heredado de Sity:** en cada paso que modifica o publica algo, hay una pending action con confirmación explícita de Alex antes de ejecutar. Nada se publica solo.

---

## 4. Phases detalladas

### Fase A — Ingesta de noticias y generación de guion (PRIORIDAD 1)

Es el núcleo. Todo lo demás depende de tener un buen guion.

#### 4.1 Tool: `fetch_rss_news`

**Activación:** bajo petición explícita de Alex en el chat de Sity. No hay cron job automático (decisión tomada: Alex decide cuándo buscar).

**Lo que hace:**
1. Lee los feeds configurados en `config/content_sources.yaml`.
2. Filtra ítems de los últimos 7 días (configurable).
3. Deduplica por URL.
4. Guarda en nueva tabla `news_items` de SQLite con campos: `id`, `title`, `source`, `url`, `published_at`, `summary`, `category`, `status` (`pending` / `selected` / `discarded`), `created_at`.
5. Responde con resumen: cuántas noticias por fuente, titulares principales.

**Configuración de fuentes** (`config/content_sources.yaml`, mismo patrón que `system_access.yaml`):

```yaml
rss_feeds:
  - name: "The Verge"
    url: "https://www.theverge.com/rss/index.xml"
    category: "tech"
  - name: "Ars Technica"
    url: "https://feeds.arstechnica.com/arstechnica/index"
    category: "tech"
  - name: "VentureBeat AI"
    url: "https://venturebeat.com/category/ai/feed/"
    category: "ai"
  - name: "Anthropic Blog"
    url: "https://www.anthropic.com/rss.xml"
    category: "ai"
  - name: "OpenAI Blog"
    url: "https://openai.com/blog/rss"
    category: "ai"
  - name: "Google DeepMind"
    url: "https://deepmind.google/blog/rss.xml"
    category: "ai"
  - name: "Meta AI"
    url: "https://ai.meta.com/blog/rss/"
    category: "ai"
  - name: "Hacker News (top)"
    url: "https://hnrss.org/frontpage"
    category: "tech"

content_output:
  script_output_path: "/home/alex/canal/guiones"
  assets_path: "/home/alex/canal/assets"
  audio_output_path: "/home/alex/canal/audio"
```

**Nota de seguridad:** `script_output_path` y derivados deben añadirse a la `writable_paths` de `system_access.yaml`. Esta carpeta vive fuera del repo de Sity, así que hay que actualizar el perfil de acceso.

#### 4.2 Selección editorial (Alex)

Tras la ingesta, Alex revisa en el chat y dice algo como:
> "Sity, marca como seleccionadas las noticias 1, 3 y 5 para el guion de esta semana."

Sity actualiza el campo `status` en SQLite. Pending action con confirmación, como siempre.

#### 4.3 Tool: `generate_script`

**Activación:** bajo petición de Alex, después de haber seleccionado noticias.

**Lo que hace:**
1. Recupera noticias con `status = 'selected'` de SQLite.
2. Llama a Claude (Sonnet, siguiendo el Model Router del roadmap de Sity) con el prompt de guion (ver sección 4.4).
3. Exporta el resultado como DOCX estructurado a `script_output_path`.
4. Pending action con confirmación antes de guardar.
5. Tras confirmar, marca las noticias usadas como `status = 'used'`.

**Estructura del DOCX generado:**
- Portada: título del episodio, fecha, número de episodio.
- Tabla resumen inicial: noticia / fuente / por qué importa para un no-dev.
- Sección por noticia (H1 con nombre de la noticia):
  - Contexto (qué era antes de esto).
  - La noticia en sí (qué ha pasado).
  - Qué significa para alguien normal (la clave).
  - Notas de producción en cursiva: sugerencias de b-roll, momentos de pausa, énfasis.
- Bloque final: 3-4 shorts derivados con gancho propio cada uno.
- Metadatos sugeridos: título del vídeo, descripción para YouTube, tags.

No texto plano: H1/H2, negritas en conceptos clave, tablas, cursivas para notas de producción.

#### 4.4 Prompt de guion

El prompt que `generate_script` envía a Claude. Parametrizado, no hardcodeado.

```
Eres el guionista de un canal de divulgación tech/IA llamado Sity.
El canal está presentado por una IA (Sity) y dirigido a personas sin
conocimientos técnicos: no saben programar, pero les interesa entender
qué está pasando en el mundo de la tecnología y la IA.

Tono: cercano, directo, con analogías del mundo cotidiano. Sin jerga.
Con opinión real: "esto es humo / esto cambia las cosas".
En español de España.

Recibes una lista de noticias con título, fuente y resumen.
Genera un guion para un vídeo largo de 6-10 minutos que:
1. Empiece con un gancho fuerte (los primeros 15 segundos son críticos).
2. Dedique una sección a cada noticia.
3. Conecte las noticias si hay hilo común.
4. Cierre con una reflexión breve de Sity como personaje.

Marca en cursiva [NOTA PRODUCCIÓN: ...] cualquier sugerencia de b-roll,
pausa, énfasis o recurso visual que ayude al montaje.

Al final, genera 3-4 shorts derivados, cada uno con su propio gancho
en los primeros 3 segundos, autónomo (no necesita haber visto el largo).

IMPORTANTE: no inventes datos, fechas ni cifras. Si algo no está en
las noticias que te paso, no lo incluyas. Alex lo verificará todo
antes de publicar.
```

**Nota para el dev:** el prompt completo debe vivir en un archivo de configuración (`config/prompts/script_prompt.txt` o similar), no en el código. Así Alex puede ajustarlo sin tocar Python.

---

### Fase B — Audio / TTS (PRIORIDAD 2, después de Fase A)

**Decisión tomada:** este paso NO es automático. Siempre requiere confirmación de Alex, porque el guion ya ha sido editado por él y el audio es el primer output "final" del pipeline.

#### 5.1 ElevenLabs API

**Coste:** ElevenLabs tiene tier gratuito con límite mensual de caracteres (~10.000 caracteres/mes en el plan free a fecha de esta spec). Un guion de 6-10 minutos tiene aproximadamente 4.000-8.000 caracteres de texto narrado, así que es posible generar al menos un guion completo al mes sin coste. **Verificar siempre los límites actuales en elevenlabs.io antes de implementar**, ya que cambian.

**Tool: `generate_tts`**

- Input: ruta al DOCX revisado por Alex, o el texto directamente.
- Extrae solo el texto narrable (excluye notas de producción, tablas de metadatos).
- Llama a la API de ElevenLabs con la voz configurada.
- Guarda el audio en `audio_output_path`.
- Pending action con confirmación siempre, sin excepción.
- La clave de API de ElevenLabs va en `.env`, nunca en el código ni en el repo.

**Voz:** elegir UNA voz en español y no cambiarla nunca. Es la identidad sonora de Sity en el canal. Configurada en `content_sources.yaml` o en `.env`.

---

### Fase C — Imágenes y assets visuales (A DEFINIR)

**Estado:** pendiente de decisión y pruebas.

**Opciones barajadas:**
- **Higgsfield:** generación de vídeo/imagen con IA. Pendiente de revisar API y costes.
- **Gemini (Google):** generación de imágenes. Pendiente de revisar términos de uso para contenido publicado.
- **B-roll de stock:** Pexels, Storyblocks (gratuito o de pago). Más fiable en términos de licencias.
- **Capturas reales:** de apps, demos, interfaces. Sube mucho la calidad frente a stock genérico. Recomendado siempre que sea posible.

**Decisión pendiente:** qué herramienta usar y si Sity puede orquestar la generación (llamada a API) o si Alex lo hace manualmente.

**Música:** búsqueda manual de música sin copyright (YouTube Audio Library, Free Music Archive, etc.). No automatizado por ahora.

---

### Fase D — Montaje de vídeo (A DEFINIR)

**Estado:** pendiente. La Raspberry Pi no tiene capacidad para renderizar vídeo en condiciones.

**Opción A (futuro):** editores online con API REST.
- **Shotstack:** API de montaje de vídeo en la nube. Sity envía un JSON con assets, timing y estructura; Shotstack devuelve el vídeo renderizado. Pendiente de revisar precios y calidad de salida.
- **Creatomate:** similar a Shotstack. Pendiente de evaluar.
- Si se implementa, Sity actuaría como orquestadora: prepara el "paquete de montaje" (guion + audio + lista de assets + timing) y llama a la API con confirmación.

**Opción B (inmediato):** Alex monta el vídeo en su PC con Remotion, ffmpeg, CapCut o similar. Sity entrega todos los assets organizados en `assets_path`; Alex hace el montaje manual.

**Decisión tomada para arrancar:** empezar con Opción B. Migrar a Opción A cuando el pipeline esté estable y se haya validado el formato.

---

### Fase E — Publicación en YouTube

**Tool: `upload_youtube`**

- Sube el vídeo final a YouTube vía YouTube Data API v3.
- Aplica título, descripción, tags, categoría y miniatura generados en el guion.
- Programa la publicación (no publica inmediatamente).
- **Pending action con confirmación siempre.** Nada se publica sin el OK de Alex.
- Las credenciales OAuth de YouTube van en `.env` / gestión segura de secretos, nunca en el repo.

**Publicación escalonada:**
- Largo: viernes (u otro día fijo que Analytics confirme como óptimo).
- Shorts: repartidos de lunes a jueves de la semana siguiente.

**Declaración de contenido sintético:** YouTube obliga a marcar vídeos con voz/visuales generados por IA. Activarlo siempre en la subida. Incluirlo en los parámetros de `upload_youtube`.

---

### Fase F — Respuesta a comentarios en redes

**Estado:** diseño pendiente. Marcado como "idea con riesgo" que requiere estudio antes de implementar.

**Plataformas objetivo:** YouTube, TikTok, Twitter/X. Instagram, Facebook y Bluesky descartados por ahora.

**Riesgo principal:** una IA respondiendo comentarios en público sin supervisión puede generar controversia, respuestas inapropiadas o malentendidos que dañen la reputación del canal. Es el paso más delicado de todo el pipeline.

**Propuesta de implementación segura (a validar):**

```
1. Sity monitoriza comentarios nuevos periódicamente.
2. Clasifica cada comentario: pregunta / feedback positivo / crítica / spam / tóxico.
3. Para preguntas y feedback positivo: genera respuesta propuesta.
4. Alex revisa las respuestas propuestas (modo de revisión en batch).
5. Alex aprueba, edita o descarta cada una.
6. Sity publica solo las aprobadas.
7. Comentarios tóxicos o spam: propone ocultarlos/reportarlos, con confirmación.
```

**No implementar modo "auto-respuesta total"** sin haber validado primero el sistema de revisión en batch durante al menos 4-6 semanas. La credibilidad del canal depende de no meter la pata en público.

**APIs necesarias:**
- YouTube Data API v3 (comentarios: ya está en la misma API que la subida).
- TikTok Research API / Display API (revisar disponibilidad y restricciones).
- Twitter/X API v2 (tiene costes en el tier básico a fecha de esta spec; verificar).

---

### Fase G — Métricas y datos

**Objetivo:** guardar absolutamente todo en SQLite local. No depender solo del dashboard de YouTube. Los datos son activos del proyecto y potencial material de entrenamiento futuro.

#### Qué guardar

**Métricas de vídeo (YouTube):**
- Vistas, vistas únicas, tiempo de visualización, retención por segundo.
- CTR (impresiones → clics en miniatura).
- Fuentes de tráfico (Browse, Sugeridos, Búsqueda, Externo).
- Suscriptores ganados/perdidos por vídeo.
- Likes, dislikes estimados, comentarios, compartidos.

**Métricas de audiencia:**
- Demografía: edad, sexo, geografía, idioma.
- Dispositivos y plataformas.
- Horarios de visualización.
- Contenido relacionado que ve la audiencia ("Other Videos Your Audience Watched").

**Métricas de monetización** (cuando aplique):
- RPM (revenue per mille), CPM.
- Ingresos estimados por vídeo y canal.
- Fuentes de ingresos (anuncios, membresías, Super Thanks).

**Métricas de redes sociales:**
- Interacciones (likes, comentarios, compartidos, guardados) por post.
- Alcance e impresiones.
- Seguidores ganados por post.
- Relación entre post en red social y vistas en YouTube (atribución).

**Datos de comentarios:**
- Texto del comentario, autor, fecha, plataforma.
- Clasificación (pregunta, feedback, crítica, spam, tóxico).
- Si Sity respondió, qué respondió y cuándo.
- Reacciones a la respuesta de Sity.

**Correlaciones a guardar:**
- Qué día/hora se publicó cada vídeo y qué rendimiento tuvo en las primeras 24/48 h.
- Qué noticias se usaron en cada guion (referencia a `news_items`).
- Qué voz/prompt se usó para generar el audio.
- Versión del guion (número de ediciones que hizo Alex antes de aprobar).

#### Esquema de tablas SQLite (borrador)

```sql
-- Noticias recopiladas por RSS
news_items (id, title, source, url, published_at, summary, category, status, created_at)

-- Episodios / vídeos
episodes (id, title, published_at, youtube_id, tiktok_id, duration_seconds,
          script_path, audio_path, video_path, status, created_at)

-- Relación episodio ↔ noticias usadas
episode_news (episode_id, news_item_id)

-- Métricas de vídeo (snapshots periódicos)
video_metrics (id, episode_id, snapshot_at, platform, views, watch_time_minutes,
               ctr, avg_retention_pct, likes, comments, shares, subscribers_gained)

-- Métricas de audiencia (snapshots periódicos)
audience_metrics (id, episode_id, snapshot_at, age_group, gender, country,
                  percentage)

-- Métricas de monetización
monetization_metrics (id, episode_id, snapshot_at, rpm, cpm, estimated_revenue,
                      source)

-- Posts en redes sociales
social_posts (id, episode_id, platform, post_id, post_url, posted_at, content_preview)

-- Métricas de posts en redes
social_metrics (id, social_post_id, snapshot_at, likes, comments, shares,
                saves, reach, impressions)

-- Comentarios
comments (id, episode_id, platform, comment_id, author, text, posted_at,
          classification, sity_replied, sity_reply_text, sity_replied_at)
```

#### Tool: `fetch_metrics`

- Llama a las APIs de cada plataforma.
- Guarda snapshots en SQLite.
- Se puede ejecutar manualmente o con cron job (aquí sí tiene sentido el cron porque no modifica nada, solo lee).
- Sin pending action (es solo lectura), pero con log de cada ejecución.

---

## 5. Integración con la arquitectura de Sity

### 5.1 Nuevo specialist agent: `content_agent`

Siguiendo el roadmap de Sity de "Lightweight Specialist Agents", todas las tools de este documento pertenecen a un nuevo agente:

```
backend/app/tools/handlers/content_tools.py
```

Tools que incluye:
- `fetch_rss_news`
- `generate_script`
- `generate_tts`
- `upload_youtube`
- `fetch_metrics`
- `fetch_comments`
- `generate_comment_reply`
- `post_comment_reply`

### 5.2 Nuevas entradas en `system_access.yaml`

```yaml
writable_paths:
  - /home/alex/canal/guiones
  - /home/alex/canal/assets
  - /home/alex/canal/audio

readable_paths:
  - /home/alex/canal
```

### 5.3 Nuevas variables en `.env`

```
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...
YOUTUBE_CLIENT_ID=...
YOUTUBE_CLIENT_SECRET=...
YOUTUBE_REFRESH_TOKEN=...
TIKTOK_API_KEY=...
TWITTER_API_KEY=...
TWITTER_API_SECRET=...
TWITTER_ACCESS_TOKEN=...
TWITTER_ACCESS_SECRET=...
SHOTSTACK_API_KEY=...   # Solo si se implementa Opción A de montaje
```

### 5.4 Nuevas dependencias Python (tentativas)

```
feedparser          # Lectura de RSS
python-docx         # Generación de DOCX
elevenlabs          # SDK oficial de ElevenLabs
google-api-python-client  # YouTube Data API
tweepy              # Twitter/X API
```

### 5.5 Model Router para este agente

Siguiendo el roadmap del Model Router de Sity:

| Tarea | Modelo |
|---|---|
| `fetch_rss_news` (solo lectura/parse) | Sin Claude (lógica local) |
| Clasificar comentarios (rápido) | Haiku |
| Generar respuesta a comentario | Haiku / Sonnet según complejidad |
| `generate_script` (guion largo) | Sonnet |
| Cualquier revisión o análisis de guion | Sonnet |

---

## 6. Workflow semanal con Sity integrada

```
LUNES
  Alex: "Sity, busca las noticias de esta semana"
  Sity: fetch_rss_news → presenta titulares
  Alex: "Selecciona las noticias 1, 3 y 5"
  Sity: pending action → confirmación → marca en SQLite

MARTES
  Alex: "Sity, genera el guion con las noticias seleccionadas"
  Sity: generate_script → pending action → confirmación → DOCX en /canal/guiones
  Alex: abre el DOCX, revisa, verifica datos, edita, aprueba

MIÉRCOLES
  Alex: "Sity, genera el audio del guion revisado"
  Sity: generate_tts → pending action → confirmación → audio en /canal/audio
  Alex: escucha el audio, aprueba o pide regenerar con ajustes

  Alex: genera imágenes (manual o semi-auto, TBD)
  Alex: busca música sin copyright (manual)

JUEVES
  Alex: monta el vídeo en su PC
  Alex: genera miniatura (plantilla Canva)
  Alex: "Sity, sube el vídeo programado para el viernes a las 16:00"
  Sity: upload_youtube → pending action → confirmación → programado

VIERNES
  YouTube publica el vídeo (automático, ya programado)
  Sity: fetch_metrics → primer snapshot de métricas

CONTINUO
  Sity: fetch_comments periódicamente
  Sity: genera respuestas propuestas
  Alex: revisa y aprueba en batch
  Sity: publica respuestas aprobadas
  Sity: fetch_metrics periódicamente (snapshots a 24h, 48h, 7d, 30d)
```

---

## 7. Decisiones tomadas

| Decisión | Elección | Razón |
|---|---|---|
| Idioma del canal | Español | Ventaja competitiva real, mercado menos saturado, Alex puede verificar matices |
| Activación de RSS | Manual (bajo petición) | Alex decide cuándo buscar; más control editorial |
| Guardado del DOCX | Carpeta específica fuera del repo | `/home/alex/canal/guiones` |
| TTS | Con confirmación obligatoria | Paso crítico; el guion ya ha sido editado |
| Montaje inicial | Manual en PC de Alex | La Pi no renderiza vídeo; empezar simple |
| Redes sociales objetivo | YouTube + TikTok + Twitter/X | Instagram/Facebook/Bluesky descartados por ahora |
| Respuesta a comentarios | Con revisión humana en batch | Riesgo reputacional alto; no auto-respuesta total |
| Identidad de Sity en canal | Transparente (es una IA, parte del gancho) | Honestidad + diferenciación |
| Modelo para guiones | Claude Sonnet | Tarea larga y de calidad; Haiku no es suficiente |

---

## 8. Decisiones pendientes

| Decisión | Opciones | Notas |
|---|---|---|
| Herramienta de imágenes | Higgsfield / Gemini / stock / capturas reales | Revisar API, costes y licencias de cada una |
| Montaje futuro (Opción A) | Shotstack / Creatomate | Evaluar cuando el pipeline esté estable |
| Voz de ElevenLabs | Por elegir | UNA voz, consistente siempre. Revisar tier gratuito actual |
| Frecuencia de `fetch_metrics` | Manual / cron job | Cron tiene sentido aquí (solo lectura); definir intervalos |
| TikTok API | Research API / Display API | Revisar disponibilidad y restricciones actuales |
| Twitter/X API | v2 básico / elevado | Verificar costes actuales; han cambiado varias veces |
| Shorts y TikTok | ¿Los sube Sity o Alex manualmente? | TBD |

---

## 9. Avisos importantes para quien implemente esto

1. **Verificación de datos en el guion es innegociable.** El prompt le dice a Claude que no invente datos. Aun así, Alex revisa cada cifra y fecha contra la fuente original antes de aprobar. La credibilidad del canal depende de esto.

2. **Nunca auto-publicar.** Toda acción que publique algo (vídeo, comentario, post) debe tener una pending action con confirmación explícita de Alex. Sin excepción. Es el mismo principio de "puede proponer, puede actuar según política" que ya tiene Sity.

3. **Credenciales sensibles.** Las APIs de YouTube, ElevenLabs, TikTok y Twitter/X van en `.env`. Nunca en el código, nunca en el repo. Añadir todas las claves nuevas a `.gitignore` y documentarlas en `.env.example` sin valores reales.

4. **Declaración de contenido sintético en YouTube.** Obligatorio por política de YouTube (2025+). Incluirlo siempre en los parámetros de `upload_youtube`. No es opcional.

5. **Costes de APIs.** ElevenLabs, Twitter/X, Shotstack y otros tienen costes que cambian. Antes de implementar cada fase, verificar precios actuales. No asumir que algo es gratis porque lo era cuando se diseñó esto.

6. **Sity habla de sí misma en femenino y en castellano de España.** Las respuestas generadas para comentarios deben respetar esto. Incluirlo en el prompt de `generate_comment_reply`.

7. **El canal es de Sity como personaje, no como IA autónoma.** Nunca comunicar que Sity publica sola o decide sola. La transparencia es el diferenciador, no un problema.

8. **Respetar la arquitectura de Sity.** Todas las tools nuevas siguen el mismo patrón: handler en `content_tools.py`, registro en el registry (cuando esté refactorizado), sin lógica de negocio en `routes_chat.py`. El core no ejecuta comandos directamente; las capabilities los implementan.

---

## 10. Orden de implementación recomendado

```
1. Tabla news_items en SQLite
2. config/content_sources.yaml con las fuentes RSS
3. Añadir /home/alex/canal/* a system_access.yaml
4. Tool fetch_rss_news (sin Claude, lógica local con feedparser)
5. Tool generate_script (con Claude Sonnet + exportación DOCX)
6. Probar el ciclo completo: pedir → noticias → seleccionar → guion → DOCX
7. Validar calidad del DOCX y del guion antes de seguir
8. Tool generate_tts (ElevenLabs API, con confirmación)
9. Tool upload_youtube (YouTube Data API, con confirmación)
10. Tool fetch_metrics (todas las plataformas)
11. Sistema de comentarios (fetch + clasificar + proponer respuesta + confirmar + publicar)
12. Evaluar montaje online (Shotstack/Creatomate) si tiene sentido en ese momento
```

---

*Documento generado a partir de la conversación de diseño de junio 2026. Para contexto completo sobre Sity, ver [README del repositorio](https://github.com/SrAlex16/sity).*
