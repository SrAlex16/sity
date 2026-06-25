import { AnimatePresence, motion } from 'framer-motion';

// Interpolate t∈[0,1] across 5 keyframes
function lerp5(t: number, v: [number, number, number, number, number]): number {
  const pos = Math.max(0, Math.min(4, t * 4));
  const i = Math.min(Math.floor(pos), 3);
  return v[i] + (v[i + 1] - v[i]) * (pos - i);
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

const SPRING = { type: 'spring', stiffness: 180, damping: 22 } as const;
const EASE   = { duration: 0.35, ease: 'easeOut' } as const;

export function MoodFace({ moodLevel, size = 64 }: MoodFaceProps) {
  const t = moodLevel / 100;

  const color = moodColor(moodLevel);

  // Eye squint: ry from open (5) to squinted (1.8)
  const eyeRy = lerp5(t, [5, 5, 4, 3, 1.8]);

  // Eyebrow rotation (degrees): happy tilted up → furrowed V
  const leftBrowRot  = lerp5(t, [10, 0, -14, -26, -38]);
  const rightBrowRot = lerp5(t, [-10, 0, 14, 26, 38]);
  // Eyebrows move down toward eyes when furrowed
  const browDown = lerp5(t, [-2, 0, 3, 5, 7]);

  // Mouth: control-point y (SVG y increases downward)
  // ctrlY < baseY → curves up (smile); ctrlY > baseY → flat; ctrlY >> baseY → not possible for frown
  // Actually smile = ctrl is BELOW the arc endpoints in SVG, i.e. HIGHER y value
  // frown = ctrl is ABOVE the arc endpoints, i.e. LOWER y value
  const mouthCtrlY = lerp5(t, [62, 56, 52, 46, 40]);
  // Mouth widens slightly at extremes
  const mouthX1 = lerp5(t, [25, 25, 25, 25, 22]);
  const mouthX2 = lerp5(t, [55, 55, 55, 55, 58]);
  const mouthD = `M ${mouthX1.toFixed(1)} 52 Q 40 ${mouthCtrlY.toFixed(1)} ${mouthX2.toFixed(1)} 52`;

  const showVein = moodLevel > 78;

  return (
    <svg
      viewBox="0 0 80 80"
      width={size}
      height={size}
      style={{ overflow: 'visible', flexShrink: 0 }}
      aria-hidden
    >
      {/* Head */}
      <motion.circle
        cx="40" cy="40" r="36"
        fill="#0f0f1a"
        stroke={color}
        strokeWidth="2"
        animate={{ stroke: color }}
        transition={EASE}
      />

      {/* Blush tint at high anger */}
      <motion.circle
        cx="40" cy="40" r="36"
        fill="#ff2200"
        animate={{ fillOpacity: lerp5(t, [0, 0, 0, 0.06, 0.18]) }}
        transition={EASE}
        style={{ pointerEvents: 'none' }}
      />

      {/* === Eyes === */}
      {/* Whites */}
      <motion.ellipse cx="27" cy="33" rx="5" animate={{ ry: eyeRy }} transition={SPRING} fill="white" />
      <motion.ellipse cx="53" cy="33" rx="5" animate={{ ry: eyeRy }} transition={SPRING} fill="white" />
      {/* Pupils */}
      <circle cx="28" cy="34" r="2.2" fill="#111" />
      <circle cx="54" cy="34" r="2.2" fill="#111" />
      {/* Shine dots */}
      <circle cx="30" cy="32" r="0.9" fill="white" />
      <circle cx="56" cy="32" r="0.9" fill="white" />

      {/* === Eyebrows === */}
      <motion.g
        style={{ transformOrigin: '27px 24px' }}
        animate={{ rotate: leftBrowRot, y: browDown }}
        transition={SPRING}
      >
        <line x1="20" y1="24" x2="34" y2="24"
          stroke={color} strokeWidth="2.5" strokeLinecap="round" />
      </motion.g>
      <motion.g
        style={{ transformOrigin: '53px 24px' }}
        animate={{ rotate: rightBrowRot, y: browDown }}
        transition={SPRING}
      >
        <line x1="46" y1="24" x2="60" y2="24"
          stroke={color} strokeWidth="2.5" strokeLinecap="round" />
      </motion.g>

      {/* === Mouth === */}
      <motion.path
        d={mouthD}
        animate={{ d: mouthD }}
        transition={EASE}
        fill="none"
        stroke={color}
        strokeWidth="2.5"
        strokeLinecap="round"
      />

      {/* === Veins (>78%) === */}
      <AnimatePresence>
        {showVein && (
          <motion.g
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
          >
            <polyline points="16,20 19,15 23,21" fill="none" stroke="#ff3333" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            <polyline points="54,17 58,12 62,18" fill="none" stroke="#ff3333" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </motion.g>
        )}
      </AnimatePresence>
    </svg>
  );
}
