export type UiLang = 'es' | 'en' | 'ja';

export interface T {
  nav: {
    chat: string;
    personality: string;
    achievements: string;
    settings: string;
    dataset: string;
  };
  app: {
    initializing: string;
    accessDenied: string;
    accessDeniedDesc: string;
    maintenance: string;
    maintenanceDesc: string;
    maintenanceSub: string;
    adminLogin: string;
  };
  settings: {
    title: string;
    reload: string;
    saved: string;
    loading: string;
    // Voice section
    voice: string;
    responseMode: string;
    modeAlways: string;
    modeNever: string;
    modeSymmetric: string;
    includeTranscript: string;
    longResponses: string;
    longSplit: string;
    longTextOnly: string;
    restoreVoice: string;
    // TTS engine selector (User/Admin only)
    ttsEngineSection: string;
    ttsEngineHint: string;
    ttsEnginePiper: string;
    ttsEngineElevenLabs: string;
    ttsElevenLabsUnavailable: string;
    ttsUsage: (used: number, limit: number) => string;
    // Admin cleanup
    cleanupSection: string;
    cleanupHint: string;
    cleanupUnit: string;
    cleanupNever: string;
    // Model upgrade memory TTL
    upgradeMemorySection: string;
    upgradeMemoryHint: string;
    upgradeMemoryUnit: string;
    // UI language — Sistema 1
    uiLanguageSection: string;
    uiLanguageHint: string;
    uiLanguageNote: string;
    // Sity conversation language — Sistema 2
    sityLanguageSection: string;
    sityLanguageHint: string;
    sityLanguageNote: string;
    // Integrations
    integrationsSection: string;
    connected: string;
    notConnected: string;
    connect: string;
    disconnect: string;
    confirmDisconnect: string;
    cancel: string;
    // Export
    exportSection: string;
    exportHint: string;
    download: string;
    // Delete account
    deleteSection: string;
    deleteHint: string;
    deleteAccount: string;
    deleteConfirmWarning: string;
    confirmDeleteAll: string;
    // Files
    filesSection: string;
    filesHint: string;
    // Status
    justConnected: (name: string) => string;
    // Initiative — proactive messaging
    initiativeSection: string;
    initiativeMasterLabel: string;
    initiativeMasterHint: string;
    initiativeAbandoned: string;
    initiativeAbandonedHint: string;
    initiativeInactivity: string;
    initiativeInactivityHint: string;
    initiativeOpenLoop: string;
    initiativeOpenLoopHint: string;
    // Location
    locationSection: string;
    locationHint: string;
    locationPlaceholder: string;
    locationSave: string;
    locationDetect: string;
    locationDetecting: string;
    locationDenied: string;
    locationClear: string;
    locationSourceLabel: (source: string) => string;
  };
  chat: {
    guest: string;
    share: string;
    clearChat: string;
    changeBg: string;
    changeFont: string;
    notifProcessing: string;
    notifBlocked: string;
    notifDisable: string;
    notifEnable: string;
    logout: string;
    generatingLink: string;
    retry: string;
    copied: string;
    copyLink: string;
    close: string;
    expiresLabel: string;
    // StatusBadge
    statusOnline: string;
    statusProcessing: string;
    statusDisconnected: string;
    // AudioMessageBubble
    showTranscript: string;
    hideTranscript: string;
    yesterday: string;
    // FontPicker
    fontFuturistic: string;
    fontTerminal: string;
    fontElegant: string;
    fontCancel: string;
    // Shared links manager
    mySharedLinks: string;
    noSharedLinks: string;
    linkActive: string;
    linkRevoked: string;
    linkExpired: string;
    revokeLink: string;
    revoking: string;
    viewsLabel: string;
  };
  personality: {
    moodTranquil: string;
    moodNeutral: string;
    moodIrritable: string;
    moodHostile: string;
    moodNuclear: string;
    tabTraits: string;
    tabAlters: string;
    restore: string;
    reload: string;
    loading: string;
    noData: string;
  };
  alters: {
    empty: string;
    saveHere: string;
    load: string;
    rename: string;
    copy: string;
    clear: string;
    namePlaceholder: string;
    save: string;
    confirmLoad: string;
    confirm: string;
    cancel: string;
    confirmClear: string;
    copyTarget: string;
    slotLabel: string;
    slotEmpty: string;
  };
  dataset: {
    activePrefix: string;
    inactive: string;
    loading: string;
    captureActive: string;
    captureHint: string;
    preset: string;
    noneOption: string;
    save: string;
    disable: string;
    reload: string;
    restorePersonality: string;
  };
  achievements: {
    title: string;
    loading: string;
    unlocked: string;
    guestBanner: string;
    catPersonalidad: string;
    catTools: string;
    catMemoria: string;
    catDomotica: string;
    catBackground: string;
    catSecrets: string;
  };
  auth: {
    signInTitle: string;
    signIn: string;
    email: string;
    password: string;
    forgotPassword: string;
    connecting: string;
    continueGuest: string;
    orDivider: string;
    googleSignIn: string;
    noAccount: string;
    createAccountLink: string;
    createAccount: string;
    confirmPassword: string;
    registering: string;
    googleRegister: string;
    haveAccount: string;
    privacyAccept: string;
    privacyLink: string;
    recoverTitle: string;
    recoverSent: string;
    recoverIntro: string;
    sendLink: string;
    sendError: string;
    newPasswordTitle: string;
    newPasswordLabel: string;
    newPasswordPlaceholder: string;
    confirmPasswordLabel: string;
    confirmPasswordPlaceholder: string;
    changePassword: string;
    changingPassword: string;
    resetSuccess: string;
    resetIntro: string;
    resetInvalid: string;
    pwMinChars: string;
    pwUppercase: string;
    pwLowercase: string;
    pwNumber: string;
    emailRequired: string;
    emailInvalid: string;
    pwMismatch: string;
    privacyRequired: string;
    emailPasswordRequired: string;
    loginError: string;
    registerError: string;
    privacyTitle: string;
  };
}

