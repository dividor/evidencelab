import React, { useCallback, useEffect, useState } from 'react';
import { BriefDiff } from './BriefDiff';
import { formatWhen } from './BriefSectionAudit';
import { BriefVersionItem, BriefVersionRead, BriefVersionSection } from './briefTypes';
import { getBriefVersion, listBriefVersions } from './briefVersionsApi';

// The whole-brief version Log: every change to the brief (the API writes a
// version with each one), and any version shown as the whole brief with
// tracked changes against the version before it. The owner can restore the
// brief to it; the restore is itself a new version.

const when = (iso: string): string => formatWhen(Date.parse(iso));

const errorText = (e: unknown, fallback: string): string => {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  return e instanceof Error ? e.message : fallback;
};

const Title: React.FC<{ title: string }> = ({ title }) => <>{title || 'Untitled'}</>;

// A section's heading: renamed shows the old title struck out and the new one
// added; an added or removed section's whole heading is marked.
const VersionSectionTitle: React.FC<{ row: BriefVersionSection }> = ({ row }) => {
  const renamed = row.change === 'changed' && row.beforeTitle != null && row.beforeTitle !== row.title;
  let heading: React.ReactNode = <Title title={row.title} />;
  if (renamed) {
    heading = (
      <>
        <del className="brief-diff-del">
          <Title title={row.beforeTitle || ''} />
        </del>{' '}
        <ins className="brief-diff-add">
          <Title title={row.title} />
        </ins>
      </>
    );
  } else if (row.change === 'added') {
    heading = (
      <ins className="brief-diff-add">
        <Title title={row.title} />
      </ins>
    );
  } else if (row.change === 'removed') {
    heading = (
      <del className="brief-diff-del">
        <Title title={row.title} />
      </del>
    );
  }
  return (
    <h3 className="brief-version-section-title">
      {heading}
      {row.change !== 'unchanged' && (
        <span className={`brief-version-tag brief-version-tag-${row.change}`}>{row.change}</span>
      )}
    </h3>
  );
};

// The text a section had before and after this version: an added section had
// none before, a removed one has none after, an unchanged one reads as it is.
const sectionTexts = (row: BriefVersionSection): [string, string] => {
  const after = row.change === 'removed' ? '' : row.after || '';
  if (row.change === 'unchanged') return [after, after];
  return [row.change === 'added' ? '' : row.before || '', after];
};

// One section of the version: unchanged text as it reads, a changed section
// as tracked changes, an added section all green, a removed one struck out.
// The first version has nothing before it, so it reads as plain text.
const VersionSection: React.FC<{ row: BriefVersionSection; first: boolean }> = ({ row, first }) => {
  const [before, after] = first ? [row.after || '', row.after || ''] : sectionTexts(row);
  const changeClass = first ? '' : ` brief-version-section-${row.change}`;
  const subClass = row.level === 2 ? ' brief-version-section-sub' : '';
  return (
    <section className={`brief-version-section${changeClass}${subClass}`}>
      {first ? (
        <h3 className="brief-version-section-title">
          <Title title={row.title} />
        </h3>
      ) : (
        <VersionSectionTitle row={row} />
      )}
      {before || after ? (
        <BriefDiff oldText={before} newText={after} />
      ) : (
        <div className="brief-version-empty">No text yet.</div>
      )}
    </section>
  );
};

