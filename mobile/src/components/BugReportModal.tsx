import { useState, useEffect, useRef } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import styles from './BugReportModal.module.css';

interface BugReportModalProps {
  open: boolean;
  onClose: () => void;
}

type Severity = 'baja' | 'media' | 'alta' | 'crítica';

interface DraftState {
  observations: string;
  severity: Severity;
}

const _LS_KEY = 'sity_bug_report_draft';

function loadDraft(): DraftState {
  try {
    const raw = localStorage.getItem(_LS_KEY);
    if (raw) return JSON.parse(raw) as DraftState;
  } catch { /* ignore */ }
  return { observations: '', severity: 'media' };
}

function saveDraft(state: DraftState) {
  try {
    localStorage.setItem(_LS_KEY, JSON.stringify(state));
  } catch { /* ignore */ }
}

function clearDraft() {
  try { localStorage.removeItem(_LS_KEY); } catch { /* ignore */ }
}

export function BugReportModal({ open, onClose }: BugReportModalProps) {
  const draft = loadDraft();
  const [observations, setObservations] = useState(draft.observations);
  const [severity, setSeverity] = useState<Severity>(draft.severity);
  const [attachments, setAttachments] = useState<File[]>([]);
  const [status, setStatus] = useState<'idle' | 'sending' | 'success' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Persist draft whenever content changes
  useEffect(() => {
    saveDraft({ observations, severity });
  }, [observations, severity]);

  // Reset transient state when modal opens
  useEffect(() => {
    if (open) {
      const d = loadDraft();
      setObservations(d.observations);
      setSeverity(d.severity);
      setAttachments([]);
      setStatus('idle');
      setErrorMsg('');
    }
  }, [open]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []).slice(0, 5);
    setAttachments(files);
  };

  const handleClose = () => {
    if (status !== 'sending') onClose();
  };

  const handleSubmit = async () => {
    if (!observations.trim()) return;
    setStatus('sending');
    setErrorMsg('');

    try {
      const attachmentPayloads = await Promise.all(
        attachments.map(async (f) => {
          const buf = await f.arrayBuffer();
          const bytes = new Uint8Array(buf);
          let binary = '';
          for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
          return { data: btoa(binary), media_type: f.type };
        })
      );

      const resp = await fetch('/bug-report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ observations, severity, attachments: attachmentPayloads }),
      });

      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}));
        throw new Error((detail as { detail?: string }).detail ?? `Error ${resp.status}`);
      }

      clearDraft();
      setObservations('');
      setSeverity('media');
      setAttachments([]);
      setStatus('success');
      setTimeout(() => { setStatus('idle'); onClose(); }, 1800);
    } catch (e) {
      setStatus('error');
      setErrorMsg(e instanceof Error ? e.message : 'Error al enviar el reporte.');
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className={styles.backdrop}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={handleClose}
        >
          <motion.div
            className={styles.modal}
            initial={{ opacity: 0, scale: 0.92, y: 24 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.92, y: 24 }}
            transition={{ duration: 0.2 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={styles.header}>
              <h2 className={styles.title}>Reportar un problema</h2>
              <button className={styles.closeX} onClick={handleClose} aria-label="Cerrar">✕</button>
            </div>

            <label className={styles.fieldLabel}>
              Observaciones
              <textarea
                className={styles.textarea}
                value={observations}
                onChange={(e) => setObservations(e.target.value)}
                placeholder="Describe el problema…"
                rows={5}
                disabled={status === 'sending' || status === 'success'}
              />
            </label>

            <label className={styles.fieldLabel}>
              Severidad
              <select
                className={styles.select}
                value={severity}
                onChange={(e) => setSeverity(e.target.value as Severity)}
                disabled={status === 'sending' || status === 'success'}
              >
                <option value="baja">Baja</option>
                <option value="media">Media</option>
                <option value="alta">Alta</option>
                <option value="crítica">Crítica</option>
              </select>
            </label>

            <div className={styles.attachRow}>
              <button
                className={styles.attachBtn}
                onClick={() => fileInputRef.current?.click()}
                disabled={status === 'sending' || status === 'success'}
                type="button"
              >
                {attachments.length > 0
                  ? `${attachments.length} archivo${attachments.length > 1 ? 's' : ''} adjunto${attachments.length > 1 ? 's' : ''}`
                  : 'Adjuntar imagen'}
              </button>
              {attachments.length > 0 && (
                <button
                  className={styles.clearAttach}
                  onClick={() => { setAttachments([]); if (fileInputRef.current) fileInputRef.current.value = ''; }}
                  disabled={status === 'sending'}
                  type="button"
                >
                  ✕
                </button>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp,image/gif"
                multiple
                style={{ display: 'none' }}
                onChange={handleFileChange}
              />
            </div>

            {status === 'error' && <p className={styles.errorMsg}>{errorMsg}</p>}
            {status === 'success' && <p className={styles.successMsg}>Reporte enviado. ¡Gracias!</p>}

            <div className={styles.actions}>
              <button
                className={styles.btnSecondary}
                onClick={handleClose}
                disabled={status === 'sending'}
              >
                Cancelar
              </button>
              <button
                className={styles.btnPrimary}
                onClick={() => void handleSubmit()}
                disabled={!observations.trim() || status === 'sending' || status === 'success'}
              >
                {status === 'sending' ? 'Enviando…' : 'Enviar'}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