const es: T = {
  nav: {
    chat: 'Chat',
    personality: 'Rasgos',
    achievements: 'Logros',
    settings: 'Ajustes',
    dataset: 'Datos',
  },
  app: {
    initializing: 'Inicializando…',
    accessDenied: '[ acceso denegado ]',
    accessDeniedDesc: 'Esta sección requiere permisos de administrador.',
    maintenance: '[ mantenimiento ]',
    maintenanceDesc: 'Sity está en mantenimiento.',
    maintenanceSub: 'Vuelve más tarde.',
    adminLogin: 'acceder como administrador',
  },
  settings: {
    title: 'Ajustes',
    reload: 'Recargar',
    saved: 'Guardado',
    loading: 'Cargando…',
    voice: 'Voz',
    responseMode: 'Modo de respuesta',
    modeAlways: 'Siempre',
    modeNever: 'Nunca',
    modeSymmetric: 'Simétrico (solo si el mensaje fue de voz)',
    includeTranscript: 'Incluir transcripción de texto junto al audio',
    longResponses: 'Respuestas largas',
    longSplit: 'Dividir en notas de voz',
    longTextOnly: 'Solo texto (sin audio)',
    restoreVoice: 'Restaurar valores de voz',
    ttsEngineSection: 'Motor de síntesis de voz',
    ttsEngineHint: 'Piper es local y gratuito. ElevenLabs usa la nube con límite diario de caracteres.',
    ttsEnginePiper: 'Piper (local)',
    ttsEngineElevenLabs: 'ElevenLabs (nube)',
    ttsElevenLabsUnavailable: 'No disponible para el idioma seleccionado',
    ttsUsage: (used: number, limit: number) => limit > 0 ? `Uso hoy: ${used} / ${limit} caracteres` : `Uso hoy: ${used} caracteres`,
    cleanupSection: 'Periodicidad de borrado',
    cleanupHint: 'Los mensajes de audio se sustituyen por su transcripción transcurrido este tiempo.',
    cleanupUnit: 'días',
    cleanupNever: '(0 = nunca borrar)',
    upgradeMemorySection: 'Memoria de propuesta de modelo',
    upgradeMemoryHint: 'Tiempo que Sity recuerda que ya aceptaste un upgrade del modelo para la misma tarea. Tras este tiempo, vuelve a preguntar.',
    upgradeMemoryUnit: 'horas',
    uiLanguageSection: 'Idioma de la app',
    uiLanguageHint: 'Idioma de los menús y botones. Se guarda en este navegador.',
    uiLanguageNote: 'Controla la interfaz, no las respuestas de Sity.',
    sityLanguageSection: 'Idioma de conversación de Sity',
    sityLanguageHint: 'En qué idioma responde Sity. «Auto» detecta el idioma de cada mensaje.',
    sityLanguageNote: 'Controla las respuestas de Sity, no los menús de la app.',
    integrationsSection: 'Integraciones',
    connected: 'Conectado',
    notConnected: 'No conectado',
    connect: 'Conectar',
    disconnect: 'Desconectar',
    confirmDisconnect: 'Sí, desconectar',
    cancel: 'Cancelar',
    exportSection: 'Exportar conversación',
    exportHint: 'Descarga todos los mensajes de tu conversación como archivo JSON.',
    download: 'Descargar',
    deleteSection: 'Borrar todos mis datos',
    deleteHint: 'Elimina tu cuenta y todos los datos asociados. Esta acción es irreversible.',
    deleteAccount: 'Borrar cuenta',
    deleteConfirmWarning: '¿Estás seguro? Esta acción no puede deshacerse.',
    confirmDeleteAll: 'Sí, borrar todo',
    filesSection: 'Gestión de archivos',
    filesHint: 'Próximamente. Aquí podrás ver y eliminar los archivos que hayas compartido con Sity.',
    justConnected: (name) => `${name} conectado correctamente.`,
    initiativeSection: 'Mensajes proactivos',
    initiativeMasterLabel: 'Permitir que Sity te escriba primero',
    initiativeMasterHint: 'Sity puede escribirte cuando detecte que hay algo pendiente o que merece la pena retomar.',
    initiativeAbandoned: 'Conversaciones abandonadas',
    initiativeAbandonedHint: 'Si dejas una conversación a medias, Sity puede retomarla más tarde.',
    initiativeInactivity: 'Reconexión tras inactividad',
    initiativeInactivityHint: 'Si llevas tiempo sin hablar con Sity, puede escribirte para saber cómo estás.',
    initiativeOpenLoop: 'Seguimiento de temas pendientes',
    initiativeOpenLoopHint: 'Si mencionas algo que querías resolver, Sity puede preguntarte más tarde qué tal fue.',
    locationSection: 'Ubicación',
    locationHint: 'Sity usa tu ubicación cuando preguntas por cosas locales (tiempo, restaurantes, horarios). Se guarda en el servidor, no en el navegador.',
    locationPlaceholder: 'Ciudad o región (ej: Madrid)',
    locationSave: 'Guardar',
    locationDetect: 'Detectar con el navegador',
    locationDetecting: 'Detectando…',
    locationDenied: 'Acceso denegado por el navegador',
    locationClear: 'Borrar ubicación',
    locationSourceLabel: (source: string) =>
      source === 'browser' ? 'Detectada con el navegador' :
      source === 'manual'  ? 'Introducida manualmente' :
      source === 'auto'    ? 'Detectada por Sity' :
      source === 'denied'  ? 'Acceso denegado' : '',
  },
  chat: {
    guest: 'Invitado',
    share: 'Compartir conversación',
    clearChat: 'Borrar chat',
    changeBg: 'Cambiar fondo',
    changeFont: 'Cambiar fuente',
    notifProcessing: 'Procesando…',
    notifBlocked: 'Notificaciones bloqueadas',
    notifDisable: 'Desactivar notificaciones push',
    notifEnable: 'Activar notificaciones push',
    logout: 'Cerrar sesión',
    generatingLink: 'Generando enlace…',
    retry: 'Reintentar',
    copied: '¡Copiado!',
    copyLink: 'Copiar enlace',
    close: 'Cerrar',
    expiresLabel: 'Caduca',
    statusOnline: 'EN LÍNEA',
    statusProcessing: 'PROCESANDO...',
    statusDisconnected: 'DESCONECTADO',
    showTranscript: 'Ver transcripción',
    hideTranscript: 'Ocultar transcripción',
    yesterday: 'Ayer',
    fontFuturistic: 'Futurista',
    fontTerminal: 'Terminal',
    fontElegant: 'Elegante',
    fontCancel: 'Cancelar',
    mySharedLinks: 'Mis enlaces compartidos',
    noSharedLinks: 'No has creado ningún enlace todavía.',
    linkActive: 'Activo',
    linkRevoked: 'Revocado',
    linkExpired: 'Caducado',
    revokeLink: 'Revocar',
    revoking: 'Revocando…',
    viewsLabel: 'vistas',
  },
  personality: {
    moodTranquil: 'Tranquila',
    moodNeutral: 'Neutral',
    moodIrritable: 'Irritable',
    moodHostile: 'Hostil',
    moodNuclear: 'Nuclear',
    tabTraits: 'Rasgos',
    tabAlters: 'Alters',
    restore: 'Restaurar',
    reload: 'Recargar',
    loading: 'Cargando…',
    noData: 'Sin datos',
  },
  alters: {
    empty: 'Vacío',
    saveHere: 'Guardar aquí',
    load: 'Cargar',
    rename: 'Renombrar',
    copy: 'Copiar',
    clear: 'Vaciar',
    namePlaceholder: 'Nombre del Alter',
    save: 'Guardar',
    confirmLoad: 'Sobrescribirá la personalidad activa',
    confirm: 'Confirmar',
    cancel: 'Cancelar',
    confirmClear: 'Se eliminará este preset',
    copyTarget: '— Destino —',
    slotLabel: 'Slot',
    slotEmpty: '(Vacío)',
  },
  dataset: {
    activePrefix: 'Activo',
    inactive: 'Desactivado',
    loading: 'Cargando…',
    captureActive: 'Capture activo',
    captureHint: 'Registra las conversaciones para el dataset LoRA',
    preset: 'Preset',
    noneOption: '— ninguno —',
    save: 'Guardar',
    disable: 'Desactivar',
    reload: 'Recargar',
    restorePersonality: 'Restaurar valores de personalidad',
  },
  achievements: {
    title: 'Logros',
    loading: 'Cargando…',
    unlocked: 'LOGRO DESBLOQUEADO',
    guestBanner: 'Regístrate para desbloquear logros y guardar tu progreso.',
    catPersonalidad: 'Personalidad',
    catTools: 'Herramientas',
    catMemoria: 'Memoria',
    catDomotica: 'Domótica',
    catBackground: 'Background',
    catSecrets: 'Secretos',
  },
  auth: {
    signInTitle: 'Iniciar sesión',
    signIn: 'Iniciar sesión',
    email: 'Email',
    password: 'Contraseña',
    forgotPassword: 'He olvidado la contraseña',
    connecting: 'Conectando…',
    continueGuest: 'Continuar como invitado',
    orDivider: 'o',
    googleSignIn: 'G  Iniciar sesión con Google (próximamente)',
    noAccount: '¿No tienes cuenta?',
    createAccountLink: 'Crear cuenta',
    createAccount: 'Crear cuenta',
    confirmPassword: 'Confirmar contraseña',
    registering: 'Registrando…',
    googleRegister: 'G  Registrarse con Google (próximamente)',
    haveAccount: '¿Ya tienes cuenta?',
    privacyAccept: 'He leído y acepto la',
    privacyLink: 'política de privacidad',
    recoverTitle: 'Recuperar contraseña',
    recoverSent: 'Si el email está registrado, recibirás un enlace de recuperación.',
    recoverIntro: 'Introduce tu email y te enviaremos un enlace para restablecer la contraseña.',
    sendLink: 'Enviar enlace',
    sendError: 'Error al enviar. Inténtalo de nuevo.',
    newPasswordTitle: 'Nueva contraseña',
    newPasswordLabel: 'Nueva contraseña',
    newPasswordPlaceholder: 'Mín. 8 car., mayús., minús. y número',
    confirmPasswordLabel: 'Confirmar contraseña',
    confirmPasswordPlaceholder: 'Repite la contraseña',
    changePassword: 'Cambiar contraseña',
    changingPassword: 'Actualizando…',
    resetSuccess: '¡Contraseña actualizada correctamente! Ya puedes iniciar sesión con tu nueva contraseña.',
    resetIntro: 'Introduce tu nueva contraseña.',
    resetInvalid: 'Este enlace ya no es válido. Pide uno nuevo desde "He olvidado mi contraseña".',
    pwMinChars: 'Mínimo 8 caracteres.',
    pwUppercase: 'Debe incluir al menos una mayúscula.',
    pwLowercase: 'Debe incluir al menos una minúscula.',
    pwNumber: 'Debe incluir al menos un número.',
    emailRequired: 'Email y contraseña son obligatorios.',
    emailInvalid: 'Introduce un email válido.',
    pwMismatch: 'Las contraseñas no coinciden.',
    privacyRequired: 'Debes aceptar la política de privacidad.',
    emailPasswordRequired: 'Email y contraseña son obligatorios.',
    loginError: 'Error al iniciar sesión.',
    registerError: 'Error al registrarse.',
    privacyTitle: 'Política de privacidad',
  },
};

