# Evolución del proyecto

Este documento narra cómo ha evolucionado Sity desde su concepción hasta el
estado actual. Es un documento vivo: se actualiza conforme el proyecto avanza.
Para el estado funcional detallado y vigente, ver `docs/operations/current-state.md`;
para lo que viene, ver el roadmap en el `README.md`.

## Origen y concepto

Sity nació de la idea de construir algo parecido a las IAs de ficción que tienen
presencia y memoria —una IA con la que se pueda hablar, que recuerde y que tenga
carácter propio— pero aterrizado en algo realmente útil y ejecutable en casa, no
un simple chatbot de rol. La intención desde el principio fue que no compitiera
con tener el móvil o el PC a mano, sino que aportara algo distinto: una presencia
local, persistente, ligada al entorno físico y con personalidad.

El nombre "Sity" viene de "sensity", por la idea original de dotarla de "sentidos"
(cámara, micrófono, percepción del entorno).

## Personalidad

El carácter de Sity se inspiró en personajes femeninos de anime de tipo tsundere
(ariscas o frías en la superficie, con un fondo más cálido) y en un punto mordaz
y sarcástico propio de ciertas IAs de videojuegos. La idea incluía simular una
especie de "libre albedrío": que pudiera negarse a hacer algo o responder con
desgana según su estado.

El sistema de ajustar la personalidad por porcentajes se inspiró en un robot de
ciencia ficción con parámetros configurables, y se materializó en los sliders
actuales. Sity puede ajustar sus propios parámetros por chat, además de poder
hacerlo manualmente desde la interfaz.

Los parámetros han evolucionado con el tiempo. Algunos que se plantearon al
principio se descartaron (un "modo" que imitaba a una IA concreta de videojuego,
que en realidad solo era inspiración; y un parámetro de "autonomía" que no
aportaba claridad). Otros se añadieron después: un parámetro de melancolía y, más
adelante, uno de escepticismo (facilidad para creerse algo o cuestionarlo).

Se definió también que Sity habla de sí misma en femenino y en castellano de
España, y que —asumiendo un usuario adulto— puede usar un humor más ácido,
palabrotas o expresiones subidas de tono, siempre modulado por los parámetros de
personalidad.

## Arquitectura y decisiones tempranas

Varias decisiones de arquitectura se tomaron pronto y se han mantenido:

- **Un solo proveedor de IA (Claude).** Al principio se barajó usar dos
  proveedores con uno como fallback, pero se simplificó a usar solo Claude,
  dejando el fallback a otros modelos para el futuro.
- **SQLite en lugar de una base de datos en la nube**, por privacidad y
  simplicidad, con exportación manual de datos al PC cuando haga falta.
- **Sin Docker** de momento, para reducir complejidad.
- **Flujo de desarrollo basado en Git**: desarrollo en local, push al repo,
  pull en la Pi, conexión por SSH, y acceso al frontend web desde el PC.
- **Logs y trazabilidad estructurada** en todos los módulos desde el inicio, y
  como objetivo transversal, **ahorrar tokens sin perder calidad**.

Un principio que ha guiado muchas decisiones: **evitar literales hardcodeados**
en el código que decidan el comportamiento (por ejemplo, listas de palabras
clave). En su lugar, dejar la interpretación al modelo. Esto surgió de varios
bugs en los que listas de términos fijas provocaban comportamientos incorrectos,
y se convirtió en una regla de diseño recurrente.

## Sentidos (cámara, micrófono, audio)

El diseño original de los "sentidos" contemplaba: ver la pantalla del PC (solo
cuando se le pidiera), cámara activable por voz con frecuencia de captura
variable, y micrófono. Las capturas no se guardan indefinidamente: se borran de
forma automática.

La integración de hardware dio bastante trabajo. El audio por HDMI de la pantalla
no funcionaba porque el panel no envía señal de detección de conexión, lo que
impedía que el sistema expusiera el dispositivo de audio de forma normal;
resolverlo requirió configuración a bajo nivel. También hubo que resolver
conflictos entre distintos subsistemas de audio del sistema operativo para que
ciertas aplicaciones sonaran por los altavoces.

Hoy la cámara y el micrófono USB se detectan y funcionan, con captura de imagen y
grabación corta de audio tanto desde el backend como desde el frontend, preview
en el chat, indicador de grabación y cancelación de la operación.

## Acceso al sistema y acciones

Se definió que Sity tuviera acceso amplio al sistema donde vive, pero que las
acciones críticas requirieran confirmación previa: primero propone un plan, el
usuario confirma, y solo entonces se ejecuta. Las acciones se dividen entre
seguras (lectura) y críticas (modificación).

Esto se aplicó a varias áreas: lectura del estado del sistema, integración con
Git (lectura de estado/historial como segura; cambios, ramas, pull y push como
críticos con confirmación), y gestión de servicios del sistema con una allowlist
configurable. Se creó un servicio de prueba ("sity-test") que simplemente
responde, para poder probar acciones de sistema sin tocar servicios pesados.

La confirmación se diseñó para ser flexible: si el usuario no sabe el nombre
exacto de una acción pendiente, una referencia razonable basta como confirmación.

