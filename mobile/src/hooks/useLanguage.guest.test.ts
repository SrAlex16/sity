/**
 * R11-01 — useLanguage guest mode: load from sessionStorage, save to sessionStorage.
 */
import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import { useLanguage, GUEST_LANG_KEY } from './useLanguage';

beforeEach(() => {
  sessionStorage.clear();
});

describe('useLanguage — guest mode', () => {

  it('returns auto when sessionStorage is empty', () => {
    const { result } = renderHook(() => useLanguage(true));
    expect(result.current.settings?.language_override).toBe('auto');
  });

  it('loads stored language from sessionStorage on mount', () => {
    sessionStorage.setItem(GUEST_LANG_KEY, 'en-US');
    const { result } = renderHook(() => useLanguage(true));
    expect(result.current.settings?.language_override).toBe('en-US');
  });

  it('save() stores value in sessionStorage and updates state', async () => {
    const { result } = renderHook(() => useLanguage(true));
    await act(async () => { await result.current.save('ja'); });
    expect(sessionStorage.getItem(GUEST_LANG_KEY)).toBe('ja');
    expect(result.current.settings?.language_override).toBe('ja');
  });

  it('save("auto") removes key from sessionStorage', async () => {
    sessionStorage.setItem(GUEST_LANG_KEY, 'en-US');
    const { result } = renderHook(() => useLanguage(true));
    await act(async () => { await result.current.save('auto'); });
    expect(sessionStorage.getItem(GUEST_LANG_KEY)).toBeNull();
    expect(result.current.settings?.language_override).toBe('auto');
  });

  it('non-guest mode does not read sessionStorage', () => {
    sessionStorage.setItem(GUEST_LANG_KEY, 'en-US');
    // isGuest=false → should attempt fetch, not read sessionStorage.
    // We only verify that settings is NOT immediately populated from storage.
    const { result } = renderHook(() => useLanguage(false));
    // settings starts null while the fetch is in flight
    expect(result.current.settings).toBeNull();
  });

});
