import { useRef, useState, useEffect, useCallback } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { UseChatResult } from '../hooks/useChat';
import { useVoice } from '../hooks/useVoice';
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

// ── Recording state ───────────────────────────────────────────────────────────

interface RecordingCtx {
  mediaRecorder: MediaRecorder;
  analyserNode: AnalyserNode;
  audioContext: AudioContext;
  chunks: Blob[];
  startTime: number;
}

// ── ChatScreen ────────────────────────────────────────────────────────────────

export function ChatScreen({ messages, status, sendMessage, sendAudio, clearMessages, canCancel, cancel, backgroundJobsActive, backgroundJustFinished }: UseChatResult) {
  const { settings: voiceSettings } = useVoice();
  const voiceIncludeText = voiceSettings?.voice_include_text ?? true;

  const [inputText, setInputText] = useState(() => localStorage.getItem('sity_draft_message') ?? '');
  const [activeAudioId, setActiveAudioId] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [bgPickerOpen, setBgPickerOpen] = useState(false);
  const [fontPickerOpen, setFontPickerOpen] = useState(false);
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
    if ((!text && !pendingImage) || status === 'procesando') return;
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
  }, [inputText, pendingImage, status, sendMessage]);

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
            <StatusBadge status={status} />
            <BgJobIndicator active={backgroundJobsActive > 0} justFinished={backgroundJustFinished} />
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
                  <button className={styles.menuItem} onClick={() => { clearMessages(); setMenuOpen(false); }}>
                    Borrar chat
                  </button>
                  <button className={styles.menuItem} onClick={() => { setMenuOpen(false); setBgPickerOpen(true); }}>
                    Cambiar fondo
                  </button>
                  <button className={styles.menuItem} onClick={() => { setMenuOpen(false); setFontPickerOpen(true); }}>
                    Cambiar fuente
                  </button>
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

                {canCancel ? (
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
                    disabled={(!inputText.trim() && !pendingImage) || status === 'procesando'}
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
      />
    </>
  );
}
