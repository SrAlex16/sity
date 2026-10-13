import { useState, useEffect, useRef } from 'react';
import { useDataset } from '../hooks/useDataset';
import { useDebug } from '../hooks/useDebug';
import { useSystemMetrics } from '../hooks/useSystemMetrics';
import type { DatasetCaptureRequest } from '../hooks/useDataset';
import type { TraceEvent, DatasetStats, CognitiveStats } from '../hooks/useDebug';
import type { SystemSnapshot, SystemRates, SystemHistory, ServiceStatus, ProcessInfo } from '../hooks/useSystemMetrics';
import { HelpModal } from '../components/HelpModal';
import { TRANSLATIONS } from '../i18n/translations';
import type { UiLang } from '../i18n/translations';
import styles from './DevToolsScreen.module.css';

// ── Internal tab types ────────────────────────────────────────────────────────

type DevTab = 'dataset' | 'debug' | 'system';

// ── Dataset capture ───────────────────────────────────────────────────────────

type PresetKey = 'normal_use' | 'synthetic_claude_user' | 'human_guest' | 'demo_session' | 'debug_test';

const PRESETS: Record<PresetKey, Partial<CaptureForm>> = {
  normal_use:            { dataset_source: 'normal_use',            speaker_source: 'human_local',           dataset_eligible: true,  dataset_tags: '' },
  synthetic_claude_user: { dataset_source: 'synthetic_claude_user', speaker_source: 'synthetic_claude_user', dataset_eligible: true,  dataset_tags: 'multi_persona' },
  human_guest:           { dataset_source: 'human_guest',           speaker_source: 'human_guest',           dataset_eligible: true,  dataset_tags: '' },
  demo_session:          { dataset_source: 'demo_session',          speaker_source: 'human_local',           dataset_eligible: true,  dataset_tags: 'demo' },
  debug_test:            { dataset_source: 'debug_test',            speaker_source: 'human_local',           dataset_eligible: false, dataset_tags: '' },
};

const DATASET_SOURCE_OPTIONS = ['normal_use', 'synthetic_claude_user', 'human_guest', 'demo_session', 'debug_test'] as const;
const SPEAKER_SOURCE_OPTIONS = ['human_local', 'synthetic_claude_user', 'human_guest'] as const;

interface CaptureForm {
  enabled: boolean;
  dataset_source: string;
  speaker_label: string;
  speaker_source: string;
  speaker_confidence: string;
  dataset_eligible: boolean;
  dataset_tags: string;
}

import type { DatasetCaptureContext } from '../hooks/useDataset';

function captureToForm(ctx: DatasetCaptureContext | null): CaptureForm {
  return {
    enabled:            ctx?.enabled              ?? false,
    dataset_source:     ctx?.dataset_source       ?? 'normal_use',
    speaker_label:      ctx?.speaker_label        ?? '',
    speaker_source:     ctx?.speaker_source       ?? '',
    speaker_confidence: ctx?.speaker_confidence != null ? String(ctx.speaker_confidence) : '',
    dataset_eligible:   ctx?.dataset_eligible     ?? true,
    dataset_tags:       ctx?.dataset_tags?.join(', ') ?? '',
  };
}

function formToRequest(form: CaptureForm): DatasetCaptureRequest {
  const conf = form.speaker_confidence.trim() ? parseFloat(form.speaker_confidence) : null;
  return {
    enabled:            form.enabled,
    dataset_source:     form.dataset_source || 'normal_use',
    speaker_label:      form.speaker_label.trim() || null,
    speaker_source:     form.speaker_source.trim() || null,
    speaker_confidence: conf,
    dataset_eligible:   form.dataset_eligible,
    dataset_tags:       form.dataset_tags.split(',').map((t) => t.trim()).filter(Boolean),
  };
}

// ── Dataset stats sub-components ──────────────────────────────────────────────

