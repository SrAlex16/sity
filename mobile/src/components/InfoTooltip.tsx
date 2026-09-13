import { useState, useRef, useCallback } from 'react';
import styles from './InfoTooltip.module.css';

interface Props {
  content: string;
}

// Computed once at module load — fine for a PWA (no SSR).
// Same pattern as the Enter-key mobile fix.
const IS_TOUCH = typeof navigator !== 'undefined' && navigator.maxTouchPoints > 0;

export function InfoTooltip({ content }: Props) {
  const [visible, setVisible] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const computePos = useCallback(() => {
    if (triggerRef.current) {
      const r = triggerRef.current.getBoundingClientRect();
      setPos({ top: r.top, left: r.left + r.width / 2 });
    }
  }, []);

  // Desktop: hover
  const handleMouseEnter = useCallback(() => {
    if (IS_TOUCH) return;
    computePos();
    setVisible(true);
  }, [computePos]);

  const handleMouseLeave = useCallback(() => {
    if (IS_TOUCH) return;
    setVisible(false);
  }, []);

  // Mobile: long-press (400 ms threshold)
  const handleTouchStart = useCallback(() => {
    computePos();
    timerRef.current = setTimeout(() => setVisible(true), 400);
  }, [computePos]);

  const handleTouchEnd = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setVisible(false);
  }, []);

  return (
    <span className={styles.wrap}>
      <button
        ref={triggerRef}
        type="button"
        className={styles.trigger}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
        onTouchCancel={handleTouchEnd}
        aria-label="más información"
        tabIndex={-1}
      >
        ⓘ
      </button>
      {visible && pos && (
        <span
          className={styles.popover}
          role="tooltip"
          style={{ top: pos.top, left: pos.left }}
        >
          {content}
        </span>
      )}
    </span>
  );
}
