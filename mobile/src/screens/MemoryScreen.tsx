import { useState, useEffect, useCallback } from 'react';
import { TRANSLATIONS } from '../i18n/translations';
import type { UiLang } from '../i18n/translations';
import styles from './MemoryScreen.module.css';

type MemoryTab = 'facts' | 'episodes' | 'selfbeliefs';

interface SemanticFactItem {
  id: number;
  proposition: string;
  confidence: number;
  stability: string;
  inference_type: string;
  created_at: string;
}

interface EpisodeItem {
  id: number;
  summary: string;
  occurred_at: string;
  salience_total: number;
}

interface SelfBeliefItem {
  id: number;
  proposition: string;
  confidence: number;
  source: string;
  reinforcement_count: number;
  contradiction_count: number;
  created_at: string;
}

interface PagedResult<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
}

interface MemoryScreenProps {
  role: string;
  uiLang?: UiLang;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function confidenceColor(c: number): string {
  if (c > 0.60) return '#00f5ff';
  if (c >= 0.45) return '#ff8000';
  return '#ff4060';
}

function formatRelativeDate(isoStr: string, lang: UiLang): string {
  const date = new Date(isoStr);
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - date.getTime()) / 86400000);
  if (diffDays === 0) return lang === 'ja' ? '今日' : lang === 'en' ? 'today' : 'hoy';
  if (diffDays === 1) return lang === 'ja' ? '昨日' : lang === 'en' ? 'yesterday' : 'ayer';
  if (diffDays < 7) {
    if (lang === 'ja') return `${diffDays}日前`;
    if (lang === 'en') return `${diffDays} days ago`;
    return `hace ${diffDays} días`;
  }
  if (diffDays < 30) {
    const w = Math.floor(diffDays / 7);
    if (lang === 'ja') return `${w}週間前`;
    if (lang === 'en') return `${w} week${w > 1 ? 's' : ''} ago`;
    return `hace ${w} semana${w > 1 ? 's' : ''}`;
  }
  if (lang === 'ja') return `${date.getMonth() + 1}月${date.getDate()}日`;
  if (lang === 'en') {
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return `${months[date.getMonth()]} ${date.getDate()}`;
  }
  const months = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
  return `el ${date.getDate()} de ${months[date.getMonth()]}`;
}

// ── Pagination ────────────────────────────────────────────────────────────────

function Paginator({ page, total, perPage, onPage }: { page: number; total: number; perPage: number; onPage: (p: number) => void }) {
  const maxPage = Math.max(1, Math.ceil(total / perPage));
  if (maxPage <= 1) return null;

  const pages: (number | '...')[] = [];
  if (maxPage <= 7) {
    for (let i = 1; i <= maxPage; i++) pages.push(i);
  } else {
    pages.push(1);
    if (page > 3) pages.push('...');
    for (let i = Math.max(2, page - 1); i <= Math.min(maxPage - 1, page + 1); i++) pages.push(i);
    if (page < maxPage - 2) pages.push('...');
    pages.push(maxPage);
  }

  return (
    <div className={styles.pagination}>
      <button className={styles.pageBtn} disabled={page <= 1} onClick={() => onPage(page - 1)}>{'<'}</button>
      {pages.map((p, i) =>
        p === '...'
          ? <span key={`d${i}`} className={styles.pageDots}>…</span>
          : <button
              key={p}
              className={`${styles.pageBtn} ${p === page ? styles.pageBtnActive : ''}`}
              onClick={() => onPage(p as number)}
            >{p}</button>
      )}
      <button className={styles.pageBtn} disabled={page >= maxPage} onClick={() => onPage(page + 1)}>{'>'}</button>
    </div>
  );
}

// ── Modals ────────────────────────────────────────────────────────────────────

function InfoModal({ text, onClose }: { text: string; onClose: () => void }) {
  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.modalBody}>{text}</div>
        <div className={styles.modalActions}>
          <button className={styles.modalCancelBtn} onClick={onClose}>OK</button>
        </div>
      </div>
    </div>
  );
}

function ConfirmModal({ text, confirmLabel, cancelLabel, onConfirm, onCancel }: {
  text: string; confirmLabel: string; cancelLabel: string;
  onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.modalBody}>{text}</div>
        <div className={styles.modalActions}>
          <button className={styles.modalCancelBtn} onClick={onCancel}>{cancelLabel}</button>
          <button className={styles.modalConfirmBtn} onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}

// ── ConfidenceBar ─────────────────────────────────────────────────────────────

