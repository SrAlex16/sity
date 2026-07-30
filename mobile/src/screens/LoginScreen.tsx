import React, { useState } from 'react';
import { HelpModal } from '../components/HelpModal';
import type { UseAuthResult } from '../hooks/useAuth';
import { getRecaptchaToken } from '../utils/recaptcha';
import styles from './AuthForm.module.css';

interface Props {
  auth: UseAuthResult;
  onSwitchToRegister: () => void;
}

export function LoginScreen({ auth, onSwitchToRegister }: Props) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const [forgotOpen, setForgotOpen] = useState(false);
  const [forgotEmail, setForgotEmail] = useState('');
  const [forgotStatus, setForgotStatus] = useState<'idle' | 'sent' | 'error'>('idle');

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
    </div>
  );
}
