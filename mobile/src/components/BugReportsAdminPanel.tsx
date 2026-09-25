import { useState, useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import styles from './BugReportsAdminPanel.module.css';

interface ReportListItem {
  id: number;
  created_at: string;
  severity: string;
  role: string | null;
  has_attachments: boolean;
}

interface AttachmentItem {
  filename: string;
  url: string;
  mime_type: string | null;
}

interface ReportDetail {
  id: number;
  created_at: string;
  severity: string;
  observations: string | null;
  session_id: string | null;
  user_id: number | null;
  role: string | null;
  user_agent: string | null;
  git_commit: string | null;
  attachments: AttachmentItem[];
}

const SEVERITY_COLORS: Record<string, string> = {
  baja: '#4caf50',
  media: '#ff9800',
  alta: '#f44336',
  'crítica': '#b71c1c',
};

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('es-ES', {
      day: '2-digit', month: '2-digit', year: '2-digit',
      hour: '2-digit', minute: '2-digit',
    });
  } catch { return iso; }
}

interface DetailModalProps {
  report: ReportDetail;
  onClose: () => void;
  onDownload: () => void;
  onDelete: () => void;
}

function DetailModal({ report, onClose, onDownload, onDelete }: DetailModalProps) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await fetch(`/bug-reports/${report.id}`, { method: 'DELETE', credentials: 'include' });
      onDelete();
    } catch { /* silent */ } finally {
      setDeleting(false);
    }
  };

  return (
    <motion.div
      className={styles.backdrop}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={onClose}
    >
      <motion.div
        className={styles.detailModal}
        initial={{ opacity: 0, scale: 0.92, y: 24 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.92, y: 24 }}
        transition={{ duration: 0.2 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.detailHeader}>
          <h3 className={styles.detailTitle}>
            Reporte #{report.id}
            <span className={styles.badge} style={{ color: SEVERITY_COLORS[report.severity] ?? 'inherit' }}>
              {report.severity}
            </span>
          </h3>
          <div className={styles.detailHeaderActions}>
            <button className={styles.downloadBtn} onClick={onDownload}>↓ JSON</button>
            <button className={styles.closeX} onClick={onClose} aria-label="Cerrar">✕</button>
          </div>
        </div>

        <div className={styles.detailBody}>
          <div className={styles.metaGrid}>
            <span className={styles.metaKey}>Fecha</span>
            <span className={styles.metaVal}>{fmtDate(report.created_at)}</span>
            <span className={styles.metaKey}>Rol</span>
            <span className={styles.metaVal}>{report.role ?? '—'}</span>
            <span className={styles.metaKey}>User ID</span>
            <span className={styles.metaVal}>{report.user_id ?? 'guest'}</span>
            <span className={styles.metaKey}>Session</span>
            <span className={styles.metaVal}>{report.session_id ?? '—'}</span>
            <span className={styles.metaKey}>Commit</span>
            <span className={styles.metaVal}>{report.git_commit ?? '—'}</span>
            <span className={styles.metaKey}>User-Agent</span>
            <span className={styles.metaVal}>{report.user_agent ?? '—'}</span>
          </div>

          {report.observations && (
            <div className={styles.obsBlock}>
              <p className={styles.obsLabel}>Observaciones</p>
              <p className={styles.obsText}>{report.observations}</p>
            </div>
          )}

          {report.attachments.length > 0 && (
            <div className={styles.attachsBlock}>
              <p className={styles.obsLabel}>Adjuntos</p>
              <div className={styles.thumbGrid}>
                {report.attachments.map((a) => (
                  a.mime_type?.startsWith('image/') ? (
                    <img
                      key={a.filename}
                      src={a.url}
                      alt={a.filename}
                      className={styles.thumb}
                    />
                  ) : (
                    <span key={a.filename} className={styles.attachName}>{a.filename}</span>
                  )
                ))}
              </div>
            </div>
          )}
        </div>

        {!confirmDelete ? (
          <div className={styles.footer}>
            <button className={styles.btnDanger} onClick={() => setConfirmDelete(true)}>
              Eliminar reporte
            </button>
            <button className={styles.closeBtn} onClick={onClose}>Cerrar</button>
          </div>
        ) : (
          <div className={styles.confirmBar}>
            <p className={styles.confirmText}>
              ¿Eliminar este reporte? Esta acción no se puede deshacer.
            </p>
            <div className={styles.confirmActions}>
              <button className={styles.closeBtn} onClick={() => setConfirmDelete(false)} disabled={deleting}>
                Cancelar
              </button>
              <button className={styles.btnDanger} onClick={() => void handleDelete()} disabled={deleting}>
                {deleting ? 'Eliminando…' : 'Eliminar'}
              </button>
            </div>
          </div>
        )}
      </motion.div>
    </motion.div>
  );
}

interface BugReportsAdminPanelProps {
  open: boolean;
  onClose: () => void;
}

