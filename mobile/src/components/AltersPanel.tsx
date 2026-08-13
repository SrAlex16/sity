import { useState } from 'react';
import { useAlters } from '../hooks/useAlters';
import type { AlterSlot } from '../hooks/useAlters';
import type { T } from '../i18n/translations';
import styles from './AltersPanel.module.css';

type ActionType =
  | 'saving'        // empty slot: name input + save
  | 'renaming'      // filled: name input + save
  | 'confirm-load'  // filled: inline load confirmation
  | 'confirm-clear' // filled: inline clear confirmation
  | 'copying';      // filled: slot selector + confirm

interface AltersPanelProps {
  onLoaded: () => Promise<void>;
  tl: T['alters'];
}

export function AltersPanel({ onLoaded, tl }: AltersPanelProps) {
  const { slots, busy, save, load, rename, clear, copy } = useAlters();

  const [activeSlot, setActiveSlot] = useState<number | null>(null);
  const [actionType, setActionType] = useState<ActionType | null>(null);
  const [inputName, setInputName] = useState('');
  const [copyTarget, setCopyTarget] = useState<number | null>(null);

  function startAction(slot: number, type: ActionType, initialName = '') {
    setActiveSlot(slot);
    setActionType(type);
    setInputName(initialName);
    setCopyTarget(null);
  }

  function cancel() {
    setActiveSlot(null);
    setActionType(null);
    setInputName('');
    setCopyTarget(null);
  }

  async function handleSave(slot: number) {
    if (!inputName.trim()) return;
    await save(slot, inputName.trim());
    cancel();
  }

  async function handleLoad(slot: number) {
    await load(slot);
    await onLoaded();
    cancel();
  }

  async function handleRename(slot: number) {
    if (!inputName.trim()) return;
    await rename(slot, inputName.trim());
    cancel();
  }

  async function handleClear(slot: number) {
    await clear(slot);
    cancel();
  }

  async function handleCopy(fromSlot: number) {
    if (copyTarget == null) return;
    await copy(fromSlot, copyTarget);
    cancel();
  }

  function renderSlot(s: AlterSlot) {
    const isActive = activeSlot === s.slot;
    const isBusy = busy === s.slot;

    return (
      <div key={s.slot} className={styles.slot}>
        {/* Header row: number + name */}
        <div className={styles.slotHeader}>
          <span className={styles.slotNum}>{s.slot}</span>
          <span className={`${styles.slotName} ${s.is_empty ? styles.emptyName : ''}`}>
            {s.is_empty ? tl.empty : (s.name ?? `Alter ${s.slot}`)}
          </span>
        </div>

        {/* Default action buttons */}
        {!isActive && (
          <div className={styles.actions}>
            {s.is_empty ? (
              <button
                className={styles.btn}
                onClick={() => startAction(s.slot, 'saving')}
                disabled={isBusy}
              >
                {tl.saveHere}
              </button>
            ) : (
              <>
                <button
                  className={`${styles.btn} ${styles.btnPrimary}`}
                  onClick={() => startAction(s.slot, 'confirm-load')}
                  disabled={isBusy}
                >
                  {tl.load}
                </button>
                <button
                  className={styles.btn}
                  onClick={() => startAction(s.slot, 'renaming', s.name ?? '')}
                  disabled={isBusy}
                >
                  {tl.rename}
                </button>
                <button
                  className={styles.btn}
                  onClick={() => startAction(s.slot, 'copying')}
                  disabled={isBusy}
                >
                  {tl.copy}
                </button>
                <button
                  className={`${styles.btn} ${styles.btnDanger}`}
                  onClick={() => startAction(s.slot, 'confirm-clear')}
                  disabled={isBusy}
                >
                  {tl.clear}
                </button>
              </>
            )}
          </div>
        )}

        {/* Inline: save name input */}
        {isActive && actionType === 'saving' && (
          <div className={styles.inputRow}>
            <input
              className={styles.nameInput}
              placeholder={tl.namePlaceholder}
              value={inputName}
              onChange={(e) => setInputName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void handleSave(s.slot); }}
              autoFocus
              maxLength={40}
            />
            <button
              className={`${styles.btn} ${styles.btnPrimary}`}
              onClick={() => void handleSave(s.slot)}
              disabled={!inputName.trim() || isBusy}
            >
              {isBusy ? '…' : tl.save}
            </button>
            <button className={styles.btn} onClick={cancel}>✕</button>
          </div>
        )}

        {/* Inline: rename input */}
        {isActive && actionType === 'renaming' && (
          <div className={styles.inputRow}>
            <input
              className={styles.nameInput}
              value={inputName}
              onChange={(e) => setInputName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void handleRename(s.slot); }}
              autoFocus
              maxLength={40}
            />
            <button
              className={`${styles.btn} ${styles.btnPrimary}`}
              onClick={() => void handleRename(s.slot)}
              disabled={!inputName.trim() || isBusy}
            >
              {isBusy ? '…' : tl.save}
            </button>
            <button className={styles.btn} onClick={cancel}>✕</button>
          </div>
        )}

        {/* Inline: load confirmation */}
        {isActive && actionType === 'confirm-load' && (
          <div className={styles.confirmRow}>
            <span className={styles.confirmMsg}>
              {tl.confirmLoad}
            </span>
            <div className={styles.confirmBtns}>
              <button
                className={`${styles.btn} ${styles.btnPrimary}`}
                onClick={() => void handleLoad(s.slot)}
                disabled={isBusy}
              >
                {isBusy ? '…' : tl.confirm}
              </button>
              <button className={styles.btn} onClick={cancel}>{tl.cancel}</button>
            </div>
          </div>
        )}

        {/* Inline: clear confirmation */}
        {isActive && actionType === 'confirm-clear' && (
          <div className={styles.confirmRow}>
            <span className={styles.confirmMsg}>
              {tl.confirmClear}
            </span>
            <div className={styles.confirmBtns}>
              <button
                className={`${styles.btn} ${styles.btnDanger}`}
                onClick={() => void handleClear(s.slot)}
                disabled={isBusy}
              >
                {isBusy ? '…' : tl.confirm}
              </button>
              <button className={styles.btn} onClick={cancel}>{tl.cancel}</button>
            </div>
          </div>
        )}

        {/* Inline: copy selector */}
        {isActive && actionType === 'copying' && (
          <div className={styles.inputRow}>
            <select
              className={styles.copySelect}
              value={copyTarget ?? ''}
              onChange={(e) => setCopyTarget(Number(e.target.value) || null)}
            >
              <option value="">{tl.copyTarget}</option>
              {slots
                .filter((t) => t.slot !== s.slot)
                .map((t) => (
                  <option key={t.slot} value={t.slot}>
                    {tl.slotLabel} {t.slot}{t.name ? ` — ${t.name}` : ` ${tl.slotEmpty}`}
                  </option>
                ))}
            </select>
            <button
              className={`${styles.btn} ${styles.btnPrimary}`}
              onClick={() => void handleCopy(s.slot)}
              disabled={copyTarget == null || isBusy}
            >
              {isBusy ? '…' : tl.copy}
            </button>
            <button className={styles.btn} onClick={cancel}>✕</button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={styles.panel}>
      {slots.map(renderSlot)}
    </div>
  );
}
