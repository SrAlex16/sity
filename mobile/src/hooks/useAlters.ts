import { useState, useEffect } from 'react';

export interface AlterSlot {
  slot: number;
  name: string | null;
  parameters: Record<string, number> | null;
  is_empty: boolean;
}

export function useAlters() {
  const [slots, setSlots] = useState<AlterSlot[]>([]);
  const [busy, setBusy] = useState<number | null>(null); // slot in flight

  useEffect(() => { void refresh(); }, []);

  async function refresh(): Promise<void> {
    const r = await fetch('/settings/alters');
    if (!r.ok) return;
    setSlots(await r.json() as AlterSlot[]);
  }

  async function save(slot: number, name: string): Promise<void> {
    setBusy(slot);
    try {
      const r = await fetch(`/settings/alters/${slot}/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (!r.ok) throw new Error('save');
      const updated = await r.json() as AlterSlot;
      setSlots((prev) => prev.map((s) => (s.slot === slot ? updated : s)));
    } finally {
      setBusy(null);
    }
  }

  async function load(slot: number): Promise<void> {
    setBusy(slot);
    try {
      const r = await fetch(`/settings/alters/${slot}/load`, { method: 'POST' });
      if (!r.ok) throw new Error('load');
    } finally {
      setBusy(null);
    }
  }

  async function rename(slot: number, name: string): Promise<void> {
    setBusy(slot);
    try {
      const r = await fetch(`/settings/alters/${slot}/rename`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (!r.ok) throw new Error('rename');
      setSlots((prev) => prev.map((s) => (s.slot === slot ? { ...s, name } : s)));
    } finally {
      setBusy(null);
    }
  }

  async function clear(slot: number): Promise<void> {
    setBusy(slot);
    try {
      const r = await fetch(`/settings/alters/${slot}`, { method: 'DELETE' });
      if (!r.ok) throw new Error('clear');
      setSlots((prev) =>
        prev.map((s) =>
          s.slot === slot ? { slot, name: null, parameters: null, is_empty: true } : s
        )
      );
    } finally {
      setBusy(null);
    }
  }

  async function copy(fromSlot: number, toSlot: number): Promise<void> {
    setBusy(fromSlot);
    try {
      const r = await fetch(`/settings/alters/${fromSlot}/copy/${toSlot}`, { method: 'POST' });
      if (!r.ok) throw new Error('copy');
      const updated = await r.json() as AlterSlot;
      setSlots((prev) => prev.map((s) => (s.slot === toSlot ? updated : s)));
    } finally {
      setBusy(null);
    }
  }

  return { slots, busy, refresh, save, load, rename, clear, copy };
}
