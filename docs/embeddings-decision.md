# Decisión: embeddings locales descartados para Raspberry Pi 4B

**Fecha:** 2026-09-30  
**Contexto:** evaluación de embeddings locales para pre-filtrado semántico en
el sistema de deduplicación de SelfBelief y SemanticFact candidates (Mini-Remake v2.0, Punto 4).

## Benchmark realizado

Modelo probado: `sentence-transformers/all-MiniLM-L6-v2` (el más ligero disponible, ~90MB)  
Hardware: Raspberry Pi 4B, 4GB RAM, ARM64

| Métrica | Resultado |
|---------|-----------|
| Carga del modelo | **26.34s** |
| 1 proposición (media 10 runs) | **856.5ms** |
| 20 proposiciones (media 10 runs) | **2958.3ms** |
| RAM adicional | **880.5MB** |

## Conclusión

Embeddings locales son inviables en la Pi 4B para este caso de uso:

- **26 segundos de carga** en cada arranque del backend es inaceptable.
- **856ms por proposición** añadiría casi 1 segundo de latencia a cada turno
  que genere un candidate nuevo.
- **880MB de RAM** representa más de un tercio de la RAM total (4GB), compartida
  con el backend FastAPI, SQLite, Piper TTS y faster-whisper STT.

## Estrategia adoptada

### Pre-filtrado sin embeddings (fase beta)

Con volúmenes bajos de SelfBeliefs y SemanticFacts (esperables en la beta),
el semantic resolver pasa todos los candidates existentes directamente a Haiku
sin pre-filtrado previo. Con 20-50 beliefs, el prompt es manejable y la latencia
adicional es solo la de la llamada Haiku (~300-500ms), no la de los embeddings.

### Embeddings via API (cuando el volumen lo justifique)

Cuando el volumen de beliefs/facts supere ~100 entries por usuario, se evaluará
usar la API de embeddings de Anthropic para pre-filtrar los K más similares antes
de la llamada al semantic resolver. Sin coste de RAM en la Pi, pago por uso.

### Trigger de revisión

Revisar esta decisión cuando:
- Cualquier usuario supere 100 SelfBeliefs activas, o
- La latencia del semantic resolver supere 1 segundo por candidate nuevo, o
- Haya un modelo de embeddings ARM64 con carga < 2s y RAM < 200MB disponible.

## Dependencias instaladas y eliminadas

Durante el benchmark se instalaron temporalmente:
- `sentence-transformers`, `transformers`, `tokenizers`, `huggingface-hub`, `torch`
- Caché de HuggingFace (~90MB en `~/.cache/huggingface/`)

Todas eliminadas tras el benchmark. El entorno de producción de la Pi queda
sin dependencias adicionales.
