import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { LoginScreen } from './LoginScreen';
import type { UseAuthResult } from '../hooks/useAuth';

vi.mock('../utils/recaptcha', () => ({
  getRecaptchaToken: vi.fn().mockResolvedValue(''),
  loadRecaptchaScript: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('../components/HelpModal', () => ({
  HelpModal: ({ children, open }: { children: React.ReactNode; open: boolean }) =>
    open ? <div>{children}</div> : null,
}));

const mockAuth: UseAuthResult = {
  currentUser: null,
  guestOptedIn: true,
  maintenance: false,
  login: vi.fn().mockResolvedValue({ ok: true }),
  register: vi.fn().mockResolvedValue({ ok: true }),
  forgotPassword: vi.fn().mockResolvedValue({ ok: true }),
  resetPassword: vi.fn().mockResolvedValue({ ok: true }),
  continueAsGuest: vi.fn(),
  logout: vi.fn(),
  refreshUser: vi.fn().mockResolvedValue(undefined),
};

function renderLogin() {
  return render(
    <LoginScreen
      auth={mockAuth}
      onSwitchToRegister={vi.fn()}
      uiLang="es"
    />
  );
}

describe('LoginScreen — show/hide password toggle', () => {
  it('login password field starts as type=password', () => {
    renderLogin();
    expect(screen.getByLabelText('Contraseña')).toHaveAttribute('type', 'password');
  });

  it('clicking the eye button reveals the login password', () => {
    renderLogin();
    const input = screen.getByLabelText('Contraseña');
    const toggle = screen.getByRole('button', { name: 'Mostrar contraseña' });

    fireEvent.click(toggle);
    expect(input).toHaveAttribute('type', 'text');
  });

  it('clicking the eye button twice hides the login password again', () => {
    renderLogin();
    const input = screen.getByLabelText('Contraseña');
    const toggle = screen.getByRole('button', { name: 'Mostrar contraseña' });

    fireEvent.click(toggle);
    expect(input).toHaveAttribute('type', 'text');

    fireEvent.click(screen.getByRole('button', { name: 'Ocultar contraseña' }));
    expect(input).toHaveAttribute('type', 'password');
  });
});