export function BugReportsAdminPanel({ open, onClose }: BugReportsAdminPanelProps) {
  const [reports, setReports] = useState<ReportListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<ReportDetail | null>(null);
  const [checkedIds, setCheckedIds] = useState<Set<number>>(new Set());
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const reloadReports = async () => {
    setLoading(true);
    setError('');
    try {
      const r = await fetch('/bug-reports', { credentials: 'include' });
      const data = await r.json();
      setReports(data.reports ?? []);
    } catch {
      setError('Error al cargar reportes.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    setCheckedIds(new Set());
    setConfirmBulkDelete(false);
    void reloadReports();
  }, [open]);

  const toggleCheck = (id: number) => {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const handleBulkDelete = async () => {
    if (checkedIds.size === 0) return;
    setDeleting(true);
    try {
      await fetch('/bug-reports', {
        method: 'DELETE',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: [...checkedIds] }),
      });
      setCheckedIds(new Set());
      setConfirmBulkDelete(false);
      await reloadReports();
    } catch { /* silent */ } finally {
      setDeleting(false);
    }
  };

  const handleDetailDeleted = async () => {
    setSelected(null);
    await reloadReports();
  };

  const handleRowClick = async (id: number) => {
    try {
      const resp = await fetch(`/bug-reports/${id}`, { credentials: 'include' });
      const data: ReportDetail = await resp.json();
      setSelected(data);
    } catch { /* silent */ }
  };

  const handleDownload = async (id: number) => {
    try {
      const resp = await fetch(`/bug-reports/${id}/download`, { credentials: 'include' });
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `bug-report-${id}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { /* silent */ }
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className={styles.backdrop}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className={styles.listModal}
            initial={{ opacity: 0, scale: 0.92, y: 24 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.92, y: 24 }}
            transition={{ duration: 0.2 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={styles.listHeader}>
              <h2 className={styles.listTitle}>Bug Reports</h2>
              <button className={styles.closeX} onClick={onClose} aria-label="Cerrar">✕</button>
            </div>

            {loading && <p className={styles.hint}>Cargando…</p>}
            {error && <p className={styles.errorMsg}>{error}</p>}

            {!loading && !error && reports.length === 0 && (
              <p className={styles.hint}>No hay reportes aún.</p>
            )}

            {!loading && reports.length > 0 && (
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th className={styles.checkCell}></th>
                      <th>Fecha</th>
                      <th>Severidad</th>
                      <th>Rol</th>
                      <th>Adj</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {reports.map((r) => (
                      <tr
                        key={r.id}
                        className={`${styles.row}${checkedIds.has(r.id) ? ` ${styles.rowChecked}` : ''}`}
                        onClick={() => void handleRowClick(r.id)}
                      >
                        <td
                          className={styles.checkCell}
                          onClick={(e) => { e.stopPropagation(); toggleCheck(r.id); }}
                        >
                          <input
                            type="checkbox"
                            className={styles.checkbox}
                            checked={checkedIds.has(r.id)}
                            onChange={() => toggleCheck(r.id)}
                          />
                        </td>
                        <td className={styles.dateCell}>{fmtDate(r.created_at)}</td>
                        <td>
                          <span
                            className={styles.sevBadge}
                            style={{ color: SEVERITY_COLORS[r.severity] ?? 'inherit' }}
                          >
                            {r.severity}
                          </span>
                        </td>
                        <td className={styles.roleCell}>{r.role ?? '—'}</td>
                        <td className={styles.adjCell}>{r.has_attachments ? '📎' : ''}</td>
                        <td className={styles.dlCell}>
                          <button
                            className={styles.dlBtn}
                            onClick={(e) => { e.stopPropagation(); void handleDownload(r.id); }}
                            title="Descargar JSON"
                          >
                            ↓
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {!confirmBulkDelete ? (
              <div className={styles.footer}>
                <button className={styles.closeBtn} onClick={onClose}>Cerrar</button>
                {checkedIds.size > 0 && (
                  <button
                    className={styles.btnDanger}
                    onClick={() => setConfirmBulkDelete(true)}
                  >
                    Eliminar seleccionados ({checkedIds.size})
                  </button>
                )}
              </div>
            ) : (
              <div className={styles.confirmBar}>
                <p className={styles.confirmText}>
                  ¿Eliminar {checkedIds.size} reporte(s) seleccionado(s)? Esta acción no se puede deshacer.
                </p>
                <div className={styles.confirmActions}>
                  <button
                    className={styles.closeBtn}
                    onClick={() => setConfirmBulkDelete(false)}
                    disabled={deleting}
                  >
                    Cancelar
                  </button>
                  <button
                    className={styles.btnDanger}
                    onClick={() => void handleBulkDelete()}
                    disabled={deleting}
                  >
                    {deleting ? 'Eliminando…' : 'Eliminar'}
                  </button>
                </div>
              </div>
            )}
          </motion.div>

          <AnimatePresence>
            {selected && (
              <DetailModal
                report={selected}
                onClose={() => setSelected(null)}
                onDownload={() => void handleDownload(selected.id)}
                onDelete={() => void handleDetailDeleted()}
              />
            )}
          </AnimatePresence>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
