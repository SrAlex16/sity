import { useState, useEffect } from 'react';
import { useVoice, VOICE_DEFAULTS } from '../hooks/useVoice';
import type { VoiceSettings } from '../hooks/useVoice';
import { useLanguage, SUPPORTED_LANGUAGES } from '../hooks/useLanguage';
import type { LanguageCode } from '../hooks/useLanguage';
import { useIntegrations } from '../hooks/useIntegrations';
import { TRANSLATIONS, UI_LANGUAGES } from '../i18n/translations';
import type { UiLang } from '../i18n/translations';
import styles from './VoiceScreen.module.css';

// ── Icons ────────────────────────────────────────────────────────────────────

function IconReload() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" width="16" height="16">
      <path d="M23 4v6h-6" />
      <path d="M1 20v-6h6" />
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
    </svg>
  );
}

// ── Screen ───────────────────────────────────────────────────────────────────

interface SettingsScreenProps {
  role: string;
  uiLang: UiLang;
  onUiLangChange: (lang: UiLang) => void;
}

export function VoiceScreen({ role, uiLang, onUiLangChange }: SettingsScreenProps) {
  const tl = TRANSLATIONS[uiLang].settings;
  const { settings, isLoading, error, save, reload } = useVoice();
  const { settings: langSettings, isLoading: langLoading, error: langError, save: saveLang } = useLanguage();
  const { integrations, isLoading: intLoading, error: intError, refresh: refreshIntegrations } = useIntegrations();
  const [form, setForm] = useState<VoiceSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // Integrations state
  const [connecting, setConnecting] = useState<string | null>(null);
  const [disconnectConfirm, setDisconnectConfirm] = useState<string | null>(null);
  const [disconnecting, setDisconnecting] = useState<string | null>(null);
  const [justConnected, setJustConnected] = useState<string | null>(null);
  const [bgValue] = useState<string>(() => localStorage.getItem('sity_bg') ?? '');

  useEffect(() => {
    if (settings) setForm(settings);
  }, [settings]);

  const backgroundStyle: React.CSSProperties = bgValue
    ? (bgValue.startsWith('/') || bgValue.startsWith('data:') || bgValue.startsWith('http'))
      ? { backgroundImage: `url(${bgValue})`, backgroundSize: 'cover', backgroundPosition: 'center' }
      : { background: bgValue }
    : {};

  const busy = saving || isLoading;

  const handleSave = async () => {
    if (!form) return;
    setSaving(true);
    try { await save(form); } catch { /* error shown via hook */ } finally { setSaving(false); }
  };

  const handleRestore = async () => {
    setForm(VOICE_DEFAULTS);
    setSaving(true);
    try { await save(VOICE_DEFAULTS); } catch { /* error shown via hook */ } finally { setSaving(false); }
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const resp = await fetch('/chat/export', { credentials: 'include' });
      if (!resp.ok) return;
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'sity-conversacion.json';
      a.click();
      URL.revokeObjectURL(url);
    } catch { /* silent */ } finally {
      setExporting(false);
    }
  };

  // Clear the "just connected" flash after 5 s
  useEffect(() => {
    if (!justConnected) return;
    const id = setTimeout(() => setJustConnected(null), 5000);
    return () => clearTimeout(id);
  }, [justConnected]);

  // Receive OAuth result from the popup tab via BroadcastChannel.
  // Fallback: refresh integrations whenever this tab regains visibility
  // (covers the case where VoiceScreen was not mounted when the popup closed).
  useEffect(() => {
    if (role === 'guest') return;

    let bc: BroadcastChannel | null = null;
    try {
      bc = new BroadcastChannel('sity_oauth');
      bc.onmessage = (ev: MessageEvent) => {
        if (ev.data?.type === 'oauth_connected') {
          void refreshIntegrations();
          setJustConnected((ev.data.provider as string) ?? null);
        }
      };
    } catch { /* BroadcastChannel not available */ }

    const onVisible = () => {
      if (document.visibilityState === 'visible') void refreshIntegrations();
    };
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      bc?.close();
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [role, refreshIntegrations]);

  const handleConnect = async (provider: string) => {
    setConnecting(provider);
    try {
      const resp = await fetch(`/auth/integrations/${provider}/connect`, { credentials: 'include' });
      if (!resp.ok) return;
      const { auth_url } = await resp.json() as { auth_url: string };
      window.open(auth_url, '_blank');
    } catch { /* silent */ } finally {
      setConnecting(null);
    }
  };

  const handleDisconnect = async (provider: string) => {
    setDisconnecting(provider);
    try {
      const resp = await fetch(`/auth/integrations/${provider}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      if (resp.ok) {
        setDisconnectConfirm(null);
        await refreshIntegrations();
      }
    } catch { /* silent */ } finally {
      setDisconnecting(null);
    }
  };

  const handleDeleteAccount = async () => {
    setDeleting(true);
    try {
      const resp = await fetch('/auth/me', { method: 'DELETE', credentials: 'include' });
      if (resp.ok) window.location.reload();
      else setDeleteConfirm(false);
    } catch {
      setDeleteConfirm(false);
    } finally {
      setDeleting(false);
    }
  };

  const patch = (delta: Partial<VoiceSettings>) =>
    setForm((prev) => prev ? { ...prev, ...delta } : prev);

  return (
    <div className={styles.screen}>
      {bgValue && <div className={styles.background} style={backgroundStyle} />}
      <div className={styles.overlay} />

      {/* Header */}
      <header className={styles.header}>
        <div className={styles.headerText}>
          <span className={styles.titleJp}>設定</span>
          <span className={styles.titleEs}>{tl.title}</span>
        </div>
        <button className={styles.reloadBtn} onClick={() => void reload()} disabled={busy}>
          <IconReload />
          <span>{tl.reload}</span>
        </button>
      </header>

      {/* Content */}
      <div className={styles.content}>
        {error && <p className={styles.errorMsg}>{error}</p>}

        {!form && isLoading && <p className={styles.loading}>{tl.loading}</p>}

        {form && (
          <>
            {/* Voz — modo de respuesta, transcripción, respuestas largas */}
            <div className={styles.section}>
              <p className={styles.sectionJp}>ボイス</p>
              <p className={styles.sectionEs}>{tl.voice}</p>

              {/* Modo de respuesta */}
              <p className={styles.sectionHint} style={{ marginBottom: 10 }}>{tl.responseMode}</p>
              <div className={styles.radioGroup}>
                {(['always', 'never', 'symmetric'] as const).map((mode) => (
                  <label key={mode} className={styles.radioRow}>
                    <input
                      type="radio"
                      className={styles.hiddenInput}
                      name="voice_response_mode"
                      value={mode}
                      checked={form.voice_response_mode === mode}
                      onChange={() => patch({ voice_response_mode: mode })}
                    />
                    <span className={styles.radioIndicator} />
                    <span className={styles.optionText}>{
                      mode === 'always' ? tl.modeAlways :
                      mode === 'never'  ? tl.modeNever  :
                                          tl.modeSymmetric
                    }</span>
                  </label>
                ))}
              </div>

              {/* Transcripción */}
              <label className={styles.checkboxRow} style={{ marginTop: 18 }}>
                <input
                  type="checkbox"
                  className={styles.hiddenInput}
                  checked={form.voice_include_text}
                  onChange={(e) => patch({ voice_include_text: e.target.checked })}
                />
                <span className={styles.checkboxIndicator} />
                <div>
                  <p className={styles.sectionJp}>テキスト起こしも含む</p>
                  <p className={styles.sectionEs}>{tl.includeTranscript}</p>
                </div>
              </label>

              {/* Respuestas largas */}
              <p className={styles.sectionHint} style={{ marginTop: 18, marginBottom: 10 }}>{tl.longResponses}</p>
              <div className={styles.radioGroup}>
                {(['split', 'text_only'] as const).map((action) => (
                  <label key={action} className={styles.radioRow}>
                    <input
                      type="radio"
                      className={styles.hiddenInput}
                      name="voice_long_response_action"
                      value={action}
                      checked={form.voice_long_response_action === action}
                      onChange={() => patch({ voice_long_response_action: action })}
                    />
                    <span className={styles.radioIndicator} />
                    <span className={styles.optionText}>{action === 'split' ? tl.longSplit : tl.longTextOnly}</span>
                  </label>
                ))}
              </div>

              {/* Restaurar valores — dentro de la sección Voz */}
              <button
                className={`${styles.sectionBtn} ${styles.btnSecondary}`}
                style={{ marginTop: 18 }}
                onClick={handleRestore}
                disabled={busy}
              >
                {tl.restoreVoice}
              </button>
            </div>

            {/* Periodicidad de borrado — admin only, global */}
            {role === 'admin' && (
              <div className={styles.section}>
                <p className={styles.sectionJp}>保存期間</p>
                <p className={styles.sectionEs}>{tl.cleanupSection}</p>
                <p className={styles.sectionHint}>{tl.cleanupHint}</p>
                <div className={styles.cleanupRow}>
                  <input
                    type="number"
                    className={styles.cleanupInput}
                    min={0}
                    max={365}
                    value={form.audio_cleanup_days}
                    onChange={(e) => patch({ audio_cleanup_days: Math.max(0, Math.min(365, Number(e.target.value))) })}
                  />
                  <span className={styles.cleanupUnit}>{tl.cleanupUnit}</span>
                  <span className={styles.cleanupHint}>{tl.cleanupNever}</span>
                </div>
              </div>
            )}
          </>
        )}

        {/* Idioma de la app — Sistema 1, funcional */}
        <div className={styles.section}>
          <p className={styles.sectionJp}>言語</p>
          <p className={styles.sectionEs}>{tl.uiLanguageSection}</p>
          <p className={styles.sectionHint}>{tl.uiLanguageHint}</p>
          <p className={styles.sectionHint} style={{ marginBottom: 10, opacity: 0.7 }}>
            ⓘ {tl.uiLanguageNote}
          </p>
          <select
            className={styles.select}
            value={uiLang}
            onChange={(e) => onUiLangChange(e.target.value as UiLang)}
          >
            {UI_LANGUAGES.map(({ code, label }) => (
              <option key={code} value={code}>{label}</option>
            ))}
          </select>
        </div>

        {/* Idioma de conversación de Sity — Sistema 2, funcional */}
        {role !== 'guest' && (
          <div className={styles.section}>
            <p className={styles.sectionJp}>会話言語</p>
            <p className={styles.sectionEs}>{tl.sityLanguageSection}</p>
            <p className={styles.sectionHint}>{tl.sityLanguageHint}</p>
            <p className={styles.sectionHint} style={{ marginBottom: 10, opacity: 0.7 }}>
              ⓘ {tl.sityLanguageNote}
            </p>
            {langLoading && !langSettings && <p className={styles.sectionHint}>{tl.loading}</p>}
            {langError && <p className={styles.errorMsg}>{langError}</p>}
            {langSettings && (
              <select
                className={styles.select}
                value={langSettings.language_override}
                onChange={(e) => void saveLang(e.target.value as LanguageCode)}
                disabled={langLoading}
              >
                {SUPPORTED_LANGUAGES.map(({ code, label }) => (
                  <option key={code} value={code}>{label}</option>
                ))}
              </select>
            )}
          </div>
        )}

        {/* Integraciones */}
        {role !== 'guest' && (
          <div className={styles.section}>
            <p className={styles.sectionJp}>連携設定</p>
            <p className={styles.sectionEs}>{tl.integrationsSection}</p>
            {justConnected && (
              <p className={styles.successMsg}>
                {tl.justConnected(justConnected === 'google' ? 'Google' : 'Spotify')}
              </p>
            )}
            {intLoading && <p className={styles.sectionHint}>{tl.loading}</p>}
            {intError && <p className={styles.errorMsg}>{intError}</p>}
            {!intLoading && !intError && (
              <div className={styles.providerList}>
                {(['google', 'spotify'] as const).map((provider) => {
                  const info = integrations.find((i) => i.provider === provider);
                  const isConnected = info?.connected ?? false;
                  const isConfirming = disconnectConfirm === provider;
                  const isDisconnecting = disconnecting === provider;
                  return (
                    <div key={provider} className={styles.providerRow}>
                      <div>
                        <p className={styles.providerName}>
                          {provider === 'google' ? 'Google' : 'Spotify'}
                        </p>
                        <p className={isConnected ? styles.statusConnected : styles.sectionHint}>
                          {isConnected ? tl.connected : tl.notConnected}
                        </p>
                      </div>
                      <div>
                        {!isConnected ? (
                          <button
                            className={`${styles.sectionBtn} ${styles.btnCyan}`}
                            onClick={() => void handleConnect(provider)}
                            disabled={connecting === provider}
                          >
                            {connecting === provider ? '…' : tl.connect}
                          </button>
                        ) : isConfirming ? (
                          <div className={styles.confirmActions}>
                            <button
                              className={`${styles.sectionBtn} ${styles.btnSecondary}`}
                              onClick={() => setDisconnectConfirm(null)}
                              disabled={isDisconnecting}
                            >
                              {tl.cancel}
                            </button>
                            <button
                              className={`${styles.sectionBtn} ${styles.btnMagenta}`}
                              onClick={() => void handleDisconnect(provider)}
                              disabled={isDisconnecting}
                            >
                              {isDisconnecting ? '…' : tl.confirmDisconnect}
                            </button>
                          </div>
                        ) : (
                          <button
                            className={`${styles.sectionBtn} ${styles.btnMagenta}`}
                            onClick={() => setDisconnectConfirm(provider)}
                          >
                            {tl.disconnect}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Exportar conversación */}
        {role !== 'guest' && (
          <div className={styles.section}>
            <p className={styles.sectionJp}>会話エクスポート</p>
            <p className={styles.sectionEs}>{tl.exportSection}</p>
            <p className={styles.sectionHint}>{tl.exportHint}</p>
            <button
              className={`${styles.sectionBtn} ${styles.btnCyan}`}
              onClick={() => void handleExport()}
              disabled={exporting}
            >
              {exporting ? '…' : tl.download}
            </button>
          </div>
        )}

        {/* Borrar todos mis datos */}
        {role !== 'guest' && (
          <div className={styles.section}>
            <p className={styles.sectionJp}>データ削除</p>
            <p className={styles.sectionEs}>{tl.deleteSection}</p>
            <p className={styles.sectionHint}>{tl.deleteHint}</p>
            {!deleteConfirm ? (
              <button
                className={`${styles.sectionBtn} ${styles.btnMagenta}`}
                onClick={() => setDeleteConfirm(true)}
              >
                {tl.deleteAccount}
              </button>
            ) : (
              <div className={styles.confirmRow}>
                <p className={styles.confirmWarning}>{tl.deleteConfirmWarning}</p>
                <div className={styles.confirmActions}>
                  <button
                    className={`${styles.sectionBtn} ${styles.btnSecondary}`}
                    onClick={() => setDeleteConfirm(false)}
                    disabled={deleting}
                  >
                    {tl.cancel}
                  </button>
                  <button
                    className={`${styles.sectionBtn} ${styles.btnMagenta}`}
                    onClick={() => void handleDeleteAccount()}
                    disabled={deleting}
                  >
                    {deleting ? '…' : tl.confirmDeleteAll}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Gestión de archivos — placeholder */}
        <div className={styles.section}>
          <p className={styles.sectionJp}>ファイル管理</p>
          <p className={styles.sectionEs}>{tl.filesSection}</p>
          <p className={styles.sectionHint}>{tl.filesHint}</p>
        </div>
      </div>

      {/* Footer actions */}
      <div className={styles.footer}>
        <button className={`${styles.btn} ${styles.btnCyan}`} onClick={handleSave} disabled={busy || !form}>
          {saving ? '…' : tl.save}
        </button>
      </div>
    </div>
  );
}
