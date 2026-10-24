import React, { useState } from 'react';
import { progressText } from './SummaryEditor';
import { SummarySettingsPanel } from './SummarySettingsPanel';
import type { SummarySettings } from './summarySettings';
import { BulkItem, BulkState, useBulkSummaries } from './useBulkSummaries';
import type { SummaryAdmin } from './useSummaryAdmin';

interface BulkSummaryModalProps {
  isOpen: boolean;
  onClose: () => void;
  admin: SummaryAdmin;
  documents: Array<{ id: string; title: string }>;
  /** Called once a run ends, e.g. to clear the selection. */
  onFinished?: () => void;
}

const STATE_LABELS: Record<BulkState, string> = {
  waiting: 'Waiting',
  generating: 'Generating',
  saved: 'Saved',
  failed: 'Failed',
  stopped: 'Not changed',
};

const statusText = (item: BulkItem): string => {
  if (item.state === 'generating') return progressText(item.progress ?? null);
  if (item.state === 'failed') return `Failed: ${item.message}`;
  return STATE_LABELS[item.state];
};

const BulkProgress: React.FC<{ items: BulkItem[] }> = ({ items }) => {
  const count = (state: BulkState) => items.filter((i) => i.state === state).length;
  return (
    <>
      <p className="doc-summary-note" role="status">
        {count('saved')} saved · {count('failed')} failed · {count('waiting') + count('generating')} to go
        {count('stopped') ? ` · ${count('stopped')} not changed` : ''}
      </p>
      <ul className="doc-summary-bulk-list">
        {items.map((item) => (
          <li key={item.id} className={`doc-summary-bulk-item doc-summary-bulk-${item.state}`}>
            <span className="doc-summary-bulk-title">{item.title}</span>
            <span className="doc-summary-bulk-status">{statusText(item)}</span>
          </li>
        ))}
      </ul>
    </>
  );
};

/** Regenerate and save the summaries of several documents (administrators). */
export const BulkSummaryModal: React.FC<BulkSummaryModalProps> = ({
  isOpen,
  onClose,
  admin,
  documents,
  onFinished,
}) => {
  const [settings, setSettings] = useState<SummarySettings>(admin.defaults);
  const bulk = useBulkSummaries(admin);
  const started = bulk.items.length > 0;

  if (!isOpen) return null;

  const close = () => {
    if (bulk.running) return;
    if (started) onFinished?.();
    bulk.reset();
    onClose();
  };

  return (
    <div className="preview-overlay" onClick={close}>
      <div className="modal-panel" role="dialog" aria-label="Regenerate summaries" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Regenerate {documents.length === 1 ? '1 summary' : `${documents.length} summaries`}</h2>
          <div className="modal-header-actions">
            <button onClick={close} className="modal-close" disabled={bulk.running} aria-label="Close">
              ×
            </button>
          </div>
        </div>
        <div className="modal-body">
          {started ? (
            <BulkProgress items={bulk.items} />
          ) : (
            <>
              <p className="doc-summary-note">
                Each summary is generated and saved straight away, replacing the current one for everyone. Keep
                this page open until it finishes.
              </p>
              <SummarySettingsPanel
                settings={settings}
                onChange={setSettings}
                allSectionTypes={admin.allSectionTypes}
                defaultPrompt={admin.defaults.prompt}
              />
            </>
          )}
          <div className="doc-summary-actions">
            {bulk.running && (
              <button type="button" className="btn-sm" onClick={bulk.stop}>Stop</button>
            )}
            {!bulk.running && (
              <button type="button" className="btn-sm" onClick={close}>{started ? 'Close' : 'Cancel'}</button>
            )}
            {!started && (
              <button
                type="button"
                className="btn-sm btn-primary"
                disabled={!settings.prompt.trim() || !settings.sectionTypes.length}
                onClick={() => bulk.start(documents, settings)}
              >
                Regenerate and save
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
