Auditoría del Proyecto: sity
Repositorio: https://github.com/SrAlex16/sity
Fecha de auditoría: 30 de julio de 2026
Versión analizada: Rama principal actual
Estado del proyecto: Fase temprana de desarrollo (Auth en construcción)

1. Entendimiento General del Proyecto
sity es una red social descentralizada y minimalista construida sobre AT Protocol (el protocolo de Bluesky). La interfaz de usuario está desarrollada con SvelteKit, estilizada con Tailwind CSS y utiliza DaisyUI como librería de componentes. Para la integración con AT Protocol se apoya en el SDK oficial @atproto/api.

La aplicación permite:

Autenticación mediante credenciales de Bluesky (identifier + app password)

Visualización de un timeline con filtros (seguidos, popular, etiquetas)

Gestión de perfiles

Un reproductor de música integrado (SoundCloud)

Una interfaz limpia y responsiva

El proyecto se encuentra en una fase temprana de desarrollo, con la autenticación aún en construcción y funcionalidades marcadas como pendientes.

2. Estructura del Proyecto
text
sity/
├── src/
│   ├── lib/
│   │   ├── api/          # Cliente AT Protocol y PDS
│   │   ├── components/   # Componentes UI reutilizables
│   │   ├── icons/        # Íconos SVG
│   │   ├── stores/       # Estados globales (Svelte stores)
│   │   ├── types/        # Tipos TypeScript
│   │   └── utils/        # Utilidades y constantes
│   ├── routes/           # Sistema de rutas SvelteKit
│   │   ├── (auth)/       # Layout para autenticación
│   │   ├── (dashboard)/  # Layout para el dashboard
│   │   ├── api/          # Endpoints de API internos
│   │   └── login/        # Página de inicio de sesión
│   ├── app.css           # Estilos globales y utilidades
│   └── app.html          # Template HTML principal
├── static/
├── docs/                 # Documentación
└── Archivos de configuración
3. Puntos Fuertes
3.1 Arquitectura y Código
Separación clara de responsabilidades: El patrón de diseño separa lógica de API, componentes reutilizables, stores globales y tipos, lo que facilita el mantenimiento

Uso correcto de SvelteKit: Aprovecha layouts anidados ((auth) y (dashboard)), páginas con carga de datos asíncrona y page.js para proteger rutas

Tipado TypeScript: Tipos definidos para posts, perfiles, respuestas de API, estados de carga, etc., lo que mejora la robustez del código

Manejo de estados de UI: Componentes como Skeleton, ErrorView y props de loading/error proporcionan buena experiencia de usuario durante cargas y fallos

Internacionalización: El sistema de i18n en $lib/i18n/ con soporte español e inglés permite añadir más idiomas fácilmente

Configuración de PDS personalizable: Soporte para conectarse a diferentes servidores AT Protocol mediante variables de entorno

3.2 Documentación
README bien estructurado: Explica el propósito, las tecnologías, cómo instalar, configuración, contribución y solución de problemas

Guías detalladas: Documentos en docs/ para configuración de PDS, testing OAuth, manejo de sesiones y solución de problemas de cursor/timeline

3.3 UI/UX
Diseño responsivo: Adaptado a móviles y escritorio con barra lateral, menú inferior y navegación superior

Temas personalizables: 31 temas disponibles con selector en la interfaz y persistencia en localStore

Modo sin conexión: Manejo de navigator.onLine con indicador de estado offline

4. Puntos Débiles y Riesgos Identificados
4.1 Riesgos de Seguridad
🔴 Almacenamiento inseguro de credenciales

En auth.ts se almacenan tokens en texto plano en el almacenamiento local:

typescript
localStorage.setItem('atproto_credentials', JSON.stringify({
  identifier: session.did,
  password: session.accessJwt,
}));
Esto expone el token de acceso (aunque no es la contraseña real, es sensible) a cualquier script que pueda acceder al localStorage mediante XSS.

Recomendación: Almacenar solo tokens de sesión con tiempo de expiración o usar cookies HttpOnly gestionadas por el servidor.

🟡 Validación de entradas

No se detectan mecanismos explícitos de sanitización de contenido de posts antes de renderizarlos, lo que podría exponer a riesgos XSS si el contenido incluye HTML o scripts.

🟡 Endpoint API /api/proxy

Expone un proxy que podría ser utilizado para realizar peticiones arbitrarias al PDS configurado. Sin una capa de rate limiting o autenticación adicional, podría ser susceptible a abuso.

4.2 Código y Arquitectura
🔴 Manejo inadecuado de errores en funciones críticas

En pds.ts, la función resolveHandle tiene un bloque try/catch con una aserción de tipo peligrosa:

typescript
const errorBody = await response.json() as { message?: string };
throw new Error(errorBody.message || 'Error desconocido al resolver el identificador');
Si la respuesta no es JSON válido (por ejemplo, error de red), response.json() lanzará otra excepción que no está siendo manejada.

🟡 Lógica de cliente duplicada

pds.ts reimplementa un cliente HTTP genérico en lugar de extender o reutilizar las capacidades del SDK @atproto/api. Esto puede llevar a:

Mantenimiento duplicado

Posible divergencia con actualizaciones del protocolo

Carencia de manejo automático de tokens de refresco

🟡 Gestión de sesiones frágil

La sesión se mantiene únicamente en localStore del lado del cliente y se pasa manualmente a cada petición. No hay un mecanismo centralizado de interceptor o middleware para adjuntar el token automáticamente a todas las peticiones del SDK.

