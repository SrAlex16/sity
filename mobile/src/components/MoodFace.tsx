import { AnimatePresence, motion } from 'framer-motion';

function emojiFor(pct: number): string {
  if (pct <= 20) return '😊';
  if (pct <= 40) return '😑';
  if (pct <= 60) return '😠';
  if (pct <= 80) return '😡';
  return '🤬';
}

function moodColor(pct: number): string {
  if (pct <= 25) return '#00f5ff';
  if (pct <= 50) return '#00ff80';
  if (pct <= 75) return '#ff8000';
  return '#ff00ff';
}

interface MoodFaceProps {
  moodLevel: number; // 0–100
  size?: number;
}

export function MoodFace({ moodLevel, size = 64 }: MoodFaceProps) {
  const emoji = emojiFor(moodLevel);
  const color = moodColor(moodLevel);

  return (
    <div style={{ width: size, height: size, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
      <AnimatePresence mode="wait">
        <motion.span
          key={emoji}
          initial={{ scale: 0.7, opacity: 0 }}
          animate={{ scale: [0.7, 1.15, 1.0], opacity: [0, 1, 1] }}
          exit={{ scale: 0.7, opacity: 0 }}
          transition={{ duration: 0.32, times: [0, 0.55, 1], ease: 'easeOut' }}
          style={{
            display: 'inline-block',
            fontSize: size,
            lineHeight: 1,
            filter: `drop-shadow(0 0 6px ${color}) drop-shadow(0 0 14px ${color})`,
            userSelect: 'none',
          }}
        >
          {emoji}
        </motion.span>
      </AnimatePresence>
    </div>
  );
}
