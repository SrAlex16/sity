# Sity — Frontend

React + TypeScript + Vite. Tailwind CSS. Sin router: toda la navegación es un `useState<Tab>` en `App.tsx`.

---

## Estructura

```
frontend/src/
  App.tsx                     — shell/orquestador: estado, hooks, routing de tabs
  hooks/
    useChat.ts                — estado y ciclo de vida del chat
  components/
    ChatTab.tsx               — tab de conversación (presentacional)
    PersonalityTab.tsx        — tab de personalidad y sliders (presentacional)
    DebugTab.tsx              — tab de trazas y eventos (presentacional)
    DatasetTab.tsx            — tab de dataset: captura, stats, reset de personalidad (presentacional)
  api/
    chatApi.ts                — sendChatMessage, getCurrentChat, tipos de respuesta
    sityApi.ts                — getPersonality, adjustPersonality, resetPersonality
    debugApi.ts               — getRecentEvents, getLastTrace
  constants/
    personalityDefaults.ts    — CANONICAL_PERSONALITY: valores canónicos de personalidad compartidos con el backend
```

---

## Responsabilidades

### `App.tsx` — shell/orquestador

- Mantiene el estado de personalidad (`personality`, `loading`, `savingKey`, `error`, `message`).
- Mantiene el estado de debug (`recentEvents`, `lastTraceEvents`, `lastTraceId`, `debugError`).
- Llama a `useChat` y recibe el estado de chat ya gestionado.
- Calcula `averageEdge` (useMemo sobre la personalidad: `frialdad_afectiva_level`).
- Expone `refreshPersonality`, `refreshDebug`, `setAbsolute`, `restorePersonalityToDefaults`.
- Renderiza el header con los botones de tab y delega en `<ChatTab>`, `<PersonalityTab>`, `<DebugTab>`, `<DatasetTab>`.

### `hooks/useChat.ts`

- Estado: `chatInput`, `chatEntries`, `chatLoading`, `chatError`, `pendingStatus`, `activeClientTurnId`, `canCancel`.
- Refs: `chatBottomRef` (scroll), `eventSourceRef` (cleanup SSE en unmount), `abortControllerRef` (cancel fetch en unmount o por usuario).
- Abre un `EventSource` por turno para recibir actualizaciones de progreso (tool_started, tool_finished, cancelled, done/error).
- `submitChat`: crea un `AbortController`, llama a `sendChatMessage` con el signal, maneja `AbortError` en silencio.
- `cancelActiveOperation`: aborta el fetch activo y llama al endpoint `/events/chat/:id/cancel`.
- Acepta `onMessageSent?: () => void` para disparar refreshes de personalidad/debug tras respuesta exitosa.
- Exporta `ChatEntry` type.

### `components/ChatTab.tsx` — presentacional

Props recibidas de `useChat` + `averageEdge` de App. Sin estado ni efectos propios.
Importa `API_BASE` directamente (no lo recibe como prop).

### `components/PersonalityTab.tsx` — presentacional

Contiene `LABELS`, `ORDER` y `percent()` (solo los usa personalidad). Incluye botón "Restaurar valores por defecto".
Props: `personality`, `averageEdge`, `message`, `error`, `loading`, `savingKey`, `onReload`, `onRestoreDefaults`, `onSliderChange(key, value)` (update optimista), `onSliderCommit(key, value)` (llama a la API).

### `components/DebugTab.tsx` — presentacional

Contiene `EventCard` y `formatTime` (solo los usa debug).
Props: `lastTraceId`, `lastTraceEvents`, `recentEvents`, `debugError`, `onRefresh`.

### `components/DatasetTab.tsx` — presentacional

Gestiona la sección de dataset capture y estadísticas. Incluye botón "Restaurar valores de personalidad" que llama a `onRestorePersonality`.
Props: `onRestorePersonality: () => Promise<void>`, más props de estado de dataset capture.

---

## Patrones

- **Componentes presentacionales**: `ChatTab`, `PersonalityTab`, `DebugTab` son cero-`useState`, cero-`useEffect`. Reciben todo por props.
- **`debugLog`**: helper DEV-only en `useChat.ts` (`if (import.meta.env.DEV) console.log(...)`). Vite lo elimina en producción.
- **AbortController**: creado en `submitChat`, pasado como `signal` a `sendChatMessage`, nulado en `finally`. El `onerror` del SSE también está guardado con `import.meta.env.DEV`.

---

## Variables de entorno

| Variable | Descripción | Default |
|---|---|---|
| `VITE_SITY_API_BASE` | URL base del backend | `http://localhost:8000` |

Definir en `frontend/.env.local` para desarrollo local con URL diferente.