const en: T = {
  nav: {
    chat: 'Chat',
    personality: 'Traits',
    achievements: 'Awards',
    settings: 'Settings',
    dataset: 'Data',
  },
  app: {
    initializing: 'Initializing…',
    accessDenied: '[ access denied ]',
    accessDeniedDesc: 'This section requires administrator permissions.',
    maintenance: '[ maintenance ]',
    maintenanceDesc: 'Sity is under maintenance.',
    maintenanceSub: 'Come back later.',
    adminLogin: 'sign in as administrator',
  },
  settings: {
    title: 'Settings',
    reload: 'Reload',
    saved: 'Saved',
    loading: 'Loading…',
    voice: 'Voice',
    responseMode: 'Response mode',
    modeAlways: 'Always',
    modeNever: 'Never',
    modeSymmetric: 'Symmetric (only if message was voice)',
    includeTranscript: 'Include text transcript with audio',
    longResponses: 'Long responses',
    longSplit: 'Split into voice notes',
    longTextOnly: 'Text only (no audio)',
    restoreVoice: 'Restore voice defaults',
    ttsEngineSection: 'Voice synthesis engine',
    ttsEngineHint: 'Piper is local and free. ElevenLabs uses the cloud with a daily character limit.',
    ttsEnginePiper: 'Piper (local)',
    ttsEngineElevenLabs: 'ElevenLabs (cloud)',
    ttsElevenLabsUnavailable: 'Not available for the selected language',
    ttsUsage: (used: number, limit: number) => limit > 0 ? `Today's usage: ${used} / ${limit} characters` : `Today's usage: ${used} characters`,
    cleanupSection: 'Cleanup period',
    cleanupHint: 'Audio messages are replaced by their transcript after this time.',
    cleanupUnit: 'days',
    cleanupNever: '(0 = never delete)',
    upgradeMemorySection: 'Model upgrade memory',
    upgradeMemoryHint: 'How long Sity remembers that you accepted a model upgrade for the same task. After this time, it will ask again.',
    upgradeMemoryUnit: 'hours',
    uiLanguageSection: 'App language',
    uiLanguageHint: 'Language for menus and buttons. Saved in this browser.',
    uiLanguageNote: "Controls the interface, not Sity's responses.",
    sityLanguageSection: "Sity's conversation language",
    sityLanguageHint: "The language Sity responds in. «Auto» detects the language of each message.",
    sityLanguageNote: "Controls Sity's responses, not the app menus.",
    integrationsSection: 'Integrations',
    connected: 'Connected',
    notConnected: 'Not connected',
    connect: 'Connect',
    disconnect: 'Disconnect',
    confirmDisconnect: 'Yes, disconnect',
    cancel: 'Cancel',
    exportSection: 'Export conversation',
    exportHint: 'Download all your conversation messages as a JSON file.',
    download: 'Download',
    deleteSection: 'Delete all my data',
    deleteHint: 'Deletes your account and all associated data. This action is irreversible.',
    deleteAccount: 'Delete account',
    deleteConfirmWarning: 'Are you sure? This action cannot be undone.',
    confirmDeleteAll: 'Yes, delete everything',
    filesSection: 'File management',
    filesHint: 'Coming soon. Here you will be able to view and delete files shared with Sity.',
    justConnected: (name) => `${name} connected successfully.`,
    initiativeSection: 'Proactive messages',
    initiativeMasterLabel: 'Allow Sity to message you first',
    initiativeMasterHint: 'Sity may reach out when it detects something worth following up on.',
    initiativeAbandoned: 'Abandoned conversations',
    initiativeAbandonedHint: 'If you leave a conversation unfinished, Sity may pick it up later.',
    initiativeInactivity: 'Reconnect after inactivity',
    initiativeInactivityHint: "If you haven't talked to Sity in a while, it may check in on you.",
    initiativeOpenLoop: 'Pending topic follow-up',
    initiativeOpenLoopHint: 'If you mention something you wanted to resolve, Sity may ask about it later.',
    locationSection: 'Location',
    locationHint: 'Sity uses your location when you ask about local things (weather, restaurants, hours). Saved on the server, not in the browser.',
    locationPlaceholder: 'City or region (e.g. Madrid)',
    locationSave: 'Save',
    locationDetect: 'Detect with browser',
    locationDetecting: 'Detecting…',
    locationDenied: 'Access denied by browser',
    locationClear: 'Clear location',
    locationSourceLabel: (source: string) =>
      source === 'browser' ? 'Detected via browser' :
      source === 'manual'  ? 'Set manually' :
      source === 'auto'    ? 'Detected by Sity' :
      source === 'denied'  ? 'Access denied' : '',
  },
  chat: {
    guest: 'Guest',
    share: 'Share conversation',
    clearChat: 'Clear chat',
    changeBg: 'Change background',
    changeFont: 'Change font',
    notifProcessing: 'Processing…',
    notifBlocked: 'Notifications blocked',
    notifDisable: 'Disable push notifications',
    notifEnable: 'Enable push notifications',
    logout: 'Sign out',
    generatingLink: 'Generating link…',
    retry: 'Retry',
    copied: 'Copied!',
    copyLink: 'Copy link',
    close: 'Close',
    expiresLabel: 'Expires',
    statusOnline: 'ONLINE',
    statusProcessing: 'PROCESSING...',
    statusDisconnected: 'DISCONNECTED',
    showTranscript: 'Show transcript',
    hideTranscript: 'Hide transcript',
    yesterday: 'Yesterday',
    fontFuturistic: 'Futuristic',
    fontTerminal: 'Terminal',
    fontElegant: 'Elegant',
    fontCancel: 'Cancel',
    mySharedLinks: 'My shared links',
    noSharedLinks: 'You have not created any links yet.',
    linkActive: 'Active',
    linkRevoked: 'Revoked',
    linkExpired: 'Expired',
    revokeLink: 'Revoke',
    revoking: 'Revoking…',
    viewsLabel: 'views',
  },
  personality: {
    moodTranquil: 'Calm',
    moodNeutral: 'Neutral',
    moodIrritable: 'Irritable',
    moodHostile: 'Hostile',
    moodNuclear: 'Nuclear',
    tabTraits: 'Traits',
    tabAlters: 'Alters',
    restore: 'Restore',
    reload: 'Reload',
    loading: 'Loading…',
    noData: 'No data',
  },
  alters: {
    empty: 'Empty',
    saveHere: 'Save here',
    load: 'Load',
    rename: 'Rename',
    copy: 'Copy',
    clear: 'Clear',
    namePlaceholder: 'Alter name',
    save: 'Save',
    confirmLoad: 'This will overwrite the active personality',
    confirm: 'Confirm',
    cancel: 'Cancel',
    confirmClear: 'This preset will be deleted',
    copyTarget: '— Target —',
    slotLabel: 'Slot',
    slotEmpty: '(Empty)',
  },
  dataset: {
    activePrefix: 'Active',
    inactive: 'Disabled',
    loading: 'Loading…',
    captureActive: 'Capture active',
    captureHint: 'Records conversations for the LoRA dataset',
    preset: 'Preset',
    noneOption: '— none —',
    save: 'Save',
    disable: 'Disable',
    reload: 'Reload',
    restorePersonality: 'Restore personality defaults',
  },
  achievements: {
    title: 'Achievements',
    loading: 'Loading…',
    unlocked: 'ACHIEVEMENT UNLOCKED',
    guestBanner: 'Sign up to unlock achievements and save your progress.',
    catPersonalidad: 'Personality',
    catTools: 'Tools',
    catMemoria: 'Memory',
    catDomotica: 'Smart home',
    catBackground: 'Background',
    catSecrets: 'Secrets',
  },
  auth: {
    signInTitle: 'Sign in',
    signIn: 'Sign in',
    email: 'Email',
    password: 'Password',
    forgotPassword: 'Forgot password',
    connecting: 'Connecting…',
    continueGuest: 'Continue as guest',
    orDivider: 'or',
    googleSignIn: 'G  Sign in with Google (coming soon)',
    noAccount: "Don't have an account?",
    createAccountLink: 'Create account',
    createAccount: 'Create account',
    confirmPassword: 'Confirm password',
    registering: 'Registering…',
    googleRegister: 'G  Register with Google (coming soon)',
    haveAccount: 'Already have an account?',
    privacyAccept: 'I have read and accept the',
    privacyLink: 'privacy policy',
    recoverTitle: 'Recover password',
    recoverSent: 'If the email is registered, you will receive a recovery link.',
    recoverIntro: 'Enter your email and we will send you a link to reset your password.',
    sendLink: 'Send link',
    sendError: 'Error sending. Please try again.',
    newPasswordTitle: 'New password',
    newPasswordLabel: 'New password',
    newPasswordPlaceholder: 'Min. 8 chars, upper, lower, number',
    confirmPasswordLabel: 'Confirm password',
    confirmPasswordPlaceholder: 'Repeat the password',
    changePassword: 'Change password',
    changingPassword: 'Updating…',
    resetSuccess: 'Password updated successfully! You can now sign in with your new password.',
    resetIntro: 'Enter your new password.',
    resetInvalid: 'This link is no longer valid. Request a new one from "Forgot password".',
    pwMinChars: 'At least 8 characters.',
    pwUppercase: 'Must include at least one uppercase letter.',
    pwLowercase: 'Must include at least one lowercase letter.',
    pwNumber: 'Must include at least one number.',
    emailRequired: 'Email is required.',
    emailInvalid: 'Please enter a valid email.',
    pwMismatch: "Passwords don't match.",
    privacyRequired: 'You must accept the privacy policy.',
    emailPasswordRequired: 'Email and password are required.',
    loginError: 'Error signing in.',
    registerError: 'Error registering.',
    privacyTitle: 'Privacy policy',
  },
};

