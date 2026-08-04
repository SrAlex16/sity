import React, { useState, useEffect } from 'react';
import { HelpModal } from '../components/HelpModal';
import type { UseAuthResult } from '../hooks/useAuth';
import { getRecaptchaToken } from '../utils/recaptcha';
import styles from './AuthForm.module.css';

interface Props {
  auth: UseAuthResult;
  onSwitchToRegister: () => void;
  initialResetToken?: string | null;
  onResetTokenConsumed?: () => void;
}

// Mirror of backend _check_password_strength
function checkPasswordStrength(password: string): string | null {
  if (password.length < 8) return 'Mínimo 8 caracteres.';
  if (!/[A-Z]/.test(password)) return 'Debe incluir al menos una mayúscula.';
  if (!/[a-z]/.test(password)) return 'Debe incluir al menos una minúscula.';
  if (!/\d/.test(password)) return 'Debe incluir al menos un número.';
  return null;
}

export function LoginScreen({ auth, onSwitchToRegister, initialResetToken, onResetTokenConsumed }: Props) {
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
      setError('Email y contraseña son obligatorios.');
      return;
    }

    setLoading(true);
    const token = await getRecaptchaToken('login');
    const result = await auth.login(email, password, token);
    setLoading(false);
    if (!result.ok) setError(result.error ?? 'Error al iniciar sesión.');
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

    const strengthError = checkPasswordStrength(newPassword);
    if (strengthError) { setResetError(strengthError); return; }
    if (newPassword !== confirmPassword) { setResetError('Las contraseñas no coinciden.'); return; }

    setResetLoading(true);
    const result = await auth.resetPassword(resetToken, newPassword);
    setResetLoading(false);

    if (result.ok) {
      setResetSuccess(true);
    } else {
      setResetError(
        'Este enlace ya no es válido. Pide uno nuevo desde "He olvidado mi contraseña".',
      );
    }
  }

  function closeReset() {
    setResetOpen(false);
    setResetSuccess(false);
    setNewPassword('');
    setConfirmPassword('');
    setResetError('');
  }

  const newPwError = newPassword ? checkPasswordStrength(newPassword) : null;
  const pwMismatch = confirmPassword && newPassword !== confirmPassword;

  return (
    <div className={styles.screen}>
      <p className={styles.logo}>SITY</p>
      <p className={styles.tagline}>// SISTEMA DE IA PERSONAL</p>

      <div className={styles.card}>
        <p className={styles.cardTitle}>Iniciar sesión</p>

        {error && <div className={styles.errorBanner}>{error}</div>}

        <form onSubmit={handleSubmit} style={{ display: 'contents' }}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="login-email">Email</label>
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
            <label className={styles.label} htmlFor="login-password">Contraseña</label>
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
              He olvidado la contraseña
            </button>
          </div>

          <button type="submit" className={styles.btnPrimary} disabled={loading}>
            {loading ? 'Conectando…' : 'Iniciar sesión'}
          </button>
        </form>

        <button
          type="button"
          className={styles.btnSecondary}
          onClick={auth.continueAsGuest}
          disabled={loading}
        >
          Continuar como invitado
        </button>

        <div className={styles.divider}>o</div>

        {/* TODO: Google OAuth — backend not implemented yet */}
        <button type="button" className={styles.btnGoogle} disabled aria-disabled="true">
          G&nbsp; Iniciar sesión con Google (próximamente)
        </button>

        <p className={styles.switchRow}>
          ¿No tienes cuenta?{' '}
          <button type="button" className={styles.switchLink} onClick={onSwitchToRegister}>
            Crear cuenta
          </button>
        </p>
      </div>

      {/* Forgot password modal */}
      <HelpModal
        open={forgotOpen}
        onClose={() => setForgotOpen(false)}
        title="Recuperar contraseña"
      >
        {forgotStatus === 'sent' ? (
          <p className={styles.modalText}>
            Si el email está registrado, recibirás un enlace de recuperación.
          </p>
        ) : (
          <form onSubmit={handleForgot} style={{ display: 'contents' }}>
            <p className={styles.modalText}>
              Introduce tu email y te enviaremos un enlace para restablecer la contraseña.
            </p>
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
                Error al enviar. Inténtalo de nuevo.
              </p>
            )}
            <button type="submit" className={styles.btnPrimary}>Enviar enlace</button>
          </form>
        )}
      </HelpModal>

      {/* Reset password modal — opens automatically when the app detects /reset-password?token= in the URL */}
      <HelpModal
        open={resetOpen}
        onClose={closeReset}
        title="Nueva contraseña"
      >
        {resetSuccess ? (
          <>
            <p className={styles.modalText}>
              ¡Contraseña actualizada correctamente! Ya puedes iniciar sesión con tu nueva contraseña.
            </p>
            <button type="button" className={styles.btnPrimary} onClick={closeReset}>
              Iniciar sesión
            </button>
          </>
        ) : (
          <form onSubmit={handleReset} style={{ display: 'contents' }}>
            <p className={styles.modalText}>
              Introduce tu nueva contraseña.
            </p>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="reset-new-pw">Nueva contraseña</label>
              <input
                id="reset-new-pw"
                className={styles.input}
                type="password"
                autoComplete="new-password"
                placeholder="Mín. 8 car., mayús., minús. y número"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                disabled={resetLoading}
              />
              {newPwError && <span className={styles.fieldError}>{newPwError}</span>}
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="reset-confirm-pw">Confirmar contraseña</label>
              <input
                id="reset-confirm-pw"
                className={styles.input}
                type="password"
                autoComplete="new-password"
                placeholder="Repite la contraseña"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                disabled={resetLoading}
              />
              {pwMismatch && <span className={styles.fieldError}>Las contraseñas no coinciden.</span>}
            </div>
            {resetError && <div className={styles.errorBanner}>{resetError}</div>}
            <button type="submit" className={styles.btnPrimary} disabled={resetLoading}>
              {resetLoading ? 'Actualizando…' : 'Cambiar contraseña'}
            </button>
          </form>
        )}
      </HelpModal>
    </div>
  );
}
