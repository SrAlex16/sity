import { useRef, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import styles from './RecordingUI.module.css';

function formatElapsed(secs: number): string {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function IconTrash() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="20" height="20">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6M14 11v6" />
      <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
    </svg>
  );
}

function IconCheck() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" width="18" height="18">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

// ── Waveform canvas ───────────────────────────────────────────────────────────

interface WaveformProps {
  analyserNode: AnalyserNode | null;
}

function Waveform({ analyserNode }: WaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !analyserNode) return;

    const dpr = window.devicePixelRatio || 1;
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
    };
    resize();

    const ctx = canvas.getContext('2d')!;
    const data = new Uint8Array(analyserNode.frequencyBinCount);
    const BAR_COUNT = 32;

    const draw = () => {
      analyserNode.getByteFrequencyData(data);
      const W = canvas.width;
      const H = canvas.height;
      ctx.clearRect(0, 0, W, H);

      const barW = (W / BAR_COUNT) * 0.6;
      const gap = (W / BAR_COUNT) * 0.4;
      const step = Math.floor(data.length / BAR_COUNT);

      for (let i = 0; i < BAR_COUNT; i++) {
        const value = data[i * step] / 255;
        const barH = Math.max(3 * dpr, value * H);
        const x = i * (barW + gap) + gap / 2;
        const y = (H - barH) / 2;

        ctx.fillStyle = '#00f5ff';
        ctx.shadowBlur = 6 * dpr;
        ctx.shadowColor = '#00f5ff';
        ctx.fillRect(x, y, barW, barH);
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [analyserNode]);

  return <canvas ref={canvasRef} className={styles.canvas} />;
}

// ── RecordingUI ───────────────────────────────────────────────────────────────

interface RecordingUIProps {
  analyserNode: AnalyserNode | null;
  onCancel: () => void;
  onSend: () => void;
}

export function RecordingUI({ analyserNode, onCancel, onSend }: RecordingUIProps) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className={styles.ui}>
      {/* Cancel */}
      <button className={styles.cancelBtn} onClick={onCancel} aria-label="Cancelar grabación">
        <IconTrash />
      </button>

      {/* Timer */}
      <div className={styles.timerWrap}>
        <motion.span
          className={styles.dot}
          animate={{ opacity: [1, 0.2, 1] }}
          transition={{ repeat: Infinity, duration: 0.8, ease: 'easeInOut' }}
        />
        <span className={styles.timer}>{formatElapsed(elapsed)}</span>
      </div>

      {/* Waveform */}
      <div className={styles.waveformWrap}>
        <Waveform analyserNode={analyserNode} />
      </div>

      {/* Send */}
      <motion.button
        className={styles.sendBtn}
        onClick={onSend}
        whileTap={{ scale: 0.88 }}
        aria-label="Enviar nota de voz"
      >
        <IconCheck />
      </motion.button>
    </div>
  );
}
