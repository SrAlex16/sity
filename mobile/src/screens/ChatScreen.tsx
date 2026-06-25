import { useRef, useState, useEffect, useCallback } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useChat } from '../hooks/useChat';
import { MessageBubble } from '../components/MessageBubble';
import { TypingIndicator } from '../components/TypingIndicator';
import { StatusBadge } from '../components/StatusBadge';
import { BackgroundPicker } from '../components/BackgroundPicker';
import styles from './ChatScreen.module.css';

// ── Inline SVG icons ──────────────────────────────────────────────────────────

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

// ── ChatScreen ────────────────────────────────────────────────────────────────

export function ChatScreen() {
  const { messages, status, sendMessage, clearMessages } = useChat();

  const [inputText, setInputText] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const [bgPickerOpen, setBgPickerOpen] = useState(false);
  const [bgValue, setBgValue] = useState<string>(() => localStorage.getItem('sity_bg') ?? '');
  const [avatarSrc] = useState<string>(() => localStorage.getItem('sity_avatar') ?? '');
  const [isRecording, setIsRecording] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  // Scroll to bottom on new message or typing indicator
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, status]);

  // Auto-resize textarea
  const resizeTextarea = useCallback((el: HTMLTextAreaElement) => {
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 144)}px`; // 6 × 24px
  }, []);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputText(e.target.value);
    resizeTextarea(e.target);
  };

  const handleSend = useCallback(() => {
    const text = inputText.trim();
    if (!text || status === 'procesando') return;
    setInputText('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
    void sendMessage(text);
  }, [inputText, status, sendMessage]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Microphone: record → transcribe → fill textarea
  const handleMicToggle = async () => {
    if (isRecording) {
      mediaRecorderRef.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunksRef.current = [];
      const recorder = new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setIsRecording(false);
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        const fd = new FormData();
        fd.append('file', blob, 'recording.webm');
        try {
          const res = await fetch('/audio/transcribe', { method: 'POST', body: fd });
          const data = await res.json() as { transcript: string };
          if (data.transcript) {
            setInputText((prev) => prev + data.transcript);
            setTimeout(() => {
              if (textareaRef.current) resizeTextarea(textareaRef.current);
            }, 0);
          }
        } catch { /* ignore transcription error */ }
      };

      recorder.start();
      setIsRecording(true);
    } catch { /* mic permission denied or unavailable */ }
  };

  // Background
  const handleBgSelect = (bg: string) => {
    setBgValue(bg);
    localStorage.setItem('sity_bg', bg);
    setBgPickerOpen(false);
  };

  // Context menu close on outside click
  useEffect(() => {
    if (!menuOpen) return;
    const close = () => setMenuOpen(false);
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, [menuOpen]);

  const backgroundStyle: React.CSSProperties = bgValue
    ? bgValue.startsWith('data:')
      ? { backgroundImage: `url(${bgValue})`, backgroundSize: 'cover', backgroundPosition: 'center' }
      : { background: bgValue }
    : {};

  return (
    <>
      <div className={styles.screen}>
        {/* Background layer */}
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
                  <button
                    className={styles.menuItem}
                    onClick={() => { clearMessages(); setMenuOpen(false); }}
                  >
                    Borrar chat
                  </button>
                  <button
                    className={styles.menuItem}
                    onClick={() => { setMenuOpen(false); setBgPickerOpen(true); }}
                  >
                    Cambiar fondo
                  </button>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </header>

        {/* Messages */}
        <div className={styles.messages}>
          <AnimatePresence initial={false}>
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
          </AnimatePresence>
          {status === 'procesando' && <TypingIndicator />}
          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className={styles.inputArea}>
          <button className={styles.iconBtn} aria-label="Adjuntar">
            <IconClip />
          </button>

          <textarea
            ref={textareaRef}
            className={styles.textarea}
            value={inputText}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder="メッセージを入力..."
            rows={1}
          />

          <motion.button
            className={`${styles.iconBtn} ${isRecording ? styles.recording : ''}`}
            onClick={handleMicToggle}
            animate={isRecording ? { opacity: [1, 0.4, 1] } : { opacity: 1 }}
            transition={isRecording ? { repeat: Infinity, duration: 0.7 } : undefined}
            aria-label={isRecording ? 'Detener grabación' : 'Grabar voz'}
          >
            <IconMic />
          </motion.button>

          <motion.button
            className={styles.sendBtn}
            onClick={handleSend}
            disabled={!inputText.trim() || status === 'procesando'}
            whileTap={{ scale: 0.88 }}
            aria-label="Enviar"
          >
            <IconSend />
          </motion.button>
        </div>
      </div>

      <BackgroundPicker
        open={bgPickerOpen}
        onClose={() => setBgPickerOpen(false)}
        onSelect={handleBgSelect}
      />
    </>
  );
}
