import { useRef } from 'react';
import { motion } from 'framer-motion';
import styles from './NeonSlider.module.css';

interface NeonSliderProps {
  value: number; // 0–1
  onChange: (v: number) => void;
  onChangeCommit: (v: number) => void;
}

export function NeonSlider({ value, onChange, onChangeCommit }: NeonSliderProps) {
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
        onChangeCommit(v);
        e.currentTarget.releasePointerCapture(e.pointerId);
      }}
    >
      <div className={styles.fill} style={{ width: pct }} />
      <motion.div
        className={styles.thumb}
        style={{ left: pct }}
        whileTap={{ scale: 1.4 }}
        transition={{ type: 'spring', stiffness: 500, damping: 20 }}
      />
    </div>
  );
}
