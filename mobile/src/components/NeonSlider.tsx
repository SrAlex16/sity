import { useRef } from 'react';
import { motion } from 'framer-motion';
import styles from './NeonSlider.module.css';

interface NeonSliderProps {
  value: number;
  onChange: (value: number) => void;
  onCommit: (value: number) => void;
  color?: string;
}

export function NeonSlider({
  value,
  onChange,
  onCommit,
  color = 'var(--neon-cyan)',
}: NeonSliderProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const pct = `${(value * 100).toFixed(1)}%`;

  const compute = (clientX: number): number => {
    const track = trackRef.current;
    if (!track) return value;
    const rect = track.getBoundingClientRect();
    return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
  };

  return (
    <div
      ref={trackRef}
      className={styles.track}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        onChange(compute(e.clientX));
      }}
      onPointerMove={(e) => {
        if (!e.currentTarget.hasPointerCapture(e.pointerId)) return;
        onChange(compute(e.clientX));
      }}
      onPointerUp={(e) => {
        const v = compute(e.clientX);
        onChange(v);
        onCommit(v);
        e.currentTarget.releasePointerCapture(e.pointerId);
      }}
    >
      <div
        className={styles.fill}
        style={{ width: pct, background: color, boxShadow: `0 0 6px ${color}` }}
      />
      {/* 28px transparent hit wrapper, 16px visual dot inside */}
      <motion.div
        className={styles.thumbWrap}
        style={{ left: pct }}
        whileTap={{ scale: 1.2 }}
        transition={{ type: 'spring', stiffness: 500, damping: 20 }}
      >
        <div
          className={styles.thumbDot}
          style={{ background: color, boxShadow: `0 0 8px ${color}, 0 0 2px #fff` }}
        />
      </motion.div>
    </div>
  );
}
