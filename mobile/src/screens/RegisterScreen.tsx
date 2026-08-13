import React, { useState, useEffect } from 'react';
import { HelpModal } from '../components/HelpModal';
import type { UseAuthResult } from '../hooks/useAuth';
import { getRecaptchaToken, loadRecaptchaScript } from '../utils/recaptcha';
import { TRANSLATIONS } from '../i18n/translations';
import type { UiLang, T } from '../i18n/translations';
import styles from './AuthForm.module.css';

interface Props {
  auth: UseAuthResult;
  onSwitchToLogin: () => void;
  uiLang?: UiLang;
}

function checkPasswordStrength(password: string, tla: T['auth']): string | null {
  if (password.length < 8) return tla.pwMinChars;
  if (!/[A-Z]/.test(password)) return tla.pwUppercase;
  if (!/[a-z]/.test(password)) return tla.pwLowercase;
  if (!/\d/.test(password)) return tla.pwNumber;
  return null;
}

export function RegisterScreen({ auth, onSwitchToLogin, uiLang = 'es' }: Props) {
  const tla = TRANSLATIONS[uiLang].auth;
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [rgpdChecked, setRgpdChecked] = useState(false);
  const [rgpdOpen, setRgpdOpen] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => { void loadRecaptchaScript(); }, []);

  const pwError = password ? checkPasswordStrength(password, tla) : null;
  const pwMismatch = confirmPassword && password !== confirmPassword;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');

    if (!email) { setError(tla.emailRequired); return; }
    if (!email.includes('@')) { setError(tla.emailInvalid); return; }
    const strengthError = checkPasswordStrength(password, tla);
    if (strengthError) { setError(strengthError); return; }
    if (password !== confirmPassword) { setError(tla.pwMismatch); return; }
    if (!rgpdChecked) { setError(tla.privacyRequired); return; }

    setLoading(true);
    const token = await getRecaptchaToken('register');
    const result = await auth.register(email, password, token);
    setLoading(false);
    if (!result.ok) setError(result.error ?? tla.registerError);
  }

  return (
    <div className={styles.screen}>
      <p className={styles.logo}>SITY</p>
      <p className={styles.tagline}>// SISTEMA DE IA PERSONAL</p>

      <div className={styles.card}>
        <p className={styles.cardTitle}>{tla.createAccount}</p>

        {error && <div className={styles.errorBanner}>{error}</div>}

        <form onSubmit={handleSubmit} style={{ display: 'contents' }}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="reg-email">{tla.email}</label>
            <input
              id="reg-email"
              className={styles.input}
              type="email"
              autoComplete="email"
              placeholder="usuario@ejemplo.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={loading}
            />
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor="reg-password">{tla.password}</label>
            <input
              id="reg-password"
              className={styles.input}
              type="password"
              autoComplete="new-password"
              placeholder={tla.newPasswordPlaceholder}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loading}
            />
            {pwError && <span className={styles.fieldError}>{pwError}</span>}
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor="reg-confirm">{tla.confirmPassword}</label>
            <input
              id="reg-confirm"
              className={styles.input}
              type="password"
              autoComplete="new-password"
              placeholder={tla.confirmPasswordPlaceholder}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              disabled={loading}
            />
            {pwMismatch && <span className={styles.fieldError}>{tla.pwMismatch}</span>}
          </div>

          <div className={styles.checkRow}>
            <input
              id="reg-rgpd"
              type="checkbox"
              className={styles.checkbox}
              checked={rgpdChecked}
              onChange={(e) => setRgpdChecked(e.target.checked)}
              disabled={loading}
            />
            <label htmlFor="reg-rgpd" className={styles.checkLabel}>
              {tla.privacyAccept}{' '}
              <button
                type="button"
                className={styles.checkLink}
                onClick={() => setRgpdOpen(true)}
              >
                {tla.privacyLink}
              </button>
            </label>
          </div>

          <button type="submit" className={styles.btnPrimary} disabled={loading}>
            {loading ? tla.registering : tla.createAccount}
          </button>
        </form>

        <div className={styles.divider}>{tla.orDivider}</div>

        {/* TODO: Google OAuth — backend not implemented yet */}
        <button type="button" className={styles.btnGoogle} disabled aria-disabled="true">
          {tla.googleRegister}
        </button>

        <p className={styles.switchRow}>
          {tla.haveAccount}{' '}
          <button type="button" className={styles.switchLink} onClick={onSwitchToLogin}>
            {tla.signIn}
          </button>
        </p>
      </div>

      {/* RGPD privacy modal */}
      <HelpModal
        open={rgpdOpen}
        onClose={() => setRgpdOpen(false)}
        title={tla.privacyTitle}
      >
        <p className={styles.modalText}>
          Sity es una IA personal de uso doméstico. Los datos que introduces
          (mensajes de chat, preferencias de personalidad) se almacenan
          localmente en el dispositivo del administrador del sistema y no se
          comparten con terceros.
        </p>
        <p className={styles.modalText}>
          Las conversaciones pueden usarse para mejorar el modelo local
          (fine-tuning), siempre bajo control del administrador. Tienes
          derecho a solicitar la eliminación de tus datos en cualquier
          momento contactando al administrador del sistema.
        </p>
        <p className={styles.modalText}>
          {/* TODO: Completar con texto RGPD real cuando se despliegue en producción */}
          Este texto es un placeholder. Versión completa pendiente.
        </p>
      </HelpModal>
    </div>
  );
}
