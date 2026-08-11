export type UiLang = 'es' | 'en' | 'ja';

export interface T {
  nav: {
    chat: string;
    personality: string;
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
    save: string;
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
    // Admin cleanup
    cleanupSection: string;
    cleanupHint: string;
    cleanupUnit: string;
    cleanupNever: string;
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
  };
}

const es: T = {
  nav: {
    chat: 'Chat',
    personality: 'Rasgos',
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
    save: 'Guardar',
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
    cleanupSection: 'Periodicidad de borrado',
    cleanupHint: 'Los mensajes de audio se sustituyen por su transcripción transcurrido este tiempo.',
    cleanupUnit: 'días',
    cleanupNever: '(0 = nunca borrar)',
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
  },
};

const en: T = {
  nav: {
    chat: 'Chat',
    personality: 'Traits',
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
    save: 'Save',
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
    cleanupSection: 'Cleanup period',
    cleanupHint: 'Audio messages are replaced by their transcript after this time.',
    cleanupUnit: 'days',
    cleanupNever: '(0 = never delete)',
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
  },
};

const ja: T = {
  nav: {
    chat: 'チャット',
    personality: '性格',
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
    save: '保存',
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
    cleanupSection: '削除周期',
    cleanupHint: 'この時間が経過すると音声メッセージは文字起こしに置き換えられます。',
    cleanupUnit: '日',
    cleanupNever: '（0 = 削除しない）',
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
  },
};

export const TRANSLATIONS: Record<UiLang, T> = { es, en, ja };

export const UI_LANGUAGES: { code: UiLang; label: string }[] = [
  { code: 'es', label: 'Español' },
  { code: 'en', label: 'English' },
  { code: 'ja', label: '日本語' },
];