function ConfidenceBar({ value, label }: { value: number; label: string }) {
  const color = confidenceColor(value);
  return (
    <div className={styles.confidenceRow}>
      <span className={styles.confidencePct}>{label}</span>
      <div className={styles.confidenceBar}>
        <div className={styles.confidenceFill} style={{ width: `${value * 100}%`, background: color }} />
      </div>
      <span className={styles.confidencePct}>{Math.round(value * 100)}%</span>
    </div>
  );
}

// ── Facts tab ─────────────────────────────────────────────────────────────────

function FactsTab({ tl }: { tl: typeof TRANSLATIONS['es']['memory']; uiLang: UiLang }) {
  const [data, setData] = useState<PagedResult<SemanticFactItem> | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [showInfo, setShowInfo] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const load = useCallback(async (p: number) => {
    setLoading(true);
    try {
      const res = await fetch(`/memory/semantic-facts?page=${p}&per_page=20`);
      if (res.ok) setData(await res.json());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(page); }, [page, load]);

  function toggleSelect(id: number) {
    setSelected((prev) => { const s = new Set(prev); s.has(id) ? s.delete(id) : s.add(id); return s; });
  }

  function selectAll() {
    if (!data) return;
    const allIds = data.items.map((i) => i.id);
    setSelected((prev) => allIds.every((id) => prev.has(id)) ? new Set() : new Set(allIds));
  }

  async function deleteSelected() {
    if (selected.size === 0) return;
    await fetch('/memory/semantic-facts/batch', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: [...selected] }),
    });
    setSelected(new Set());
    void load(page);
  }

  function stabilityClass(s: string) {
    if (s === 'stable') return styles.tagStable;
    if (s === 'volatile') return styles.tagVolatile;
    return styles.tagNormal;
  }

  function stabilityLabel(s: string) {
    if (s === 'stable') return tl.stabilityStable;
    if (s === 'volatile') return tl.stabilityVolatile;
    return tl.stabilityNormal;
  }

  function inferenceLabel(t: string) {
    if (t === 'explicit') return tl.inferenceExplicit;
    if (t === 'appraisal') return tl.inferenceAppraisal;
    return tl.inferenceInferred;
  }

  function inferenceClass(t: string) {
    return t === 'explicit' ? styles.tagExplicit : styles.tagInferred;
  }

  const allOnPageSelected = data ? data.items.length > 0 && data.items.every((i) => selected.has(i.id)) : false;

  return (
    <>
      <div className={styles.toolbar}>
        <button className={styles.selectAllBtn} onClick={selectAll}>
          {allOnPageSelected ? '☑' : '☐'} {tl.selectAll}
        </button>
        {selected.size > 0 && (
          <button className={styles.deleteBtn} onClick={() => setShowConfirm(true)}>
            {tl.deleteSelected} ({selected.size})
          </button>
        )}
      </div>
      <div className={styles.listWrapper}>
        {loading ? (
          <div className={styles.loading}>{tl.loading}</div>
        ) : !data || data.items.length === 0 ? (
          <div className={styles.emptyState}>{tl.empty}</div>
        ) : (
          data.items.map((fact) => (
            <div key={fact.id} className={`${styles.item} ${selected.has(fact.id) ? styles.itemSelected : ''}`}>
              <input type="checkbox" className={styles.checkbox} checked={selected.has(fact.id)} onChange={() => toggleSelect(fact.id)} />
              <div className={styles.itemBody}>
                <span className={styles.itemText}>{fact.proposition}</span>
                <ConfidenceBar value={fact.confidence} label={tl.confidenceLabel} />
                <div className={styles.itemMeta}>
                  <span className={`${styles.tag} ${stabilityClass(fact.stability)}`}>{stabilityLabel(fact.stability)}</span>
                  <span className={`${styles.tag} ${inferenceClass(fact.inference_type)}`}>{inferenceLabel(fact.inference_type)}</span>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
      {data && <Paginator page={page} total={data.total} perPage={20} onPage={(p) => { setPage(p); setSelected(new Set()); }} />}
      {showInfo && <InfoModal text={tl.infoFacts} onClose={() => setShowInfo(false)} />}
      {showConfirm && (
        <ConfirmModal
          text={tl.deleteConfirm}
          confirmLabel={tl.confirmYes}
          cancelLabel={tl.confirmCancel}
          onConfirm={async () => { setShowConfirm(false); await deleteSelected(); }}
          onCancel={() => setShowConfirm(false)}
        />
      )}
    </>
  );
}

// ── Episodes tab ──────────────────────────────────────────────────────────────

function EpisodesTab({ tl, uiLang }: { tl: typeof TRANSLATIONS['es']['memory']; uiLang: UiLang }) {
  const [data, setData] = useState<PagedResult<EpisodeItem> | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [showConfirm, setShowConfirm] = useState(false);

  const load = useCallback(async (p: number) => {
    setLoading(true);
    try {
      const res = await fetch(`/memory/episodes?page=${p}&per_page=20`);
      if (res.ok) setData(await res.json());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(page); }, [page, load]);

  function toggleSelect(id: number) {
    setSelected((prev) => { const s = new Set(prev); s.has(id) ? s.delete(id) : s.add(id); return s; });
  }

  function selectAll() {
    if (!data) return;
    const allIds = data.items.map((i) => i.id);
    setSelected((prev) => allIds.every((id) => prev.has(id)) ? new Set() : new Set(allIds));
  }

  async function deleteSelected() {
    if (selected.size === 0) return;
    await fetch('/memory/episodes/batch', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: [...selected] }),
    });
    setSelected(new Set());
    void load(page);
  }

  function importanceLabel(s: number) {
    if (s >= 0.75) return tl.importanceClave;
    if (s >= 0.50) return tl.importanceMid;
    return tl.importanceMenor;
  }

  function importanceClass(s: number) {
    if (s >= 0.75) return styles.importanceClave;
    if (s >= 0.50) return styles.importanceMid;
    return styles.importanceMenor;
  }

  const allOnPageSelected = data ? data.items.length > 0 && data.items.every((i) => selected.has(i.id)) : false;

  return (
    <>
      <div className={styles.toolbar}>
        <button className={styles.selectAllBtn} onClick={selectAll}>
          {allOnPageSelected ? '☑' : '☐'} {tl.selectAll}
        </button>
        {selected.size > 0 && (
          <button className={styles.deleteBtn} onClick={() => setShowConfirm(true)}>
            {tl.deleteSelected} ({selected.size})
          </button>
        )}
      </div>
      <div className={styles.listWrapper}>
        {loading ? (
          <div className={styles.loading}>{tl.loading}</div>
        ) : !data || data.items.length === 0 ? (
          <div className={styles.emptyState}>{tl.empty}</div>
        ) : (
          data.items.map((ep) => (
            <div key={ep.id} className={`${styles.item} ${selected.has(ep.id) ? styles.itemSelected : ''}`}>
              <input type="checkbox" className={styles.checkbox} checked={selected.has(ep.id)} onChange={() => toggleSelect(ep.id)} />
              <div className={styles.itemBody}>
                <span className={styles.itemText}>{ep.summary}</span>
                <div className={styles.itemMeta}>
                  <span className={`${styles.tag} ${importanceClass(ep.salience_total)}`}>{importanceLabel(ep.salience_total)}</span>
                  <span className={styles.tag}>{formatRelativeDate(ep.occurred_at, uiLang)}</span>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
      {data && <Paginator page={page} total={data.total} perPage={20} onPage={(p) => { setPage(p); setSelected(new Set()); }} />}
      {showConfirm && (
        <ConfirmModal
          text={tl.deleteConfirm}
          confirmLabel={tl.confirmYes}
          cancelLabel={tl.confirmCancel}
          onConfirm={async () => { setShowConfirm(false); await deleteSelected(); }}
          onCancel={() => setShowConfirm(false)}
        />
      )}
    </>
  );
}

// ── SelfBeliefs tab (admin only) ──────────────────────────────────────────────

function SelfBeliefsTab({ tl }: { tl: typeof TRANSLATIONS['es']['memory'] }) {
  const [data, setData] = useState<PagedResult<SelfBeliefItem> | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [showConfirm, setShowConfirm] = useState(false);

  const load = useCallback(async (p: number) => {
    setLoading(true);
    try {
      const res = await fetch(`/memory/self-beliefs?page=${p}&per_page=20`);
      if (res.ok) setData(await res.json());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(page); }, [page, load]);

  function toggleSelect(id: number) {
    setSelected((prev) => { const s = new Set(prev); s.has(id) ? s.delete(id) : s.add(id); return s; });
  }

  function selectAll() {
    if (!data) return;
    const allIds = data.items.map((i) => i.id);
    setSelected((prev) => allIds.every((id) => prev.has(id)) ? new Set() : new Set(allIds));
  }

  async function deleteSelected() {
    if (selected.size === 0) return;
    await fetch('/memory/self-beliefs/batch', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: [...selected] }),
    });
    setSelected(new Set());
    void load(page);
  }

  const allOnPageSelected = data ? data.items.length > 0 && data.items.every((i) => selected.has(i.id)) : false;

  return (
    <>
      <div className={styles.toolbar}>
        <button className={styles.selectAllBtn} onClick={selectAll}>
          {allOnPageSelected ? '☑' : '☐'} {tl.selectAll}
        </button>
        {selected.size > 0 && (
          <button className={styles.deleteBtn} onClick={() => setShowConfirm(true)}>
            {tl.deleteSelected} ({selected.size})
          </button>
        )}
      </div>
      <div className={styles.listWrapper}>
        {loading ? (
          <div className={styles.loading}>{tl.loading}</div>
        ) : !data || data.items.length === 0 ? (
          <div className={styles.emptyState}>{tl.empty}</div>
        ) : (
          data.items.map((b) => (
            <div key={b.id} className={`${styles.item} ${selected.has(b.id) ? styles.itemSelected : ''}`}>
              <input type="checkbox" className={styles.checkbox} checked={selected.has(b.id)} onChange={() => toggleSelect(b.id)} />
              <div className={styles.itemBody}>
                <span className={styles.itemText}>{b.proposition}</span>
                <ConfidenceBar value={b.confidence} label={tl.confidenceLabel} />
                <div className={styles.itemMeta}>
                  <span className={styles.tag}>{b.source}</span>
                  <span className={styles.tag}>+{b.reinforcement_count} / -{b.contradiction_count}</span>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
      {data && <Paginator page={page} total={data.total} perPage={20} onPage={(p) => { setPage(p); setSelected(new Set()); }} />}
      {showConfirm && (
        <ConfirmModal
          text={tl.deleteConfirm}
          confirmLabel={tl.confirmYes}
          cancelLabel={tl.confirmCancel}
          onConfirm={async () => { setShowConfirm(false); await deleteSelected(); }}
          onCancel={() => setShowConfirm(false)}
        />
      )}
    </>
  );
}

// ── Brain icon ────────────────────────────────────────────────────────────────

function BrainIconLarge() {
  return (
    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96-.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-1.66Z" />
      <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96-.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-1.66Z" />
    </svg>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

export function MemoryScreen({ role, uiLang = 'es' }: MemoryScreenProps) {
  const tl = TRANSLATIONS[uiLang].memory;
  const isGuest = role === 'guest';
  const isAdmin = role === 'admin';
  const [tab, setTab] = useState<MemoryTab>('facts');
  const [showInfo, setShowInfo] = useState(false);

  // Non-admin trying to access selfbeliefs tab → redirect to facts
  useEffect(() => {
    if (tab === 'selfbeliefs' && !isAdmin) setTab('facts');
  }, [tab, isAdmin]);

  const infoText = tab === 'facts' ? tl.infoFacts
    : tab === 'episodes' ? tl.infoEpisodes
    : tl.infoSelfBeliefs;

  return (
    <div className={styles.screen}>
      <div className={styles.header}>
        <div className={styles.headerText}>
          <span className={styles.titleEs}>{tl.title}</span>
          <span className={styles.titleJp}>記憶</span>
        </div>
        {!isGuest && (
          <button className={styles.infoBtn} onClick={() => setShowInfo(true)}>ⓘ</button>
        )}
      </div>

      {isGuest ? (
        <div className={styles.guestBanner}>
          <div className={styles.guestIcon}><BrainIconLarge /></div>
          <p className={styles.guestMessage}>{tl.guestMessage}</p>
        </div>
      ) : (
        <>
          <div className={styles.viewTabs}>
            <button
              className={`${styles.viewTab} ${tab === 'facts' ? styles.viewTabActive : ''}`}
              onClick={() => setTab('facts')}
            >
              {tl.tabFacts}
            </button>
            <button
              className={`${styles.viewTab} ${tab === 'episodes' ? styles.viewTabActive : ''}`}
              onClick={() => setTab('episodes')}
            >
              {tl.tabEpisodes}
            </button>
            {isAdmin && (
              <button
                className={`${styles.viewTab} ${tab === 'selfbeliefs' ? styles.viewTabActive : ''}`}
                onClick={() => setTab('selfbeliefs')}
              >
                {tl.tabSelfBeliefs}
              </button>
            )}
          </div>

          {tab === 'facts' && <FactsTab key="facts" tl={tl} uiLang={uiLang} />}
          {tab === 'episodes' && <EpisodesTab key="episodes" tl={tl} uiLang={uiLang} />}
          {tab === 'selfbeliefs' && isAdmin && <SelfBeliefsTab key="selfbeliefs" tl={tl} />}
        </>
      )}

      {showInfo && <InfoModal text={infoText} onClose={() => setShowInfo(false)} />}
    </div>
  );
}
