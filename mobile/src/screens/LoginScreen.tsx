import React, { useState, useEffect } from 'react';
import { HelpModal } from '../components/HelpModal';
import type { UseAuthResult } from '../hooks/useAuth';
import { getRecaptchaToken, loadRecaptchaScript } from '../utils/recaptcha';
import { TRANSLATIONS } from '../i18n/translations';
import type { UiLang, T } from '../i18n/translations';
import styles from './AuthForm.module.css';

interface Props {
  auth: UseAuthResult;
  onSwitchToRegister: () => void;
  initialResetToken?: string | null;
  onResetTokenConsumed?: () => void;
  uiLang?: UiLang;
}

function checkPasswordStrength(password: string, tla: T['auth']): string | null {
  if (password.length < 8) return tla.pwMinChars;
  if (!/[A-Z]/.test(password)) return tla.pwUppercase;
  if (!/[a-z]/.test(password)) return tla.pwLowercase;
  if (!/\d/.test(password)) return tla.pwNumber;
  return null;
}

export function LoginScreen({ auth, onSwitchToRegister, initialResetToken, onResetTokenConsumed, uiLang = 'es' }: Props) {
  const tla = TRANSLATIONS[uiLang].auth;
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const [forgotOpen, setForgotOpen] = useState(false);
  const [forgotEmail, setForgotEmail] = useState('');
  const [forgotStatus, setForgotStatus] = useState<'idle' | 'sent' | 'error'>('idle');

  // Reset password modal
  const [resetOpen, setResetOpen] = useState(false);
  const [resetToken, setResetToken] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [resetError, setResetError] = useState('');
  const [resetLoading, setResetLoading] = useState(false);
  const [resetSuccess, setResetSuccess] = useState(false);

  // Pre-load reCAPTCHA script while the user reads the form, so the first
  // submit doesn't stall waiting for the script to load.
  useEffect(() => { void loadRecaptchaScript(); }, []);

  // Open reset modal automatically if a token was extracted from the URL in App.tsx
  useEffect(() => {
    if (initialResetToken) {
      setResetToken(initialResetToken);
      setResetOpen(true);
      onResetTokenConsumed?.();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');

    if (!email || !password) {
      setError(tla.emailPasswordRequired);
      return;
    }

    setLoading(true);
    const token = await getRecaptchaToken('login');
    const result = await auth.login(email, password, token);
    setLoading(false);
    if (!result.ok) setError(result.error ?? tla.loginError);
  }

  async function handleForgot(e: React.FormEvent) {
    e.preventDefault();
    if (!forgotEmail) return;
    const result = await auth.forgotPassword(forgotEmail);
    setForgotStatus(result.ok ? 'sent' : 'error');
  }

  async function handleReset(e: React.FormEvent) {
    e.preventDefault();
    setResetError('');

    const strengthError = checkPasswordStrength(newPassword, tla);
    if (strengthError) { setResetError(strengthError); return; }
    if (newPassword !== confirmPassword) { setResetError(tla.pwMismatch); return; }

    setResetLoading(true);
    const result = await auth.resetPassword(resetToken, newPassword);
    setResetLoading(false);

    if (result.ok) {
      setResetSuccess(true);
    } else {
      setResetError(tla.resetInvalid);
    }
  }

  function closeReset() {
    setResetOpen(false);
    setResetSuccess(false);
    setNewPassword('');
    setConfirmPassword('');
    setResetError('');
  }

  const newPwError = newPassword ? checkPasswordStrength(newPassword, tla) : null;
  const pwMismatch = confirmPassword && newPassword !== confirmPassword;

  return (
    <div className={styles.screen}>
      <p className={styles.logo}>SITY</p>
      <p className={styles.tagline}>// SISTEMA DE IA PERSONAL</p>

      <div className={styles.card}>
        <p className={styles.cardTitle}>{tla.signInTitle}</p>

        {error && <div className={styles.errorBanner}>{error}</div>}

        <form onSubmit={handleSubmit} style={{ display: 'contents' }}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="login-email">{tla.email}</label>
            <input
              id="login-email"
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
            <label className={styles.label} htmlFor="login-password">{tla.password}</label>
            <input
              id="login-password"
              className={styles.input}
              type="password"
              autoComplete="current-password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loading}
            />
            <button
              type="button"
              className={styles.forgotLink}
              onClick={() => { setForgotOpen(true); setForgotStatus('idle'); setForgotEmail(''); }}
            >
              {tla.forgotPassword}
            </button>
          </div>

          <button type="submit" className={styles.btnPrimary} disabled={loading}>
            {loading ? tla.connecting : tla.signIn}
          </button>
        </form>

        <button
          type="button"
          className={styles.btnSecondary}
          onClick={auth.continueAsGuest}
          disabled={loading}
        >
          {tla.continueGuest}
        </button>

        <div className={styles.divider}>{tla.orDivider}</div>

        {/* TODO: Google OAuth — backend not implemented yet */}
        <button type="button" className={styles.btnGoogle} disabled aria-disabled="true">
          {tla.googleSignIn}
        </button>

        <p className={styles.switchRow}>
          {tla.noAccount}{' '}
          <button type="button" className={styles.switchLink} onClick={onSwitchToRegister}>
            {tla.createAccountLink}
          </button>
        </p>
      </div>

      {/* Forgot password modal */}
      <HelpModal
        open={forgotOpen}
        onClose={() => setForgotOpen(false)}
        title={tla.recoverTitle}
      >
        {forgotStatus === 'sent' ? (
          <p className={styles.modalText}>{tla.recoverSent}</p>
        ) : (
          <form onSubmit={handleForgot} style={{ display: 'contents' }}>
            <p className={styles.modalText}>{tla.recoverIntro}</p>
            <input
              className={styles.input}
              type="email"
              placeholder="tu@email.com"
              value={forgotEmail}
              onChange={(e) => setForgotEmail(e.target.value)}
              autoComplete="email"
            />
            {forgotStatus === 'error' && (
              <p style={{ color: '#ff4466', fontSize: '0.75rem', margin: 0 }}>
                {tla.sendError}
              </p>
            )}
            <button type="submit" className={styles.btnPrimary}>{tla.sendLink}</button>
          </form>
        )}
      </HelpModal>

      {/* Reset password modal — opens automatically when the app detects /reset-password?token= in the URL */}
      <HelpModal
        open={resetOpen}
        onClose={closeReset}
        title={tla.newPasswordTitle}
      >
        {resetSuccess ? (
          <>
            <p className={styles.modalText}>{tla.resetSuccess}</p>
            <button type="button" className={styles.btnPrimary} onClick={closeReset}>
              {tla.signIn}
            </button>
          </>
        ) : (
          <form onSubmit={handleReset} style={{ display: 'contents' }}>
            <p className={styles.modalText}>{tla.resetIntro}</p>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="reset-new-pw">{tla.newPasswordLabel}</label>
              <input
                id="reset-new-pw"
                className={styles.input}
                type="password"
                autoComplete="new-password"
                placeholder={tla.newPasswordPlaceholder}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                disabled={resetLoading}
              />
              {newPwError && <span className={styles.fieldError}>{newPwError}</span>}
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="reset-confirm-pw">{tla.confirmPasswordLabel}</label>
              <input
                id="reset-confirm-pw"
                className={styles.input}
                type="password"
                autoComplete="new-password"
                placeholder={tla.confirmPasswordPlaceholder}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                disabled={resetLoading}
              />
              {pwMismatch && <span className={styles.fieldError}>{tla.pwMismatch}</span>}
            </div>
            {resetError && <div className={styles.errorBanner}>{resetError}</div>}
            <button type="submit" className={styles.btnPrimary} disabled={resetLoading}>
              {resetLoading ? tla.changingPassword : tla.changePassword}
            </button>
          </form>
        )}
      </HelpModal>
    </div>
  );
}