const ja: T = {
  nav: {
    chat: 'チャット',
    personality: '性格',
    achievements: '実績',
    settings: '設定',
    dataset: 'データ',
  },
  app: {
    initializing: '読込中…',
    accessDenied: '[ アクセス拒否 ]',
    accessDeniedDesc: 'このセクションは管理者権限が必要です。',
    maintenance: '[ メンテナンス中 ]',
    maintenanceDesc: 'Sityはメンテナンス中です。',
    maintenanceSub: '後でまたお試しください。',
    adminLogin: '管理者としてログイン',
  },
  settings: {
    title: '設定',
    reload: '再読込',
    saved: '保存済み',
    loading: '読込中…',
    voice: 'ボイス',
    responseMode: '応答モード',
    modeAlways: '常に',
    modeNever: 'なし',
    modeSymmetric: '対称（音声メッセージの場合のみ）',
    includeTranscript: '音声とともにテキスト起こしを含める',
    longResponses: '長い応答',
    longSplit: '音声ノートに分割',
    longTextOnly: 'テキストのみ（音声なし）',
    restoreVoice: '音声デフォルトに戻す',
    ttsEngineSection: '音声合成エンジン',
    ttsEngineHint: 'Piperはローカルで無料。ElevenLabsはクラウドを使用し、1日あたりの文字数制限があります。',
    ttsEnginePiper: 'Piper（ローカル）',
    ttsEngineElevenLabs: 'ElevenLabs（クラウド）',
    ttsElevenLabsUnavailable: '選択した言語では利用できません',
    ttsUsage: (used: number, limit: number) => limit > 0 ? `本日の使用量: ${used} / ${limit} 文字` : `本日の使用量: ${used} 文字`,
    cleanupSection: '削除周期',
    cleanupHint: 'この時間が経過すると音声メッセージは文字起こしに置き換えられます。',
    cleanupUnit: '日',
    cleanupNever: '（0 = 削除しない）',
    upgradeMemorySection: 'モデルアップグレード記憶',
    upgradeMemoryHint: '同じタスクのモデルアップグレードを承認したことをSityが記憶する時間。この時間が過ぎると再度確認します。',
    upgradeMemoryUnit: '時間',
    uiLanguageSection: 'アプリ言語',
    uiLanguageHint: 'メニューとボタンの言語。このブラウザに保存されます。',
    uiLanguageNote: 'インターフェースの言語を制御します（Sityの返答言語ではありません）。',
    sityLanguageSection: 'Sityの会話言語',
    sityLanguageHint: 'Sityが返答する言語。「Auto」は各メッセージの言語を自動検出します。',
    sityLanguageNote: 'Sityの返答言語を制御します（アプリメニューの言語ではありません）。',
    integrationsSection: '連携設定',
    connected: '接続済み',
    notConnected: '未接続',
    connect: '接続',
    disconnect: '切断',
    confirmDisconnect: '切断する',
    cancel: 'キャンセル',
    exportSection: '会話のエクスポート',
    exportHint: '会話のすべてのメッセージをJSONファイルとしてダウンロードします。',
    download: 'ダウンロード',
    deleteSection: 'データをすべて削除',
    deleteHint: 'アカウントとすべての関連データを削除します。この操作は元に戻せません。',
    deleteAccount: 'アカウント削除',
    deleteConfirmWarning: '本当に削除しますか？この操作は元に戻せません。',
    confirmDeleteAll: 'すべて削除',
    filesSection: 'ファイル管理',
    filesHint: '近日公開。ここでSityと共有したファイルを確認・削除できます。',
    justConnected: (name) => `${name}が正常に接続されました。`,
    initiativeSection: 'プロアクティブメッセージ',
    initiativeMasterLabel: 'Sityからのメッセージを許可する',
    initiativeMasterHint: 'フォローアップする価値があることをSityが検出したとき、メッセージを送ります。',
    initiativeAbandoned: '中断した会話',
    initiativeAbandonedHint: '会話が途中の場合、Sityが後で再開することがあります。',
    initiativeInactivity: '非アクティブ後の再接続',
    initiativeInactivityHint: 'しばらく話していない場合、Sityが様子を聞くことがあります。',
    initiativeOpenLoop: '保留中のトピックのフォローアップ',
    initiativeOpenLoopHint: '解決したいことを話すと、Sityが後で状況を確認することがあります。',
    locationSection: '位置情報',
    locationHint: '天気、レストラン、営業時間など地域に関する質問をするとき、Sityはあなたの場所を使用します。サーバーに保存されます。',
    locationPlaceholder: '都市または地域（例：東京）',
    locationSave: '保存',
    locationDetect: 'ブラウザで検出',
    locationDetecting: '検出中…',
    locationDenied: 'ブラウザにアクセスを拒否されました',
    locationClear: '位置情報を削除',
    locationSourceLabel: (source: string) =>
      source === 'browser' ? 'ブラウザで検出' :
      source === 'manual'  ? '手動で設定' :
      source === 'auto'    ? 'Sityが検出' :
      source === 'denied'  ? 'アクセス拒否' : '',
  },
  chat: {
    guest: 'ゲスト',
    share: '会話を共有',
    clearChat: 'チャットを消去',
    changeBg: '背景を変更',
    changeFont: 'フォントを変更',
    notifProcessing: '処理中…',
    notifBlocked: '通知がブロックされています',
    notifDisable: 'プッシュ通知をオフにする',
    notifEnable: 'プッシュ通知をオンにする',
    logout: 'ログアウト',
    generatingLink: 'リンク生成中…',
    retry: '再試行',
    copied: 'コピーしました！',
    copyLink: 'リンクをコピー',
    close: '閉じる',
    expiresLabel: '有効期限',
    statusOnline: 'オンライン',
    statusProcessing: '処理中...',
    statusDisconnected: '切断',
    showTranscript: '文字起こしを表示',
    hideTranscript: '文字起こしを非表示',
    yesterday: '昨日',
    fontFuturistic: 'フューチャー',
    fontTerminal: 'ターミナル',
    fontElegant: 'エレガント',
    fontCancel: 'キャンセル',
    mySharedLinks: '共有リンク一覧',
    noSharedLinks: 'まだリンクを作成していません。',
    linkActive: '有効',
    linkRevoked: '無効化',
    linkExpired: '期限切れ',
    revokeLink: '無効にする',
    revoking: '無効化中…',
    viewsLabel: '回表示',
  },
  personality: {
    moodTranquil: '穏やか',
    moodNeutral: '普通',
    moodIrritable: '苛立ち',
    moodHostile: '敵対的',
    moodNuclear: '激怒',
    tabTraits: '性格',
    tabAlters: 'Alters',
    restore: 'デフォルトに戻す',
    reload: '再読込',
    loading: '読込中…',
    noData: 'データなし',
  },
  alters: {
    empty: '空',
    saveHere: 'ここに保存',
    load: '読み込む',
    rename: '名前変更',
    copy: 'コピー',
    clear: '削除',
    namePlaceholder: 'Alterの名前',
    save: '保存',
    confirmLoad: '現在の性格が上書きされます',
    confirm: '確認',
    cancel: 'キャンセル',
    confirmClear: 'このプリセットが削除されます',
    copyTarget: '— コピー先 —',
    slotLabel: 'スロット',
    slotEmpty: '（空）',
  },
  dataset: {
    activePrefix: '有効',
    inactive: '無効',
    loading: '読込中…',
    captureActive: 'キャプチャ有効',
    captureHint: 'LoRAデータセット用に会話を記録します',
    preset: 'プリセット',
    noneOption: '— なし —',
    save: '保存',
    disable: '無効化',
    reload: '再読込',
    restorePersonality: '性格をデフォルトに戻す',
  },
  achievements: {
    title: '実績',
    loading: '読込中…',
    unlocked: '実績解除',
    guestBanner: '実績をアンロックして進捗を保存するには登録してください。',
    catPersonalidad: '性格',
    catTools: 'ツール',
    catMemoria: '記憶',
    catDomotica: 'スマートホーム',
    catBackground: 'バックグラウンド',
    catSecrets: '秘密',
  },
  auth: {
    signInTitle: 'ログイン',
    signIn: 'ログイン',
    email: 'メール',
    password: 'パスワード',
    forgotPassword: 'パスワードを忘れた方',
    connecting: '接続中…',
    continueGuest: 'ゲストとして続ける',
    orDivider: 'または',
    googleSignIn: 'G  Googleでログイン（近日公開）',
    noAccount: 'アカウントをお持ちでない方は',
    createAccountLink: 'アカウントを作成',
    createAccount: 'アカウント作成',
    confirmPassword: 'パスワードの確認',
    registering: '登録中…',
    googleRegister: 'G  Googleで登録（近日公開）',
    haveAccount: 'すでにアカウントをお持ちですか？',
    privacyAccept: 'を読み、同意します',
    privacyLink: 'プライバシーポリシー',
    recoverTitle: 'パスワードの回復',
    recoverSent: '登録済みのメールであれば、回復リンクをお送りします。',
    recoverIntro: 'メールアドレスを入力してください。パスワードリセットリンクをお送りします。',
    sendLink: 'リンクを送信',
    sendError: '送信エラー。もう一度お試しください。',
    newPasswordTitle: '新しいパスワード',
    newPasswordLabel: '新しいパスワード',
    newPasswordPlaceholder: '8文字以上、大文字・小文字・数字を含む',
    confirmPasswordLabel: 'パスワードの確認',
    confirmPasswordPlaceholder: 'パスワードをもう一度入力',
    changePassword: 'パスワードを変更',
    changingPassword: '更新中…',
    resetSuccess: 'パスワードが更新されました！新しいパスワードでログインできます。',
    resetIntro: '新しいパスワードを入力してください。',
    resetInvalid: 'このリンクは無効です。「パスワードを忘れた方」から新しいリンクを要求してください。',
    pwMinChars: '8文字以上必要です。',
    pwUppercase: '大文字を1文字以上含めてください。',
    pwLowercase: '小文字を1文字以上含めてください。',
    pwNumber: '数字を1文字以上含めてください。',
    emailRequired: 'メールアドレスは必須です。',
    emailInvalid: '有効なメールアドレスを入力してください。',
    pwMismatch: 'パスワードが一致しません。',
    privacyRequired: 'プライバシーポリシーに同意してください。',
    emailPasswordRequired: 'メールとパスワードは必須です。',
    loginError: 'ログインエラー。',
    registerError: '登録エラー。',
    privacyTitle: 'プライバシーポリシー',
  },
};

export const TRANSLATIONS: Record<UiLang, T> = { es, en, ja };

export const UI_LANGUAGES: { code: UiLang; label: string }[] = [
  { code: 'es', label: 'Español' },
  { code: 'en', label: 'English' },
  { code: 'ja', label: '日本語' },
];