function DatasetStatsSection({ stats, loading }: { stats: DatasetStats | null; loading: boolean }) {
  if (loading && !stats) return <p className={styles.loading}>Cargando estadísticas…</p>;
  if (!stats) return null;

  const sortedTargets = Object.entries(stats.targets).sort(
    ([, a], [, b]) => (b.target - b.count) - (a.target - a.count),
  );
  const tagEntries = Object.entries(stats.by_tag).sort(([, a], [, b]) => b - a);
  const sourceEntries = Object.entries(stats.by_source).sort(([, a], [, b]) => b - a);

  return (
    <>
      <div className={styles.statsHeader}>
        <p className={styles.statsTitle}>Dataset LoRA v1</p>
        <span className={styles.statsComputedAt}>
          {new Date(stats.computed_at).toLocaleString()}
          {loading && ' · actualizando…'}
        </span>
      </div>

      <div className={styles.statsCards}>
        {[
          { label: 'Totales', value: stats.total_pairs },
          { label: 'Utilizables', value: stats.usable_pairs },
          { label: 'Sin tone_meta', value: stats.missing_tone_meta },
          { label: 'Operacionales', value: stats.operational_pairs },
          { label: 'Inelegibles', value: stats.ineligible_pairs },
        ].map(({ label, value }) => (
          <div key={label} className={styles.statCard}>
            <div className={styles.statValue}>{value}</div>
            <div className={styles.statLabel}>{label}</div>
          </div>
        ))}
      </div>

      {sortedTargets.length > 0 && (
        <div className={styles.section}>
          <p className={styles.sectionLabel}>Targets por bucket</p>
          {sortedTargets.map(([bucket, data]) => (
            <div key={bucket} className={styles.bucketRow}>
              <div className={styles.bucketHeader}>
                <span className={styles.bucketName}>{bucket}</span>
                <span className={styles.bucketCount}>{data.count}/{data.target} ({Math.round(data.progress * 100)}%)</span>
              </div>
              <div className={styles.progressBar}>
                <div className={styles.progressFill} style={{ width: `${data.progress * 100}%` }} />
              </div>
            </div>
          ))}
        </div>
      )}

      {sourceEntries.length > 0 && (
        <div className={styles.section}>
          <p className={styles.sectionLabel}>Por fuente</p>
          <div>
            {sourceEntries.map(([src, count]) => (
              <span key={src} className={styles.tagChip}>{src}: <span className={styles.tagCount}>{count}</span></span>
            ))}
          </div>
        </div>
      )}

      {tagEntries.length > 0 && (
        <div className={styles.section}>
          <p className={styles.sectionLabel}>Tags</p>
          <div>
            {tagEntries.map(([tag, count]) => (
              <span key={tag} className={styles.tagChip}>{tag}: <span className={styles.tagCount}>{count}</span></span>
            ))}
          </div>
        </div>
      )}

      {stats.recent_pairs.length > 0 && (
        <div>
          <p className={styles.statsTitle} style={{ padding: '12px 16px 8px' }}>Últimos pares</p>
          {stats.recent_pairs.map((pair, i) => (
            <div key={i} className={styles.recentPairCard}>
              <div className={styles.recentPairMeta}>
                <span className={styles.recentPairTime}>{new Date(pair.created_at).toLocaleString()}</span>
                <span className={styles.recentPairBucket}>{pair.primary_bucket}</span>
                <span className={styles.recentPairTime}>{pair.dataset_source}</span>
              </div>
              <p className={styles.recentPairText}>U: {pair.user_text}</p>
              <p className={`${styles.recentPairText} ${styles.recentPairSity}`}>S: {pair.sity_text}</p>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

// ── Debug sub-components ──────────────────────────────────────────────────────

function DebugStatCards({ stats, tl }: {
  stats: CognitiveStats | null;
  tl: { debugCogMetrics: string; debugGoalsActive: string; debugEpisodesDay: string; debugEpisodesTotal: string; debugFactsTotal: string; debugBeliefsTotal: string; debugMemSnapshot: string };
}) {
  if (!stats) return null;
  return (
    <>
      <div className={styles.section}>
        <p className={styles.sectionLabel}>{tl.debugCogMetrics}</p>
        <div className={styles.statsCards}>
          {[
            { label: tl.debugGoalsActive,   value: stats.goals_active },
            { label: tl.debugEpisodesDay,   value: stats.episodes_last_24h },
          ].map(({ label, value }) => (
            <div key={label} className={styles.statCard}>
              <div className={styles.statValue}>{value}</div>
              <div className={styles.statLabel}>{label}</div>
            </div>
          ))}
        </div>
      </div>
      <div className={styles.section}>
        <p className={styles.sectionLabel}>{tl.debugMemSnapshot}</p>
        <div className={styles.statsCards}>
          {[
            { label: tl.debugEpisodesTotal, value: stats.episodes_total },
            { label: tl.debugFactsTotal,    value: stats.semantic_facts_total },
            { label: tl.debugBeliefsTotal,  value: stats.self_beliefs_total },
          ].map(({ label, value }) => (
            <div key={label} className={styles.statCard}>
              <div className={styles.statValue}>{value}</div>
              <div className={styles.statLabel}>{label}</div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

function ErrorRow({ event }: { event: TraceEvent }) {
  return (
    <div className={styles.errorRow}>
      <span className={`${styles.eventLevel} ${styles[`level${event.level}`] ?? ''}`}>{event.level}</span>
      <span className={styles.errorRowModule}>{event.module}</span>
      <span className={styles.errorRowEvent}>{event.event}</span>
      <span className={styles.errorRowTime}>{new Date(event.timestamp).toLocaleTimeString()}</span>
    </div>
  );
}

function TimelineRow({ event }: { event: TraceEvent }) {
  return (
    <div className={styles.timelineRow}>
      <span className={styles.timelineTime}>{new Date(event.timestamp).toLocaleTimeString()}</span>
      <span className={styles.timelineModule}>{event.module}</span>
      <span className={styles.timelineEvent}>{event.event}</span>
      <span className={`${styles.eventLevel} ${styles[`level${event.level}`] ?? ''}`}>{event.level}</span>
    </div>
  );
}

// ── System tab — utilities ────────────────────────────────────────────────────

function fmtBytes(n: number): string {
  if (n >= 1073741824) return `${(n / 1073741824).toFixed(1)} GB`;
  if (n >= 1048576)    return `${(n / 1048576).toFixed(1)} MB`;
  if (n >= 1024)       return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}

function fmtBps(n: number): string {
  if (n >= 1048576) return `${(n / 1048576).toFixed(1)} MB/s`;
  if (n >= 1024)    return `${(n / 1024).toFixed(1)} KB/s`;
  return `${Math.round(n)} B/s`;
}

// ── System tab — sparklines ───────────────────────────────────────────────────

function Sparkline({ data, color, fill = false, h = 32, sparkId }: {
  data: number[];
  color: string;
  fill?: boolean;
  h?: number;
  sparkId: string;
}) {
  const W = 100;
  if (data.length < 2) {
    return <svg viewBox={`0 0 ${W} ${h}`} style={{ width: '100%', height: h }} />;
  }
  const maxVal = Math.max(...data, 1);
  const pad    = 2;
  const usable = h - pad * 2;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * W;
    const y = pad + (1 - v / maxVal) * usable;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  const linePath = `M ${pts.join(' L ')}`;

  if (fill) {
    const fillPath = `M 0,${h} L ${pts.join(' L ')} L ${W},${h} Z`;
    const gradId = `sg-${sparkId}`;
    return (
      <svg viewBox={`0 0 ${W} ${h}`} style={{ width: '100%', height: h }} preserveAspectRatio="none">
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.35" />
            <stop offset="100%" stopColor={color} stopOpacity="0.02" />
          </linearGradient>
        </defs>
        <path d={fillPath} fill={`url(#${gradId})`} />
        <path d={linePath} stroke={color} strokeWidth="1.5" fill="none" />
      </svg>
    );
  }

  return (
    <svg viewBox={`0 0 ${W} ${h}`} style={{ width: '100%', height: h }} preserveAspectRatio="none">
      <path d={linePath} stroke={color} strokeWidth="1.5" fill="none" />
    </svg>
  );
}

function DualSparkline({ data1, data2, color1, color2, h = 32 }: {
  data1: number[];
  data2: number[];
  color1: string;
  color2: string;
  h?: number;
}) {
  const W = 100;
  const both = [...data1, ...data2];
  if (both.length < 2) {
    return <svg viewBox={`0 0 ${W} ${h}`} style={{ width: '100%', height: h }} />;
  }
  const maxVal = Math.max(...both, 1);
  const pad    = 2;
  const usable = h - pad * 2;

  const toPath = (arr: number[]) => {
    if (arr.length < 2) return '';
    const pts = arr.map((v, i) => {
      const x = (i / (arr.length - 1)) * W;
      const y = pad + (1 - v / maxVal) * usable;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    });
    return `M ${pts.join(' L ')}`;
  };

  return (
    <svg viewBox={`0 0 ${W} ${h}`} style={{ width: '100%', height: h }} preserveAspectRatio="none">
      {toPath(data1) && <path d={toPath(data1)} stroke={color1} strokeWidth="1.5" fill="none" />}
      {toPath(data2) && <path d={toPath(data2)} stroke={color2} strokeWidth="1.5" fill="none" />}
    </svg>
  );
}

// ── System tab — metric cards ─────────────────────────────────────────────────

function CpuCard({ cpu, hist }: { cpu: SystemSnapshot['cpu']; hist: number[] }) {
  return (
    <div className={styles.sysCard}>
      <p className={styles.sysCardTitle}>CPU</p>
      <p className={styles.sysCardValue}>{cpu.load.toFixed(1)}<span className={styles.sysCardUnit}>%</span></p>
      <div className={styles.sparklineWrap}>
        <Sparkline data={hist} color="#00f5ff" fill sparkId="cpu" />
      </div>
      <p className={styles.sysCardSub}>{cpu.temp.toFixed(1)}°C · {cpu.cores}c/{cpu.threads}t</p>
    </div>
  );
}

function RamCard({ ram, hist }: { ram: SystemSnapshot['ram']; hist: number[] }) {
  const pct = ram.percent;
  return (
    <div className={styles.sysCard}>
      <p className={styles.sysCardTitle}>RAM</p>
      <p className={styles.sysCardValue}>{pct.toFixed(1)}<span className={styles.sysCardUnit}>%</span></p>
      <div className={styles.ramBar}>
        <div className={styles.ramBarFill} style={{ width: `${pct}%` }} />
      </div>
      <div className={styles.sparklineWrap} style={{ marginTop: 6 }}>
        <Sparkline data={hist} color="#e24bff" fill sparkId="ram" />
      </div>
      <p className={styles.sysCardSub}>{fmtBytes(ram.used)} / {fmtBytes(ram.total)}</p>
    </div>
  );
}

function NetCard({ net, rates, dlHist, ulHist }: {
  net: SystemSnapshot['net'];
  rates: SystemRates;
  dlHist: number[];
  ulHist: number[];
}) {
  return (
    <div className={styles.sysCard}>
      <p className={styles.sysCardTitle}>Red · {net.iface}</p>
      <p className={styles.sysCardValue}>
        <span className={styles.netDl}>↓{fmtBps(rates.dl)}</span>
        <span className={styles.netUl}> ↑{fmtBps(rates.ul)}</span>
      </p>
      <div className={styles.sparklineWrap}>
        <DualSparkline data1={dlHist} data2={ulHist} color1="#00f5ff" color2="#e24bff" />
      </div>
      <p className={styles.sysCardSub}>{net.local_ip}</p>
    </div>
  );
}

function DiskCard({ disk, rates, rHist, wHist }: {
  disk: SystemSnapshot['disk'];
  rates: SystemRates;
  rHist: number[];
  wHist: number[];
}) {
  return (
    <div className={styles.sysCard}>
      <p className={styles.sysCardTitle}>Disco</p>
      <p className={styles.sysCardValue}>
        <span className={styles.netUl}>R:{fmtBps(rates.diskR)}</span>
        <span className={styles.netDl}> W:{fmtBps(rates.diskW)}</span>
      </p>
      <div className={styles.sparklineWrap}>
        <DualSparkline data1={rHist} data2={wHist} color1="#e24bff" color2="#00f5ff" />
      </div>
      <p className={styles.sysCardSub}>{fmtBytes(disk.used)}/{fmtBytes(disk.total)} ({disk.percent}%)</p>
    </div>
  );
}

function PowerCard({ power }: { power: SystemSnapshot['power'] }) {
  const flags: { label: string; active: boolean; crit: boolean }[] = [
    { label: 'UV ahora',   active: power.undervoltage_now,  crit: true  },
    { label: 'Throt. ahora', active: power.throttled_now,  crit: true  },
    { label: 'UV pasado',  active: power.undervoltage_past, crit: false },
    { label: 'Throt. pasado', active: power.throttled_past,crit: false },
  ];
  return (
    <div className={`${styles.sysCard} ${styles.powerCard}`}>
      <p className={styles.sysCardTitle}>Voltaje</p>
      <p className={styles.sysCardSub} style={{ fontFamily: 'var(--font-mono)', marginBottom: 8 }}>
        {power.throttled_hex}
      </p>
      <div className={styles.powerFlags}>
        {flags.map(({ label, active, crit }) => (
          <span
            key={label}
            className={`${styles.powerFlag} ${active ? (crit ? styles.powerFlagCrit : styles.powerFlagWarn) : styles.powerFlagOk}`}
          >
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── System tab — services bar ─────────────────────────────────────────────────

const SERVICE_DOT_COLOR: Record<string, string> = {
  active:   '#00f5ff',
  failed:   '#ff3b5c',
  inactive: '#555577',
};

function ServicesBar({ services }: { services: ServiceStatus[] }) {
  return (
    <div className={styles.servicesBar}>
      {services.map((svc) => {
        const color = SERVICE_DOT_COLOR[svc.state] ?? '#cccc44';
        return (
          <div key={svc.name} className={styles.serviceDot}>
            <span className={styles.serviceDotIcon} style={{ background: color, boxShadow: `0 0 6px ${color}` }} />
            <span className={styles.serviceDotLabel}>{svc.name}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── System tab — process table ────────────────────────────────────────────────

function ProcTable({ processes }: { processes: ProcessInfo[] }) {
  return (
    <div className={styles.procTable}>
      <div className={`${styles.procRow} ${styles.procRowHeader}`}>
        <span className={styles.procName}>Proceso</span>
        <span className={styles.procPid}>PID</span>
        <span className={styles.procCpu}>CPU%</span>
        <span className={styles.procRam}>RAM%</span>
        <span className={styles.procState}>Estado</span>
      </div>
      {processes.map((p) => {
        const cpuColor = p.cpu > 30 ? '#ff3b5c' : p.cpu > 10 ? '#cccc44' : 'var(--text-secondary)';
        return (
          <div key={p.pid} className={`${styles.procRow} ${p.sity ? styles.procRowSity : ''}`}>
            <span className={styles.procName}>{p.name}</span>
            <span className={styles.procPid}>{p.pid}</span>
            <span className={styles.procCpu} style={{ color: cpuColor }}>{p.cpu.toFixed(1)}</span>
            <span className={styles.procRam}>{p.ram.toFixed(1)}</span>
            <span className={styles.procState}>{p.state}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── System tab — alert modal ──────────────────────────────────────────────────

interface SysAlert {
  id: number;
  severity: 'critical' | 'grave' | 'medium' | 'low';
  title: string;
  body: string;
}

const ALERT_SEV_COLOR: Record<SysAlert['severity'], string> = {
  critical: '#ff3b5c',
  grave:    '#ff8800',
  medium:   '#cccc44',
  low:      '#00f5ff',
};

function AlertModal({ alerts, idx, onDismiss, onPrev, onNext }: {
  alerts: SysAlert[];
  idx: number;
  onDismiss: (id: number) => void;
  onPrev: () => void;
  onNext: () => void;
}) {
  if (alerts.length === 0) return null;
  const safeIdx = Math.min(idx, alerts.length - 1);
  const alert   = alerts[safeIdx];
  if (!alert) return null;
  const color = ALERT_SEV_COLOR[alert.severity];

  return (
    <div className={styles.alertOverlay}>
      <div className={styles.alertModal} style={{ borderColor: color }}>
        <div className={styles.alertHeader}>
          <span className={styles.alertSeverity} style={{ color }}>{alert.severity.toUpperCase()}</span>
          <span className={styles.alertCount}>{safeIdx + 1}/{alerts.length}</span>
        </div>
        <p className={styles.alertTitle}>{alert.title}</p>
        <p className={styles.alertBody}>{alert.body}</p>
        <div className={styles.alertActions}>
          <button className={`${styles.btn} ${styles.btnSecondary}`} onClick={onPrev} disabled={safeIdx === 0}>←</button>
          <button className={`${styles.btn} ${styles.btnSecondary}`} onClick={onNext} disabled={safeIdx === alerts.length - 1}>→</button>
          <button className={`${styles.btn} ${styles.btnMagenta}`} onClick={() => onDismiss(alert.id)}>Cerrar</button>
        </div>
      </div>
    </div>
  );
}

// ── System tab — main content ─────────────────────────────────────────────────

function SystemTab({ snap, rates, hist, loading, error, refresh }: {
  snap: SystemSnapshot | null;
  rates: SystemRates;
  hist: SystemHistory;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}) {
  if (error) return <p className={styles.errorMsg} style={{ margin: 16 }}>{error}</p>;
  if (!snap && loading) return <p className={styles.loading}>Cargando métricas del sistema…</p>;
  if (!snap) return null;

  return (
    <div className={styles.systemWrapper}>
      <div className={styles.systemSysBar}>
        <ServicesBar services={snap.services} />
        <button
          className={`${styles.btn} ${styles.btnSecondary} ${styles.sysRefreshBtn}`}
          onClick={() => void refresh()}
          disabled={loading}
        >
          {loading ? '…' : '↺'}
        </button>
      </div>
      <div className={styles.systemGrid}>
        <CpuCard  cpu={snap.cpu}   hist={hist.cpuLoad} />
        <RamCard  ram={snap.ram}   hist={hist.ramPct} />
        <NetCard  net={snap.net}   rates={rates} dlHist={hist.dlBps}    ulHist={hist.ulBps} />
        <DiskCard disk={snap.disk} rates={rates} rHist={hist.diskRBps}  wHist={hist.diskWBps} />
        <PowerCard power={snap.power} />
      </div>
      <div className={styles.section} style={{ paddingTop: 10 }}>
        <p className={styles.sectionLabel}>Procesos ({snap.processes.length})</p>
        <ProcTable processes={snap.processes} />
      </div>
    </div>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

export function DevToolsScreen({ uiLang = 'es' }: { uiLang?: UiLang }) {
  const tl = TRANSLATIONS[uiLang].dataset;
  const { capture, isLoading: captureLoading, error: captureError, save, disable, reload: reloadCapture } = useDataset();
  const { recentEvents, lastTraceId, lastTraceEvents, datasetStats, cognitiveStats, isLoading: debugLoading, error: debugError, reload: reloadDebug } = useDebug();

  const [tab, setTab] = useState<DevTab>('dataset');
  const { snapshot: sysSnap, rates: sysRates, history: sysHist, isLoading: sysLoading, error: sysError, refresh: sysRefresh } = useSystemMetrics(tab === 'system');
  const [form, setForm]     = useState<CaptureForm>(() => captureToForm(null));
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  // Alert state
  const alertIdRef      = useRef(0);
  const cpuHighCountRef = useRef(0);
  const prevIpRef       = useRef<string | null>(null);
  const firedKeysRef    = useRef(new Set<string>());
  const [sysAlerts, setSysAlerts]   = useState<SysAlert[]>([]);
  const [sysAlertIdx, setSysAlertIdx] = useState(0);

  useEffect(() => {
    if (capture) setForm(captureToForm(capture));
  }, [capture]);

  useEffect(() => {
    void reloadDebug();
  }, [tab, reloadDebug]);

  // Alert detection on each new snapshot
  useEffect(() => {
    if (!sysSnap) return;
    const queue: SysAlert[] = [];
    const fire = (key: string, sev: SysAlert['severity'], title: string, body: string) => {
      if (firedKeysRef.current.has(key)) return;
      firedKeysRef.current.add(key);
      queue.push({ id: ++alertIdRef.current, severity: sev, title, body });
    };
    const clear = (key: string) => firedKeysRef.current.delete(key);

    // CPU >85% for 4+ polls (~12s)
    if (sysSnap.cpu.load > 85) {
      cpuHighCountRef.current += 1;
      if (cpuHighCountRef.current >= 4)
        fire('cpu_high', 'medium', 'CPU alta', `${sysSnap.cpu.load.toFixed(1)}% durante ~${cpuHighCountRef.current * 3}s`);
    } else {
      cpuHighCountRef.current = 0;
      clear('cpu_high');
    }

    // Temp >80°C
    if (sysSnap.cpu.temp > 80) fire('temp_high', 'grave', 'Temperatura crítica', `CPU a ${sysSnap.cpu.temp.toFixed(1)} °C`);
    else clear('temp_high');

    // Undervoltage now
    if (sysSnap.power.undervoltage_now) fire('uv_now', 'critical', 'Undervoltage activo', 'La Pi está recibiendo tensión insuficiente');
    else clear('uv_now');

    // Service failed
    for (const svc of sysSnap.services) {
      if (svc.state === 'failed') {
        const sev: SysAlert['severity'] = svc.name === 'sity-backend' ? 'critical' : 'grave';
        fire(`svc_${svc.name}`, sev, `Servicio caído`, svc.name);
      } else {
        clear(`svc_${svc.name}`);
      }
    }

    // IP changed
    if (prevIpRef.current !== null && prevIpRef.current !== sysSnap.net.local_ip)
      fire('ip_changed', 'low', 'IP local cambiada', `${prevIpRef.current} → ${sysSnap.net.local_ip}`);
    prevIpRef.current = sysSnap.net.local_ip;

    if (queue.length > 0) setSysAlerts((prev) => [...prev, ...queue]);
  }, [sysSnap]);

  // Keep alertIdx in bounds
  useEffect(() => {
    setSysAlertIdx((i) => (sysAlerts.length === 0 ? 0 : Math.min(i, sysAlerts.length - 1)));
  }, [sysAlerts.length]);

  const dismissAlert = (id: number) =>
    setSysAlerts((prev) => prev.filter((a) => a.id !== id));

  const busy     = saving || captureLoading;
  const isActive = capture?.enabled ?? false;

  const patch = (delta: Partial<CaptureForm>) => setForm((p) => ({ ...p, ...delta }));
  const applyPreset = (key: PresetKey) => setForm((p) => ({ ...p, ...PRESETS[key] }));

  const validate = (): boolean => {
    setFormError(null);
    if (form.enabled && !form.speaker_source.trim()) {
      setFormError('speaker_source es obligatorio cuando capture está activo.');
      return false;
    }
    const conf = form.speaker_confidence.trim();
    if (conf) {
      const n = parseFloat(conf);
      if (isNaN(n) || n < 0 || n > 1) {
        setFormError('speaker_confidence debe estar entre 0 y 1.');
        return false;
      }
    }
    return true;
  };

  const handleSave = async () => {
    if (!validate()) return;
    setSaving(true);
    try { await save(formToRequest(form)); } catch { /* shown via hook */ } finally { setSaving(false); }
  };

  const handleDisable = async () => {
    setSaving(true);
    try { await disable(); } catch { /* shown via hook */ } finally { setSaving(false); }
  };

  const handleRestorePersonality = async () => {
    setSaving(true);
    try {
      const r = await fetch('/settings/personality/reset', { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
    } catch { /* silent */ } finally { setSaving(false); }
  };

  const handleTabChange = (next: DevTab) => setTab(next);

  const activeLabel = isActive
    ? `${tl.activePrefix}: ${capture?.dataset_source ?? ''}${capture?.speaker_label ? ` / ${capture.speaker_label}` : ''}`
    : tl.inactive;

  const headerSub = tab === 'dataset'
    ? activeLabel
    : tab === 'debug'
    ? (lastTraceId ?? 'sin traza')
    : sysSnap
    ? `${sysSnap.net.local_ip} · ${new Date(sysSnap.timestamp).toLocaleTimeString()}`
    : 'sistema';

  return (
    <div className={styles.screen}>
      {/* Header */}
      <header className={styles.header}>
        <div className={styles.headerText}>
          <span className={styles.titleMain}>Dev Tools</span>
          <span className={`${styles.titleSub} ${tab === 'dataset' && isActive ? styles.titleSubActive : ''}`}>
            {headerSub}
          </span>
        </div>
        <button className={styles.helpBtn} onClick={() => setHelpOpen(true)}>?</button>
      </header>

      {/* Internal tabs */}
      <div className={styles.tabsRow}>
        <button
          className={`${styles.tabBtn} ${tab === 'dataset' ? styles.tabBtnActive : ''}`}
          onClick={() => handleTabChange('dataset')}
        >
          Dataset
        </button>
        <button
          className={`${styles.tabBtn} ${tab === 'debug' ? styles.tabBtnActive : ''}`}
          onClick={() => handleTabChange('debug')}
        >
          Debug
        </button>
        <button
          className={`${styles.tabBtn} ${tab === 'system' ? styles.tabBtnActive : ''}`}
          onClick={() => handleTabChange('system')}
        >
          System
        </button>
      </div>

      {/* Tab content */}
      <div className={styles.tabContent}>

        {/* ── Dataset tab ── */}
        {tab === 'dataset' && (
          <>
            {(captureError || formError) && (
              <p className={styles.errorMsg}>{formError ?? captureError}</p>
            )}

            {!capture && captureLoading && <p className={styles.loading}>{tl.loading}</p>}

            <div className={styles.section}>
              <label className={styles.checkboxRow}>
                <input
                  type="checkbox"
                  className={styles.hiddenInput}
                  checked={form.enabled}
                  onChange={(e) => patch({ enabled: e.target.checked })}
                />
                <span className={`${styles.checkboxIndicator} ${styles.checkboxLarge}`} />
                <div>
                  <p className={styles.fieldLabel}>{tl.captureActive}</p>
                  <p className={styles.fieldHint}>{tl.captureHint}</p>
                </div>
              </label>
            </div>

            <div className={styles.section}>
              <p className={styles.sectionLabel}>{tl.preset}</p>
              <div className={styles.chipRow}>
                {(Object.keys(PRESETS) as PresetKey[]).map((key) => (
                  <button
                    key={key}
                    className={`${styles.chip} ${form.dataset_source === key ? styles.chipActive : ''}`}
                    onClick={() => applyPreset(key)}
                    disabled={busy}
                  >
                    {key}
                  </button>
                ))}
              </div>
            </div>

            <div className={styles.fieldsGrid}>
              <div className={styles.field}>
                <label className={styles.fieldLabel}>dataset_source</label>
                <select
                  className={styles.select}
                  value={form.dataset_source}
                  onChange={(e) => patch({ dataset_source: e.target.value })}
                >
                  {DATASET_SOURCE_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              </div>

              <div className={styles.field}>
                <label className={styles.fieldLabel}>speaker_source</label>
                <select
                  className={styles.select}
                  value={form.speaker_source}
                  onChange={(e) => patch({ speaker_source: e.target.value })}
                >
                  <option value="">{tl.noneOption}</option>
                  {SPEAKER_SOURCE_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              </div>

              <div className={styles.field}>
                <label className={styles.fieldLabel}>speaker_label</label>
                <input
                  type="text"
                  className={styles.input}
                  value={form.speaker_label}
                  onChange={(e) => patch({ speaker_label: e.target.value })}
                  placeholder="alex, guest_01…"
                />
              </div>

              <div className={styles.field}>
                <label className={styles.fieldLabel}>speaker_confidence (0–1)</label>
                <input
                  type="number"
                  className={styles.input}
                  min="0" max="1" step="0.05"
                  value={form.speaker_confidence}
                  onChange={(e) => patch({ speaker_confidence: e.target.value })}
                  placeholder="0.9"
                />
              </div>

              <div className={`${styles.field} ${styles.fieldFull}`}>
                <label className={styles.fieldLabel}>
                  dataset_tags <span className={styles.fieldHint}>(coma-separados)</span>
                </label>
                <input
                  type="text"
                  className={styles.input}
                  value={form.dataset_tags}
                  onChange={(e) => patch({ dataset_tags: e.target.value })}
                  placeholder="multi_persona, casual"
                />
              </div>

              <div className={`${styles.field} ${styles.fieldFull}`}>
                <label className={styles.checkboxRow}>
                  <input
                    type="checkbox"
                    className={styles.hiddenInput}
                    checked={form.dataset_eligible}
                    onChange={(e) => patch({ dataset_eligible: e.target.checked })}
                  />
                  <span className={styles.checkboxIndicator} />
                  <div>
                    <span className={styles.fieldLabel}>dataset_eligible</span>
                    <p className={styles.fieldHint}>Incluir en el pool de candidatos para fine-tuning</p>
                  </div>
                </label>
              </div>
            </div>

            <div className={styles.actionsRow}>
              <button className={`${styles.btn} ${styles.btnCyan}`} onClick={handleSave} disabled={busy}>
                {saving ? '…' : tl.save}
              </button>
              <button className={`${styles.btn} ${styles.btnMagenta}`} onClick={handleDisable} disabled={busy || !isActive}>
                {tl.disable}
              </button>
              <button className={`${styles.btn} ${styles.btnSecondary}`} onClick={() => void reloadCapture()} disabled={busy}>
                {tl.reload}
              </button>
              <button className={`${styles.btn} ${styles.btnSecondary}`} onClick={handleRestorePersonality} disabled={busy}>
                {tl.restorePersonality}
              </button>
            </div>

            <DatasetStatsSection stats={datasetStats} loading={debugLoading} />
          </>
        )}

        {/* ── Debug tab ── */}
        {tab === 'debug' && (
          <>
            <div className={styles.section}>
              <div className={styles.sectionRow}>
                <p className={styles.sectionLabel}>{tl.debugTraceTimeline}</p>
                <button className={`${styles.btn} ${styles.btnSecondary}`} onClick={() => void reloadDebug()} disabled={debugLoading}>
                  {tl.debugRefresh}
                </button>
              </div>
            </div>

            {debugError && <p className={styles.errorMsg}>{debugError}</p>}

            <DebugStatCards stats={cognitiveStats} tl={tl} />

            <div className={styles.section}>
              <p className={styles.sectionLabel}>{tl.debugRecentErrors}</p>
              {(() => {
                const errors = recentEvents.filter(ev => ev.level === 'ERROR' || ev.level === 'WARN').slice(-8).reverse();
                if (errors.length === 0) return <p className={styles.emptyMsg}>{tl.debugNoErrors}</p>;
                return errors.map((ev, i) => <ErrorRow key={`err-${ev.timestamp}-${i}`} event={ev} />);
              })()}
            </div>

            <div className={styles.section}>
              <div className={styles.sectionRow}>
                <p className={styles.sectionLabel}>{tl.debugTraceTimeline}</p>
                <span className={styles.traceIdLabel}>{lastTraceId ?? tl.debugNoTrace}</span>
              </div>
              {lastTraceEvents.length === 0 && !debugLoading && (
                <p className={styles.emptyMsg}>{tl.debugNoEvents}</p>
              )}
              {lastTraceEvents.map((ev, i) => <TimelineRow key={`tl-${ev.timestamp}-${i}`} event={ev} />)}
            </div>
          </>
        )}

        {/* ── System tab ── */}
        {tab === 'system' && (
          <SystemTab
            snap={sysSnap}
            rates={sysRates}
            hist={sysHist}
            loading={sysLoading}
            error={sysError}
            refresh={sysRefresh}
          />
        )}

      </div>

      {/* Alert modal */}
      {sysAlerts.length > 0 && (
        <AlertModal
          alerts={sysAlerts}
          idx={sysAlertIdx}
          onDismiss={dismissAlert}
          onPrev={() => setSysAlertIdx((i) => Math.max(0, i - 1))}
          onNext={() => setSysAlertIdx((i) => Math.min(sysAlerts.length - 1, i + 1))}
        />
      )}

      <HelpModal open={helpOpen} onClose={() => setHelpOpen(false)} title="Dev Tools">
        <p><strong>Dataset</strong> — configura la captura de conversaciones para el dataset LoRA y consulta estadísticas del dataset actual.</p>
        <p><strong>Debug</strong> — muestra la última traza de eventos del backend y los eventos recientes del sistema.</p>
        <p><strong>System</strong> — métricas de la Pi en tiempo real: CPU, RAM, red, disco, voltaje, servicios y procesos. Polling cada 3 s mientras la pestaña está activa.</p>
        <p><strong>dataset_source</strong> — tipo de sesión. Define cómo se agrupa este dato en la exportación.</p>
        <p><strong>speaker_source</strong> — indica si el input viene de una persona o de Claude.</p>
        <p><strong>dataset_eligible</strong> — si este par entra en el pool de candidatos para fine-tuning.</p>
        <p>Solo visible para admin.</p>
      </HelpModal>
    </div>
  );
}
