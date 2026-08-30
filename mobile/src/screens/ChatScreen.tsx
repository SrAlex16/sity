import { useRef, useState, useEffect, useCallback } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { UseChatResult } from '../hooks/useChat';
import type { CurrentUser } from '../hooks/useAuth';
import { TRANSLATIONS } from '../i18n/translations';
import type { UiLang } from '../i18n/translations';
import { useVoice } from '../hooks/useVoice';
import { useNotifications } from '../hooks/useNotifications';
import { TypingIndicator } from '../components/TypingIndicator';
import { resizeImageToBase64, type ResizedImage } from '../utils/imageResize';
import { StatusBadge } from '../components/StatusBadge';
import { BgJobIndicator } from '../components/BgJobIndicator';
import { BackgroundPicker } from '../components/BackgroundPicker';
import { FontPicker } from '../components/FontPicker';
import { MessageList } from '../components/MessageList';
import { RecordingUI } from '../components/RecordingUI';
import styles from './ChatScreen.module.css';

// ── Icons ─────────────────────────────────────────────────────────────────────

function IconRobot() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="100%" height="100%">
      <rect x="3" y="8" width="18" height="11" rx="2" />
      <path d="M8 8V6a4 4 0 0 1 8 0v2" />
      <circle cx="9" cy="13" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="15" cy="13" r="1.5" fill="currentColor" stroke="none" />
      <line x1="9" y1="17" x2="15" y2="17" />
    </svg>
  );
}

function IconDots() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
      <circle cx="12" cy="5" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="12" cy="19" r="1.5" />
    </svg>
  );
}

function IconShare() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="16" height="16">
      <circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" />
      <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" /><line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
    </svg>
  );
}

function IconClip() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="20" height="20">
      <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66L9.42 16.41a2 2 0 0 1-2.83-2.83l8.49-8.48" />
    </svg>
  );
}

function IconMic() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="20" height="20">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  );
}

function IconSend() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="18" height="18">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  );
}

function IconStop() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  );
}

// ── Shared link item ──────────────────────────────────────────────────────────

interface SharedLinkItem {
  share_id: string;
  url: string;
  created_at: string;
  expires_at: string;
  view_count: number;
  is_active: boolean;
  revoked_at: string | null;
}

// ── Recording state ───────────────────────────────────────────────────────────

interface RecordingCtx {
  mediaRecorder: MediaRecorder;
  analyserNode: AnalyserNode;
  audioContext: AudioContext;
  chunks: Blob[];
  startTime: number;
}

// ── ChatScreen ────────────────────────────────────────────────────────────────

const DATE_LOCALE: Record<UiLang, string> = { es: 'es-ES', en: 'en-US', ja: 'ja-JP' };

interface ChatScreenProps extends UseChatResult {
  onLogout?: () => void;
  currentUser?: CurrentUser | null;
  uiLang?: UiLang;
}