const VersionDetail: React.FC<{
  detail: BriefVersionRead;
  onRestore: () => void;
  restoring: boolean;
}> = ({ detail, onRestore, restoring }) => (
  <div className="brief-version-detail">
    <div className="brief-version-detail-head">
      <div>
        <div className="brief-version-detail-title">
          Version {detail.number}
          {detail.is_current && <span className="brief-version-current">current</span>}
        </div>
        <div className="brief-modal-sub">
          {detail.summary} · {detail.author_name || 'Unknown'} · {when(detail.updated_at)}
        </div>
        <div className="brief-modal-sub">
          {detail.previous_number
            ? `Compared with version ${detail.previous_number}`
            : 'The first version recorded, shown as it was'}
        </div>
      </div>
      {detail.can_restore && (
        <button className="brief-btn brief-btn-primary" onClick={onRestore} disabled={restoring}>
          {restoring ? 'Restoring…' : 'Restore whole brief to this version'}
        </button>
      )}
    </div>
    {detail.settings.length > 0 && (
      <ul className="brief-version-settings">
        {detail.settings.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ul>
    )}
    <h2 className="brief-version-brief-title">{detail.title}</h2>
    {detail.sections.length === 0 ? (
      <div className="brief-version-empty">No headings in this version.</div>
    ) : (
      detail.sections.map((row) => (
        <VersionSection
          key={`${row.change}-${row.id}`}
          row={row}
          first={detail.previous_number == null}
        />
      ))
    )}
  </div>
);

interface Props {
  briefId: string | null;
  onRestore: (number: number) => Promise<void>;
  onClose: () => void;
}

export const BriefVersionsModal: React.FC<Props> = ({ briefId, onRestore, onClose }) => {
  const [versions, setVersions] = useState<BriefVersionItem[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<BriefVersionRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(false);

  const loadList = useCallback(async () => {
    if (!briefId) return;
    try {
      const list = await listBriefVersions(briefId);
      setVersions(list);
      setSelected((current) => current ?? (list[0]?.number ?? null));
    } catch (e) {
      setError(errorText(e, 'Could not load the versions.'));
    }
  }, [briefId]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    if (!briefId || selected == null) return undefined;
    let cancelled = false;
    setDetail(null);
    getBriefVersion(briefId, selected)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e) => {
        if (!cancelled) setError(errorText(e, 'Could not load the version.'));
      });
    return () => {
      cancelled = true;
    };
  }, [briefId, selected]);

  const restore = async () => {
    if (selected == null) return;
    setRestoring(true);
    await onRestore(selected);
    setRestoring(false);
    onClose();
  };

  return (
    <div className="brief-modal-overlay" onClick={onClose}>
      <div className="brief-modal brief-versions-modal" onClick={(e) => e.stopPropagation()}>
        <div className="brief-modal-head">
          <div>
            <div className="brief-modal-title">Document History</div>
            <div className="brief-modal-sub">
              Every change to this brief. Open a version to see what changed from the one before.
            </div>
          </div>
          <button className="brief-modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        {!briefId ? (
          <div className="brief-modal-empty">
            The brief has not been saved yet; its log starts with the first save.
          </div>
        ) : error ? (
          <div className="brief-modal-empty brief-version-error">{error}</div>
        ) : versions === null ? (
          <div className="brief-modal-empty">Loading…</div>
        ) : versions.length === 0 ? (
          <div className="brief-modal-empty">
            No changes recorded yet. Every change from now on is listed here.
          </div>
        ) : (
          <div className="brief-versions-body">
            <div className="brief-versions-list" role="listbox" aria-label="Versions">
              {versions.map((v) => (
                <button
                  key={v.number}
                  type="button"
                  role="option"
                  aria-selected={v.number === selected}
                  className={`brief-versions-row${v.number === selected ? ' is-selected' : ''}`}
                  onClick={() => setSelected(v.number)}
                >
                  <span className="brief-versions-row-top">
                    <span className="brief-versions-row-number">v{v.number}</span>
                    {v.is_current && <span className="brief-version-current">current</span>}
                    <span className="brief-versions-row-when">{when(v.updated_at)}</span>
                  </span>
                  <span className="brief-versions-row-summary">{v.summary}</span>
                  <span className="brief-versions-row-who">{v.author_name || 'Unknown'}</span>
                </button>
              ))}
            </div>
            <div className="brief-versions-pane">
              {detail ? (
                <VersionDetail detail={detail} onRestore={restore} restoring={restoring} />
              ) : (
                <div className="brief-modal-empty">Loading…</div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
