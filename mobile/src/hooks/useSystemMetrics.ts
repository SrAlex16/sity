import { useState, useEffect, useCallback, useRef } from 'react';

export interface CpuMetrics   { load: number; temp: number; cores: number; threads: number; }
export interface RamMetrics   { used: number; total: number; percent: number; }
export interface NetMetrics   { iface: string; local_ip: string; bytes_sent: number; bytes_recv: number; }
export interface DiskMetrics  { read_bytes: number; write_bytes: number; used: number; total: number; percent: number; }
export interface PowerMetrics { throttled_hex: string; undervoltage_now: boolean; throttled_now: boolean; undervoltage_past: boolean; throttled_past: boolean; }
export interface ServiceStatus { name: string; state: string; }
export interface ProcessInfo   { pid: number; name: string; state: string; cpu: number; ram: number; sity: boolean; }

export interface SystemSnapshot {
  cpu: CpuMetrics;
  ram: RamMetrics;
  net: NetMetrics;
  disk: DiskMetrics;
  power: PowerMetrics;
  services: ServiceStatus[];
  processes: ProcessInfo[];
  timestamp: string;
}

export interface SystemRates {
  dl: number;    // bytes/s received
  ul: number;    // bytes/s sent
  diskR: number; // bytes/s read
  diskW: number; // bytes/s write
}

export interface SystemHistory {
  cpuLoad:  number[];
  ramPct:   number[];
  dlBps:    number[];
  ulBps:    number[];
  diskRBps: number[];
  diskWBps: number[];
}

const HISTORY_LEN  = 60;
const POLL_MS      = 3000;

function emptyRates(): SystemRates {
  return { dl: 0, ul: 0, diskR: 0, diskW: 0 };
}

function emptyHistory(): SystemHistory {
  return { cpuLoad: [], ramPct: [], dlBps: [], ulBps: [], diskRBps: [], diskWBps: [] };
}

function push60<T>(arr: T[], val: T): T[] {
  const next = [...arr, val];
  return next.length > HISTORY_LEN ? next.slice(-HISTORY_LEN) : next;
}

export function useSystemMetrics(active: boolean) {
  const [snapshot, setSnapshot]   = useState<SystemSnapshot | null>(null);
  const [rates,    setRates]      = useState<SystemRates>(emptyRates);
  const [history,  setHistory]    = useState<SystemHistory>(emptyHistory);
  const [isLoading, setIsLoading] = useState(false);
  const [error,    setError]      = useState<string | null>(null);
  const prevRef = useRef<SystemSnapshot | null>(null);

  const poll = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch('/debug/system-metrics');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json() as SystemSnapshot;
      const prev = prevRef.current;
      let newRates = emptyRates();

      if (prev) {
        const dtMs = new Date(data.timestamp).getTime() - new Date(prev.timestamp).getTime();
        const dt   = Math.max(dtMs / 1000, 0.1);
        newRates = {
          dl:    Math.max(0, (data.net.bytes_recv   - prev.net.bytes_recv)   / dt),
          ul:    Math.max(0, (data.net.bytes_sent   - prev.net.bytes_sent)   / dt),
          diskR: Math.max(0, (data.disk.read_bytes  - prev.disk.read_bytes)  / dt),
          diskW: Math.max(0, (data.disk.write_bytes - prev.disk.write_bytes) / dt),
        };
      }

      prevRef.current = data;
      setSnapshot(data);
      setRates(newRates);
      setHistory((h) => ({
        cpuLoad:  push60(h.cpuLoad,  data.cpu.load),
        ramPct:   push60(h.ramPct,   data.ram.percent),
        dlBps:    push60(h.dlBps,    newRates.dl),
        ulBps:    push60(h.ulBps,    newRates.ul),
        diskRBps: push60(h.diskRBps, newRates.diskR),
        diskWBps: push60(h.diskWBps, newRates.diskW),
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error cargando métricas');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!active) return;
    void poll();
    const id = setInterval(() => void poll(), POLL_MS);
    return () => clearInterval(id);
  }, [active, poll]);

  return { snapshot, rates, history, isLoading, error, refresh: poll };
}
