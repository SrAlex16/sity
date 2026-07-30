import React, { useState } from 'react';
import { HelpModal } from '../components/HelpModal';
import type { UseAuthResult } from '../hooks/useAuth';
import { getRecaptchaToken } from '../utils/recaptcha';
import styles from './AuthForm.module.css';

interface Props {
  auth: UseAuthResult;
  onSwitchToLogin: () => void;
}

// Mirror of backend _check_password_strength
function checkPasswordStrength(password: string): string | null {
  if (password.length < 8) return 'Mínimo 8 caracteres.';
  if (!/[A-Z]/.test(password)) return 'Debe incluir al menos una mayúscula.';
  if (!/[a-z]/.test(password)) return 'Debe incluir al menos una minúscula.';
  if (!/\d/.test(password)) return 'Debe incluir al menos un número.';
  return null;
}

export function RegisterScreen({ auth, onSwitchToLogin }: Props) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [rgpdChecked, setRgpdChecked] = useState(false);
  const [rgpdOpen, setRgpdOpen] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const pwError = password ? checkPasswordStrength(password) : null;
  const pwMismatch = confirmPassword && password !== confirmPassword;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');

    if (!email) { setError('El email es obligatorio.'); return; }
    if (!email.includes('@')) { setError('Introduce un email válido.'); return; }
    const strengthError = checkPasswordStrength(password);
    if (strengthError) { setError(strengthError); return; }
    if (password !== confirmPassword) { setError('Las contraseñas no coinciden.'); return; }
    if (!rgpdChecked) { setError('Debes aceptar la política de privacidad.'); return; }

    setLoading(true);
    const token = await getRecaptchaToken('register');
    const result = await auth.register(email, password, token);
    setLoading(false);
    if (!result.ok) setError(result.error ?? 'Error al registrarse.');
  }

  return (
    <div className={styles.screen}>
      <p className={styles.logo}>SITY</p>
      <p className={styles.tagline}>// SISTEMA DE IA PERSONAL</p>

      <div className={styles.card}>
        <p className={styles.cardTitle}>Crear cuenta</p>

        {error && <div className={styles.errorBanner}>{error}</div>}

        <form onSubmit={handleSubmit} style={{ display: 'contents' }}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="reg-email">Email</label>
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
            <label className={styles.label} htmlFor="reg-password">Contraseña</label>
            <input
              id="reg-password"
              className={styles.input}
              type="password"
              autoComplete="new-password"
              placeholder="Mín. 8 car., mayús., minús. y número"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loading}
            />
            {pwError && <span className={styles.fieldError}>{pwError}</span>}
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor="reg-confirm">Confirmar contraseña</label>
            <input
              id="reg-confirm"
              className={styles.input}
              type="password"
              autoComplete="new-password"
              placeholder="Repite la contraseña"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              disabled={loading}
            />
            {pwMismatch && <span className={styles.fieldError}>Las contraseñas no coinciden.</span>}
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
              He leído y acepto la{' '}
              <button
                type="button"
                className={styles.checkLink}
                onClick={() => setRgpdOpen(true)}
              >
                política de privacidad
              </button>
            </label>
          </div>

          <button type="submit" className={styles.btnPrimary} disabled={loading}>
            {loading ? 'Registrando…' : 'Crear cuenta'}
          </button>
        </form>

        <div className={styles.divider}>o</div>

        {/* TODO: Google OAuth — backend not implemented yet */}
        <button type="button" className={styles.btnGoogle} disabled aria-disabled="true">
          G&nbsp; Registrarse con Google (próximamente)
        </button>

        <p className={styles.switchRow}>
          ¿Ya tienes cuenta?{' '}
          <button type="button" className={styles.switchLink} onClick={onSwitchToLogin}>
            Iniciar sesión
          </button>
        </p>
      </div>

      {/* RGPD privacy modal */}
      <HelpModal
        open={rgpdOpen}
        onClose={() => setRgpdOpen(false)}
        title="Política de privacidad"
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
