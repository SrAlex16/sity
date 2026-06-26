import { useRef } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import styles from './BackgroundPicker.module.css';

export const PRESET_BACKGROUNDS = [
  '/backgrounds/wallpaper1.png',
  '/backgrounds/wallpaper2.png',
  '/backgrounds/wallpaper3.png',
  '/backgrounds/wallpaper4.png',
];

interface BackgroundPickerProps {
  open: boolean;
  onClose: () => void;
  onSelect: (bg: string) => void;
}

export function BackgroundPicker({ open, onClose, onSelect }: BackgroundPickerProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      onSelect(reader.result as string);
    };
    reader.readAsDataURL(file);
    e.target.value = '';
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className={styles.backdrop}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className={styles.sheet}
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 40 }}
            transition={{ duration: 0.22, ease: 'easeOut' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={styles.handle} />
            <h3 className={styles.title}>Cambiar fondo</h3>

            <section className={styles.section}>
              <p className={styles.sectionLabel}>Desde galería</p>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className={styles.fileInput}
                onChange={handleFileChange}
              />
              <button className={styles.galleryBtn} onClick={() => fileInputRef.current?.click()}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width={18} height={18}>
                  <rect x="3" y="3" width="18" height="18" rx="2" />
                  <circle cx="8.5" cy="8.5" r="1.5" />
                  <polyline points="21 15 16 10 5 21" />
                </svg>
                Seleccionar imagen
              </button>
            </section>

            <section className={styles.section}>
              <p className={styles.sectionLabel}>Fondos predefinidos</p>
              <div className={styles.presetGrid}>
                {PRESET_BACKGROUNDS.map((bg, i) => (
                  <button
                    key={i}
                    className={styles.presetThumb}
                    style={{ backgroundImage: `url(${bg})`, backgroundSize: 'cover', backgroundPosition: 'center' }}
                    onClick={() => onSelect(bg)}
                    aria-label={`Fondo ${i + 1}`}
                  />
                ))}
              </div>
            </section>

            <button className={styles.cancelBtn} onClick={onClose}>Cancelar</button>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
