import { useRef, useState, useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { AudioChatMessage } from '../hooks/useChat';
import styles from './AudioMessageBubble.module.css';

function formatDur(secs: number): string {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function formatTimestamp(date: Date): string {
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  const time = date.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
  if (date.toDateString() === now.toDateString()) return time;
  if (date.toDateString() === yesterday.toDateString()) return `Ayer ${time}`;
  const day = date.toLocaleDateString('es-ES', { day: '2-digit', month: 'short' }).replace('.', '');
  return `${day} ${time}`;
}

function IconPlay() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
      <polygon points="5 3 19 12 5 21 5 3" />
    </svg>
  );
}

function IconPause() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
      <rect x="6" y="4" width="4" height="16" /><rect x="14" y="4" width="4" height="16" />
    </svg>
  );
}

function IconWave() {
  return (
    <svg viewBox="0 0 24 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" width="28" height="14">
      <polyline points="0,5 3,2 6,8 9,1 12,9 15,3 18,7 21,4 24,5" />
    </svg>
  );
}

interface AudioPlayerProps {
  src: string;
  knownDuration?: number;
  isUser: boolean;
}

function AudioPlayer({ src, knownDuration, isUser }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(knownDuration ?? 0);

  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    const onLoaded = () => { if (a.duration && isFinite(a.duration)) setDuration(a.duration); };
    const onTimeUpdate = () => {
      setCurrentTime(a.currentTime);
      setProgress(a.duration ? (a.currentTime / a.duration) * 100 : 0);
    };
    const onEnded = () => { setIsPlaying(false); setProgress(0); setCurrentTime(0); };
    a.addEventListener('loadedmetadata', onLoaded);
    a.addEventListener('timeupdate', onTimeUpdate);
    a.addEventListener('ended', onEnded);
    return () => {
      a.removeEventListener('loadedmetadata', onLoaded);
      a.removeEventListener('timeupdate', onTimeUpdate);
      a.removeEventListener('ended', onEnded);
    };
  }, []);

  const togglePlay = () => {
    const a = audioRef.current;
    if (!a) return;
    if (isPlaying) { a.pause(); setIsPlaying(false); }
    else { void a.play(); setIsPlaying(true); }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const a = audioRef.current;
    if (!a || !a.duration) return;
    const pct = Number(e.target.value);
    a.currentTime = (pct / 100) * a.duration;
    setProgress(pct);
  };

  const accentColor = isUser ? 'var(--neon-cyan)' : 'var(--neon-magenta)';

  return (
    <div className={styles.player}>
      <audio ref={audioRef} src={src} preload="metadata" />

      <button className={styles.playBtn} onClick={togglePlay} style={{ color: accentColor }}>
        {isPlaying ? <IconPause /> : <IconPlay />}
      </button>

      <div className={styles.playerTrack}>
        <input
          type="range"
          min={0}
          max={100}
          value={progress}
          onChange={handleSeek}
          className={styles.seekBar}
          style={{ '--accent': accentColor } as React.CSSProperties}
        />
        <div className={styles.playerTimes}>
          <span>{formatDur(currentTime)}</span>
          <span>{duration ? formatDur(duration) : '--:--'}</span>
        </div>
      </div>
    </div>
  );
}

interface AudioMessageBubbleProps {
  message: AudioChatMessage;
}

export function AudioMessageBubble({ message }: AudioMessageBubbleProps) {
  const isUser = message.role === 'user';
  const [showTranscript, setShowTranscript] = useState(false);
  const src = message.audioBlobUrl ?? message.audioUrl ?? '';

  return (
    <motion.div
      className={`${styles.wrapper} ${isUser ? styles.wrapperUser : styles.wrapperSity}`}
      initial={{ opacity: 0, x: isUser ? 20 : -20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      layout
    >
      <div className={`${styles.bubble} ${isUser ? styles.bubbleUser : styles.bubbleSity}`}>
        <div className={styles.header}>
          <span className={styles.waveIcon} style={{ color: isUser ? 'var(--neon-cyan)' : 'var(--neon-magenta)' }}>
            <IconWave />
          </span>
          {message.durationSecs !== undefined && (
            <span className={styles.dur}>{formatDur(message.durationSecs)}</span>
          )}
        </div>

        {src && <AudioPlayer src={src} knownDuration={message.durationSecs} isUser={isUser} />}

        {message.transcript && (
          <>
            <button
              className={styles.transcriptToggle}
              onClick={() => setShowTranscript((v) => !v)}
            >
              {showTranscript ? 'Ocultar transcripción' : 'Ver transcripción'}
            </button>

            <AnimatePresence>
              {showTranscript && (
                <motion.p
                  className={styles.transcriptText}
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.2 }}
                  style={{ overflow: 'hidden' }}
                >
                  {message.transcript}
                </motion.p>
              )}
            </AnimatePresence>
          </>
        )}
      </div>

      <span className={styles.timestamp}>{formatTimestamp(message.timestamp)}</span>
    </motion.div>
  );
}