export function ChatScreen({ messages, status, sendMessage, sendAudio, clearMessages, canCancel, cancel, backgroundJobsActive, backgroundJustFinished, onLogout, currentUser, uiLang = 'es' }: ChatScreenProps) {
  const tl = TRANSLATIONS[uiLang].chat;
  const { settings: voiceSettings } = useVoice();
  const voiceIncludeText = voiceSettings?.voice_include_text ?? true;

  const isGuest = !currentUser || currentUser.role === 'guest';
  const notifications = useNotifications(isGuest);

  const [inputText, setInputText] = useState(() => localStorage.getItem('sity_draft_message') ?? '');
  const [activeAudioId, setActiveAudioId] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [bgPickerOpen, setBgPickerOpen] = useState(false);
  const [fontPickerOpen, setFontPickerOpen] = useState(false);
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [shareData, setShareData] = useState<{ url: string; expiresAt: string } | null>(null);
  const [shareLoading, setShareLoading] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);
  const [shareError, setShareError] = useState<string | null>(null);
  const [sharedLinksOpen, setSharedLinksOpen] = useState(false);
  const [sharedLinks, setSharedLinks] = useState<SharedLinkItem[] | null>(null);
  const [sharedLinksLoading, setSharedLinksLoading] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [activeFont, setActiveFont] = useState<'orbitron' | 'sharetech' | 'rajdhani'>(
    () => (localStorage.getItem('sity_font') ?? 'orbitron') as 'orbitron' | 'sharetech' | 'rajdhani'
  );
  const [bgValue, setBgValue] = useState<string>(() => localStorage.getItem('sity_bg') ?? '/backgrounds/wallpaper1.png');
  const [avatarSrc] = useState<string>(() => localStorage.getItem('sity_avatar') ?? '/icons/sity_icon.jpg');
  const [recording, setRecording] = useState<RecordingCtx | null>(null);
  const [pendingImage, setPendingImage] = useState<ResizedImage | null>(null);

  const handleAudioPlay = useCallback(
    (id: string) => setActiveAudioId(id),
    [],
  );
  const handleAudioEnded = useCallback(
    (id: string) => setActiveAudioId((prev) => (prev === id ? null : prev)),
    [],
  );

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const draftSaveTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Scroll to bottom on new content
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, status]);

  // Auto-resize textarea
  const resizeTextarea = useCallback((el: HTMLTextAreaElement) => {
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 144)}px`;
  }, []);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    setInputText(value);
    resizeTextarea(e.target);

    // Debounce del guardado en localStorage — evita I/O síncrono
    // en cada tecla pulsada (causaba lag perceptible en el input).
    if (draftSaveTimeout.current) {
      clearTimeout(draftSaveTimeout.current);
    }
    draftSaveTimeout.current = setTimeout(() => {
      localStorage.setItem('sity_draft_message', value);
    }, 400);
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';
    try {
      const resized = await resizeImageToBase64(file);
      setPendingImage(resized);
    } catch { /* ignore — imagen inválida o cancelada */ }
  };

  const handleSend = useCallback(() => {
    const text = inputText.trim();
    if (!text && !pendingImage) return;
    if (draftSaveTimeout.current) {
      clearTimeout(draftSaveTimeout.current);
      draftSaveTimeout.current = null;
    }
    const imageToSend = pendingImage;
    setInputText('');
    setPendingImage(null);
    localStorage.removeItem('sity_draft_message');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    void sendMessage(text || ' ', imageToSend ? [imageToSend] : undefined);
  }, [inputText, pendingImage, sendMessage]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  // ── Recording ──────────────────────────────────────────────────────────────

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const audioContext = new AudioContext();
      const source = audioContext.createMediaStreamSource(stream);
      const analyserNode = audioContext.createAnalyser();
      analyserNode.fftSize = 256;
      source.connect(analyserNode);

      const chunks: Blob[] = [];
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };

      mediaRecorder.start();
      setRecording({ mediaRecorder, analyserNode, audioContext, chunks, startTime: Date.now() });
    } catch { /* mic unavailable or permission denied */ }
  };

  const cancelRecording = () => {
    if (!recording) return;
    recording.mediaRecorder.stream.getTracks().forEach((t) => t.stop());
    recording.mediaRecorder.stop();
    void recording.audioContext.close();
    setRecording(null);
  };

  const sendRecording = () => {
    if (!recording) return;
    const { mediaRecorder, audioContext, chunks, startTime } = recording;
    const durationSecs = (Date.now() - startTime) / 1000;

    mediaRecorder.onstop = async () => {
      void audioContext.close();
      const blob = new Blob(chunks, { type: 'audio/webm' });
      setRecording(null);
      localStorage.removeItem('sity_draft_message');
      await sendAudio(blob, durationSecs);
    };

    mediaRecorder.stream.getTracks().forEach((t) => t.stop());
    mediaRecorder.stop();
  };

  // Cancel pending draft save on unmount
  useEffect(() => {
    return () => {
      if (draftSaveTimeout.current) {
        clearTimeout(draftSaveTimeout.current);
      }
    };
  }, []);

  // Stop recording on unmount
  useEffect(() => {
    return () => {
      if (recording) {
        recording.mediaRecorder.stream.getTracks().forEach((t) => t.stop());
        void recording.audioContext.close();
      }
    };
  }, [recording]);

  // ── Share ──────────────────────────────────────────────────────────────────

  const handleShare = async () => {
    setMenuOpen(false);
    setShareLoading(true);
    setShareModalOpen(true);
    setShareData(null);
    setShareCopied(false);
    setShareError(null);
    try {
      const resp = await fetch('/chat/share', { method: 'POST', credentials: 'include' });
      if (!resp.ok) {
        let detail = `Error ${resp.status}`;
        try {
          const body = (await resp.json()) as { detail?: string };
          if (body.detail) detail = body.detail;
        } catch { /* ignore parse failure */ }
        setShareError(detail);
        return;
      }
      const body = await resp.json() as { share_id: string; url: string; expires_at: string };
      setShareData({ url: body.url, expiresAt: body.expires_at });
    } catch (err) {
      setShareError(err instanceof Error ? err.message : 'Sin conexión con el servidor');
    } finally {
      setShareLoading(false);
    }
  };

  const handleCopyShareLink = () => {
    if (!shareData) return;
    void navigator.clipboard.writeText(shareData.url).then(() => {
      setShareCopied(true);
      setTimeout(() => setShareCopied(false), 2000);
    });
  };

  // ── Shared links ──────────────────────────────────────────────────────────

  const handleOpenSharedLinks = async () => {
    setMenuOpen(false);
    setSharedLinksOpen(true);
    if (sharedLinks !== null) return;
    setSharedLinksLoading(true);
    try {
      const resp = await fetch('/chat/share', { credentials: 'include' });
      if (!resp.ok) return;
      const body = await resp.json() as { ok: boolean; shares: SharedLinkItem[] };
      setSharedLinks(body.shares);
    } catch { /* ignore */ } finally {
      setSharedLinksLoading(false);
    }
  };

  const handleRevokeLink = async (shareId: string) => {
    setRevokingId(shareId);
    try {
      const resp = await fetch(`/chat/share/${shareId}`, { method: 'DELETE', credentials: 'include' });
      if (!resp.ok) return;
      setSharedLinks((prev) =>
        prev
          ? prev.map((s) =>
              s.share_id === shareId
                ? { ...s, is_active: false, revoked_at: new Date().toISOString() }
                : s
            )
          : prev
      );
    } catch { /* ignore */ } finally {
      setRevokingId(null);
    }
  };

  // ── Background ─────────────────────────────────────────────────────────────

  const handleBgSelect = (bg: string) => {
    setBgValue(bg);
    localStorage.setItem('sity_bg', bg);
    setBgPickerOpen(false);
  };

  // ── Context menu close on outside click ───────────────────────────────────

  useEffect(() => {
    if (!menuOpen) return;
    const close = () => setMenuOpen(false);
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, [menuOpen]);

  const backgroundStyle: React.CSSProperties = bgValue
    ? (bgValue.startsWith('/') || bgValue.startsWith('data:') || bgValue.startsWith('http'))
      ? { backgroundImage: `url(${bgValue})`, backgroundSize: 'cover', backgroundPosition: 'center' }
      : { background: bgValue }
    : {};

  return (
    <>
      <div className={styles.screen}>
        {/* Background */}
        <AnimatePresence mode="sync">
          <motion.div
            key={bgValue || '__solid'}
            className={styles.background}
            style={backgroundStyle}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.5 }}
          />
        </AnimatePresence>
        <div className={styles.overlay} />

        {/* Header */}
        <header className={styles.header}>
          <div className={styles.avatarWrap}>
            {avatarSrc
              ? <img src={avatarSrc} alt="Sity" className={styles.avatarImg} />
              : <div className={styles.avatarPlaceholder}><IconRobot /></div>
            }
          </div>

          <div className={styles.headerInfo}>
            <span className={styles.headerName}>Sity</span>
            <div className={styles.headerStatusRow}>
              <StatusBadge status={status} uiLang={uiLang} />
              <BgJobIndicator active={backgroundJobsActive > 0} justFinished={backgroundJustFinished} />
            </div>
            {currentUser && (
              <span className={`${styles.identityBadge} ${currentUser.role === 'guest' ? styles.identityGuest : styles.identityUser}`}>
                {currentUser.role === 'guest'
                  ? tl.guest
                  : currentUser.displayName ?? currentUser.email ?? currentUser.role}
              </span>
            )}
          </div>

          <div className={styles.headerMenu}>
            <button
              className={styles.menuBtn}
              onClick={(e) => { e.stopPropagation(); setMenuOpen((v) => !v); }}
              aria-label="Menú"
            >
              <IconDots />
            </button>

            <AnimatePresence>
              {menuOpen && (
                <motion.div
                  className={styles.contextMenu}
                  initial={{ opacity: 0, scale: 0.92, y: -6 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.92, y: -6 }}
                  transition={{ duration: 0.14 }}
                  onClick={(e) => e.stopPropagation()}
                >
                  {currentUser && currentUser.role !== 'guest' && (
                    <button className={styles.menuItem} onClick={() => void handleShare()}>
                      <IconShare /> {tl.share}
                    </button>
                  )}
                  {currentUser && currentUser.role !== 'guest' && (
                    <button className={styles.menuItem} onClick={() => void handleOpenSharedLinks()}>
                      {tl.mySharedLinks}
                    </button>
                  )}
                  <button className={styles.menuItem} onClick={() => { clearMessages(); setMenuOpen(false); }}>
                    {tl.clearChat}
                  </button>
                  <button className={styles.menuItem} onClick={() => { setMenuOpen(false); setBgPickerOpen(true); }}>
                    {tl.changeBg}
                  </button>
                  <button className={styles.menuItem} onClick={() => { setMenuOpen(false); setFontPickerOpen(true); }}>
                    {tl.changeFont}
                  </button>
                  {!isGuest && notifications.isSupported && (
                    <button
                      className={styles.menuItem}
                      disabled={notifications.isLoading || notifications.permission === 'denied'}
                      onClick={(e) => {
                        e.stopPropagation();
                        if (notifications.isSubscribed) {
                          void notifications.unsubscribe();
                        } else {
                          void notifications.subscribe();
                        }
                      }}
                    >
                      {notifications.isLoading
                        ? tl.notifProcessing
                        : notifications.permission === 'denied'
                          ? tl.notifBlocked
                          : notifications.isSubscribed
                            ? tl.notifDisable
                            : tl.notifEnable}
                    </button>
                  )}
                  {!isGuest && notifications.error && (
                    <span style={{ fontSize: '0.7rem', color: 'var(--color-error, #ff4d6d)', padding: '0.25rem 0.75rem', display: 'block' }}>
                      {notifications.error}
                    </span>
                  )}
                  {onLogout && (
                    <>
                      <div className={styles.menuDivider} />
                      <button
                        className={`${styles.menuItem} ${styles.menuItemDanger}`}
                        onClick={() => { setMenuOpen(false); void onLogout(); }}
                      >
                        {tl.logout}
                      </button>
                    </>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </header>

        {/* Messages */}
        <div className={styles.messages}>
          <MessageList
            messages={messages}
            activeAudioId={activeAudioId}
            onAudioPlay={handleAudioPlay}
            onAudioEnded={handleAudioEnded}
            voiceIncludeText={voiceIncludeText}
            uiLang={uiLang}
          />
          {status === 'procesando' && <TypingIndicator />}
          <div ref={messagesEndRef} />
        </div>

        {/* Input area — switches between normal input and RecordingUI */}
        <div className={styles.inputArea}>
          <AnimatePresence mode="wait">
            {recording ? (
              <motion.div
                key="recording"
                className={styles.inputRow}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 8 }}
                transition={{ duration: 0.15 }}
              >
                <RecordingUI
                  analyserNode={recording.analyserNode}
                  onCancel={cancelRecording}
                  onSend={sendRecording}
                />
              </motion.div>
            ) : (
              <motion.div
                key="input"
                className={styles.inputRow}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 8 }}
                transition={{ duration: 0.15 }}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/jpeg,image/png,image/webp,image/gif"
                  style={{ display: 'none' }}
                  onChange={handleFileChange}
                />
                <button
                  className={styles.iconBtn}
                  aria-label="Adjuntar imagen"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <IconClip />
                </button>

                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {pendingImage && (
                    <div style={{ position: 'relative', display: 'inline-block', alignSelf: 'flex-start' }}>
                      <img
                        src={pendingImage.previewUrl}
                        alt="preview"
                        style={{ height: 56, borderRadius: 8, objectFit: 'cover', border: '1px solid var(--color-border)' }}
                      />
                      <button
                        onClick={() => setPendingImage(null)}
                        aria-label="Quitar imagen"
                        style={{
                          position: 'absolute', top: -6, right: -6,
                          background: 'var(--color-bg)', border: '1px solid var(--color-border)',
                          borderRadius: '50%', width: 18, height: 18,
                          fontSize: 10, cursor: 'pointer', color: 'var(--text-secondary)',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                        }}
                      >✕</button>
                    </div>
                  )}
                  <textarea
                    ref={textareaRef}
                    className={styles.textarea}
                    value={inputText}
                    onChange={handleInputChange}
                    onKeyDown={handleKeyDown}
                    placeholder="メッセージを入力..."
                    rows={1}
                  />
                </div>

                <button
                  className={styles.iconBtn}
                  onClick={startRecording}
                  aria-label="Grabar nota de voz"
                >
                  <IconMic />
                </button>

                {canCancel && !inputText.trim() && !pendingImage ? (
                  <motion.button
                    className={styles.cancelBtn}
                    onClick={cancel}
                    whileTap={{ scale: 0.88 }}
                    aria-label="Cancelar respuesta"
                  >
                    <IconStop />
                  </motion.button>
                ) : (
                  <motion.button
                    className={styles.sendBtn}
                    onClick={handleSend}
                    disabled={!inputText.trim() && !pendingImage}
                    whileTap={{ scale: 0.88 }}
                    aria-label="Enviar"
                  >
                    <IconSend />
                  </motion.button>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      <BackgroundPicker
        open={bgPickerOpen}
        onClose={() => setBgPickerOpen(false)}
        onSelect={handleBgSelect}
      />
      <FontPicker
        open={fontPickerOpen}
        activeFont={activeFont}
        onClose={() => setFontPickerOpen(false)}
        onSelect={setActiveFont}
        uiLang={uiLang}
      />

      {/* Share modal */}
      <AnimatePresence>
        {shareModalOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            style={{
              position: 'fixed', inset: 0, zIndex: 200,
              background: 'rgba(0,0,0,0.72)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              padding: '1.5rem',
            }}
            onClick={() => setShareModalOpen(false)}
          >
            <motion.div
              initial={{ scale: 0.92, y: 12 }}
              animate={{ scale: 1, y: 0 }}
              exit={{ scale: 0.92, y: 12 }}
              transition={{ duration: 0.18 }}
              style={{
                background: 'var(--color-surface, #0f1117)',
                border: '1px solid var(--color-border, #1e2130)',
                borderRadius: '12px',
                padding: '1.5rem',
                width: '100%',
                maxWidth: '420px',
                fontFamily: 'var(--font-mono)',
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <p style={{ margin: '0 0 0.75rem', fontSize: '0.78rem', color: 'var(--text-secondary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                {tl.share}
              </p>
              {shareLoading && (
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>{tl.generatingLink}</p>
              )}
              {shareError && (
                <>
                  <p style={{ margin: '0 0 0.75rem', fontSize: '0.8rem', color: 'var(--color-error, #ff4d6d)' }}>
                    {shareError}
                  </p>
                  <button
                    onClick={() => void handleShare()}
                    style={{
                      width: '100%',
                      padding: '0.45rem',
                      background: 'none',
                      border: '1px solid var(--color-error, #ff4d6d)',
                      borderRadius: '6px',
                      color: 'var(--color-error, #ff4d6d)',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.72rem',
                      cursor: 'pointer',
                      marginBottom: '0.5rem',
                    }}
                  >
                    {tl.retry}
                  </button>
                </>
              )}
              {shareData && (
                <>
                  <div style={{
                    background: 'rgba(255,255,255,0.04)',
                    border: '1px solid var(--color-border, #1e2130)',
                    borderRadius: '6px',
                    padding: '0.6rem 0.75rem',
                    fontSize: '0.72rem',
                    color: 'var(--neon-cyan, #00f5ff)',
                    wordBreak: 'break-all',
                    marginBottom: '0.75rem',
                    userSelect: 'all',
                  }}>
                    {shareData.url}
                  </div>
                  <p style={{ margin: '0 0 0.75rem', fontSize: '0.7rem', color: 'var(--text-secondary)', opacity: 0.6 }}>
                    {tl.expiresLabel}: {new Date(shareData.expiresAt).toLocaleDateString(DATE_LOCALE[uiLang], { day: 'numeric', month: 'long', year: 'numeric' })}
                  </p>
                  <button
                    onClick={handleCopyShareLink}
                    style={{
                      width: '100%',
                      padding: '0.55rem',
                      background: shareCopied ? 'rgba(0,245,255,0.12)' : 'rgba(0,245,255,0.07)',
                      border: '1px solid var(--neon-cyan, #00f5ff)',
                      borderRadius: '6px',
                      color: 'var(--neon-cyan, #00f5ff)',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.75rem',
                      letterSpacing: '0.05em',
                      cursor: 'pointer',
                      transition: 'background 0.15s',
                    }}
                  >
                    {shareCopied ? tl.copied : tl.copyLink}
                  </button>
                </>
              )}
              <button
                onClick={() => setShareModalOpen(false)}
                style={{
                  marginTop: '0.75rem',
                  width: '100%',
                  padding: '0.45rem',
                  background: 'none',
                  border: '1px solid var(--color-border, #1e2130)',
                  borderRadius: '6px',
                  color: 'var(--text-secondary)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.72rem',
                  cursor: 'pointer',
                }}
              >
                {tl.close}
              </button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Shared links modal */}
      <AnimatePresence>
        {sharedLinksOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            style={{
              position: 'fixed', inset: 0, zIndex: 200,
              background: 'rgba(0,0,0,0.72)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              padding: '1.5rem',
            }}
            onClick={() => setSharedLinksOpen(false)}
          >
            <motion.div
              initial={{ scale: 0.92, y: 12 }}
              animate={{ scale: 1, y: 0 }}
              exit={{ scale: 0.92, y: 12 }}
              transition={{ duration: 0.18 }}
              style={{
                background: 'var(--color-surface, #0f1117)',
                border: '1px solid var(--color-border, #1e2130)',
                borderRadius: '12px',
                padding: '1.5rem',
                width: '100%',
                maxWidth: '480px',
                maxHeight: '75vh',
                display: 'flex',
                flexDirection: 'column',
                fontFamily: 'var(--font-mono)',
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <p style={{ margin: '0 0 1rem', fontSize: '0.78rem', color: 'var(--text-secondary)', letterSpacing: '0.06em', textTransform: 'uppercase', flexShrink: 0 }}>
                {tl.mySharedLinks}
              </p>

              <div style={{ overflowY: 'auto', flex: 1 }}>
                {sharedLinksLoading && (
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>…</p>
                )}
                {!sharedLinksLoading && sharedLinks && sharedLinks.length === 0 && (
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>{tl.noSharedLinks}</p>
                )}
                {!sharedLinksLoading && sharedLinks && sharedLinks.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    {sharedLinks.map((link) => {
                      const statusLabel = !link.is_active
                        ? (link.revoked_at ? tl.linkRevoked : tl.linkExpired)
                        : tl.linkActive;
                      const statusColor = link.is_active
                        ? 'var(--neon-cyan, #00f5ff)'
                        : 'var(--text-secondary)';
                      return (
                        <div
                          key={link.share_id}
                          style={{
                            background: 'rgba(255,255,255,0.03)',
                            border: '1px solid var(--color-border, #1e2130)',
                            borderRadius: '8px',
                            padding: '0.7rem 0.85rem',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem', marginBottom: '0.4rem' }}>
                            <span style={{ fontSize: '0.68rem', color: statusColor, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                              {statusLabel}
                            </span>
                            <span style={{ fontSize: '0.68rem', color: 'var(--text-secondary)', opacity: 0.6 }}>
                              {link.view_count} {tl.viewsLabel}
                            </span>
                          </div>
                          <div style={{
                            fontSize: '0.7rem',
                            color: link.is_active ? 'var(--neon-cyan, #00f5ff)' : 'var(--text-secondary)',
                            wordBreak: 'break-all',
                            marginBottom: '0.4rem',
                            opacity: link.is_active ? 1 : 0.45,
                          }}>
                            {link.url}
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem' }}>
                            <span style={{ fontSize: '0.65rem', color: 'var(--text-secondary)', opacity: 0.55 }}>
                              {new Date(link.created_at).toLocaleDateString(DATE_LOCALE[uiLang], { day: 'numeric', month: 'short', year: 'numeric' })}
                              {' → '}
                              {new Date(link.expires_at).toLocaleDateString(DATE_LOCALE[uiLang], { day: 'numeric', month: 'short', year: 'numeric' })}
                            </span>
                            {link.is_active && (
                              <button
                                disabled={revokingId === link.share_id}
                                onClick={() => void handleRevokeLink(link.share_id)}
                                style={{
                                  background: 'none',
                                  border: '1px solid var(--color-error, #ff4d6d)',
                                  borderRadius: '4px',
                                  color: 'var(--color-error, #ff4d6d)',
                                  fontFamily: 'var(--font-mono)',
                                  fontSize: '0.65rem',
                                  padding: '0.2rem 0.5rem',
                                  cursor: 'pointer',
                                  opacity: revokingId === link.share_id ? 0.5 : 1,
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                {revokingId === link.share_id ? tl.revoking : tl.revokeLink}
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              <button
                onClick={() => setSharedLinksOpen(false)}
                style={{
                  marginTop: '1rem',
                  width: '100%',
                  padding: '0.45rem',
                  background: 'none',
                  border: '1px solid var(--color-border, #1e2130)',
                  borderRadius: '6px',
                  color: 'var(--text-secondary)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.72rem',
                  cursor: 'pointer',
                  flexShrink: 0,
                }}
              >
                {tl.close}
              </button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