## Memoria y autoconocimiento

Sity tiene historial de conversación persistente y búsqueda en él mediante FTS5,
expuesta como una herramienta de búsqueda. Desde el origen del proyecto se
planteó la idea de que, ante un bug, se le pudiera preguntar a Sity por qué había
ocurrido y que mostrara logs y trazas. Esa idea fue el precursor de la
herramienta actual que le permite leer su propia traza de ejecución del día
(tokens, herramientas usadas, modo de salida, búsquedas de memoria), disponible
solo en el preset de depuración.

También se añadió conciencia del tiempo entre mensajes: Sity sabe cuánto ha
pasado desde el último mensaje y puede reaccionar a ello según el contexto.

## Refactorización hacia una arquitectura modular

A medida que el proyecto creció, el archivo principal de rutas del chat se
convirtió en un monolito. Se hizo una refactorización progresiva y cuidadosa,
extrayendo responsabilidades a módulos separados (construcción de respuestas,
presupuesto, bucle de herramientas, construcción de peticiones, cierre de
respuesta, persistencia, etc.), siempre con tests antes de mover las piezas más
delicadas.

En paralelo, el despachador de herramientas pasó de un bloque monolítico de
condicionales a un registro de handlers por dominio. La interfaz de proveedores
de IA se abstrajo para permitir, en el futuro, intercambiar proveedores sin
reescribir el núcleo.

## Voz (STT y TTS)

Se incorporó entrada y salida por voz, priorizando que el procesamiento sea local:
transcripción de voz a texto en local y síntesis de texto a voz en local. El
audio se captura en el dispositivo del cliente y solo el texto resultante entra
al flujo de Sity, un patrón que encaja con el cambio de enfoque hacia separar el
servidor del dispositivo desde el que se habla.

## Mensajería y acceso remoto

Para poder hablar con Sity desde fuera de la interfaz web, se añadió un bot de
mensajería (texto y notas de voz) con allowlist y límite de uso. El núcleo recibe
los mensajes normalizados, sin necesidad de saber por qué canal llegan; para eso
se añadió metadata de canal de origen en cada mensaje.

## Camino hacia el LLM local

Una línea de trabajo importante ha sido reducir o eliminar la dependencia de la
nube ejecutando un modelo local, por privacidad y coste. La idea evolucionó: de
sustituir el proveedor en la nube, a mantenerlo como fallback, hasta una
realización clave —dado que el PC es mucho más potente que la Pi, montar la
inferencia en el PC y que la Pi le llame por la red local, reutilizando el cliente
que ya existe—.

Se construyó la infraestructura híbrida (separando lo que va a la nube de lo que
podría ir a local), se evaluaron numerosos modelos locales, y se concluyó que
ninguno sin ajuste fino tenía una voz compatible con Sity para uso diario. La vía
elegida fue el fine-tuning de estilo (LoRA) sobre un modelo base, para lo cual se
está capturando un dataset de conversaciones con la voz de Sity. Las herramientas
y acciones seguirían yendo por la nube, ya que los modelos locales no soportan
bien el uso de herramientas.

## Calidad: tests, CI y licencia

El proyecto tiene una arquitectura de testing amplia y un CI que corre en cada
cambio sin necesitar clave de API ni red (compilación, tests locales e
integración con un proveedor simulado). El repositorio se publicó bajo licencia
AGPL-3.0-or-later: código abierto para que la comunidad pueda usarlo y modificarlo,
con la condición de compartir el código fuente de versiones modificadas ofrecidas
como servicio, y reservando los usos comerciales cerrados a permiso explícito.

## Bugs históricos resueltos (lecciones aprendidas)

A lo largo del desarrollo han aparecido varios bugs recurrentes cuya resolución
dejó aprendizajes:

- Los sliders de personalidad no se actualizaban en tiempo real en el frontend, y
  la conversación se perdía al refrescar la página.
- Las respuestas se cortaban con verbosidad baja, lo que llevó a ajustar los
  límites de tokens por nivel de verbosidad.
- El protocolo de uso de herramientas del proveedor es de dos turnos y usa un
  esquema concreto; implementarlo mal hacía que las herramientas no se activaran.
- Listas de palabras clave fijas (singular/plural, dialecto) provocaban que el
  conjunto de herramientas correcto no se activara, lo que reforzó la regla de no
  hardcodear literales.
- El contador de uso diario de tokens comparaba fechas en zonas horarias distintas,
  lo que desactivaba el límite diario; se corrigió calculando la medianoche local
  convertida a UTC.
- La voz de Sity se contaminaba con un dialecto distinto al castellano de España
  cuando recuperaba mensajes antiguos de memoria; se resolvió con una regla de
  normalización del registro al citar contenido recuperado.
- El bot de mensajería no arrancaba tras un reinicio si la red aún no estaba lista;
  se resolvió añadiendo una dependencia de red al servicio.

## Mantenimiento de este documento

Este documento debe actualizarse cuando se cierren hitos relevantes o se tomen
decisiones de diseño importantes, de forma que sirva como memoria viva de la
evolución del proyecto.