El onMount en la ruta de login puede redirigir en bucle si hay sesión activa mal validada.

🟡 Estados de UI no completos

El estado Empty está definido en los tipos de timeline pero no se utiliza en la vista actual (+page.svelte). El timeline simplemente no muestra nada si está vacío.

4.3 Documentación
Faltan badges de estado del proyecto (build, cobertura, licencia)

La documentación menciona OAuth de Bluesky pero el código actual solo implementa autenticación por contraseña de aplicación

No hay guía de migración ni documentación de releases

4.4 Configuración y DevOps
No hay tests automatizados (unitarios, integración o e2e)

Las variables de entorno contienen valores por defecto (PUBLIC_PDS_URL apunta a https://bsky.social) que aunque es seguro, podría ser peligroso si se añaden variables con secretos en el futuro y se olvida limpiar el valor por defecto

No se define un Dockerfile ni configuración de contenedores

5. Mejoras Potenciales
5.1 Seguridad y Autenticación (prioridad alta)
Migrar a OAuth PKCE: Como la documentación sugiere, implementar OAuth 2.0 con PKCE para evitar que la aplicación maneje credenciales del usuario

Almacenar sesiones en cookies HttpOnly/Secure: En lugar de localStorage, usar cookies gestionadas por SvelteKit en el servidor o, si se mantiene en cliente, cifrar los tokens

Implementar CSP (Content Security Policy): Ya se menciona en la documentación, pero no hay evidencia de implementación

Sanitizar contenido de posts: Usar DOMPurify o similares si se renderiza HTML, o asegurar que todo el contenido se escape adecuadamente

5.2 Arquitectura de Cliente AT Protocol
Centralizar la lógica de autenticación: Crear un store o servicio que maneje la sesión, tokens y renovación automática, con interceptores para todas las peticiones

Evaluar si reemplazar el cliente HTTP personalizado por el SDK oficial: @atproto/api ya maneja la creación de sesiones, firmas de peticiones y renovación de tokens

Implementar patrón "Offline First" mejorado: Usar service workers para cachear el timeline y permitir navegación básica sin conexión

5.3 Testing y Calidad de Código
Añadir tests unitarios: Con Vitest, probar al menos stores, utilidades y transformaciones de datos

Tests e2e: Con Playwright para flujos críticos como login, carga de timeline y filtrado

Integrar ESLint y Prettier en CI: Aunque hay configuraciones presentes, no hay evidencia de que se ejecuten automáticamente

Añadir husky + lint-staged para pre-commit hooks

5.4 Experiencia de Usuario
Implementar paginación real con cursor: La UI actual tiene botones de "Anterior/Siguiente" pero el mecanismo de cursor infinito no está completo (se menciona en la documentación como mejora pendiente)

Añadir estado Empty al timeline: Mostrar un mensaje amigable cuando no hay posts, con acciones sugeridas (ej. "Sigue a más personas" o "Explora etiquetas populares")

Mejorar la accesibilidad: Añadir atributos ARIA, roles adecuados y navegación por teclado

Implementar búsqueda: No hay funcionalidad de búsqueda a pesar de que AT Protocol la soporta

5.5 Documentación
Añadir JSDoc a funciones principales: Especialmente en el cliente API y stores

Crear un changelog y versionado semántico

Documentar arquitectura de decisiones: Por qué se optó por un cliente personalizado, patrones de estado, etc.

6. Datos Críticos (TL;DR)
Aspecto	Estado	Prioridad
Almacenamiento de tokens en localStorage	⚠️ Riesgo de seguridad	Crítica
Validación de contenido de posts	⚠️ Posible XSS	Alta
Cliente HTTP sin interceptor de autenticación	⚠️ Mantenimiento y seguridad	Alta
Sistema de autenticación (en desarrollo)	ℹ️ Se indica que está incompleto	Observación
Tests automatizados	❌ No implementados	Media
Documentación	✅ Adecuada para fase temprana	Mantenimiento
Arquitectura general	✅ Bien estructurada	-
UI/UX y diseño	✅ Robusto y personalizable	-
Código duplicado (vs SDK)	⚠️ Potencial deuda técnica	Media
7. Conclusión
El proyecto sity muestra una base sólida con buenas prácticas de arquitectura y documentación, especialmente valioso para ser un proyecto en etapa inicial. La integración con AT Protocol es funcional para lectura de timelines.

Los riesgos principales están en la seguridad del manejo de sesiones (prioridad urgente) y la falta de tests. La decisión de implementar un cliente HTTP personalizado añade flexibilidad pero también deuda técnica que podría evitarse usando el SDK oficial de manera más extensiva.

El proyecto tiene potencial para convertirse en un cliente alternativo ligero y atractivo para Bluesky si se abordan estos puntos. La mención explícita en la documentación de que la autenticación está en desarrollo mitiga parcialmente la preocupación, pero no elimina los riesgos actuales si el código con almacenamiento inseguro llegara a producción.

8. Notas Adicionales
Auth en desarrollo: Se ha tenido en cuenta la indicación de que la parte de Auth sigue en desarrollo, por lo que las observaciones sobre autenticación se consideran en ese contexto

Sin invención de datos: Todas las observaciones se basan exclusivamente en el código y documentación disponibles en el repositorio

Consulta abierta: Si algún punto no queda claro o se necesita profundizar en algún aspecto, se puede consultar sin problema

Auditoría realizada sobre el código y documentación disponibles públicamente en el repositorio.

