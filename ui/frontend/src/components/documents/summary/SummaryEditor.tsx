import React, { useEffect, useRef, useState } from 'react';
import {
  GeneratedSummary,
  SummaryProgress,
  fetchDocumentSections,
  generateDocumentSummary,
  saveDocumentSummary,
} from './documentSummaryApi';
import { SummarySettingsPanel } from './SummarySettingsPanel';
import {
  DocumentSections,
  SUMMARY_MODE_LABELS,
  SaveMethod,
  SummarySettings,
} from './summarySettings';
import type { SummaryAdmin } from './useSummaryAdmin';

type EditorView = 'view' | 'edit' | 'regenerate';

interface SummaryEditorProps {
  admin: SummaryAdmin;
  docId: string;
  summary: string;
  /** The read-only summary, shown when not editing. */
  renderSummary: () => React.ReactNode;
}

export const progressText = (progress: SummaryProgress | null): string => {
  if (!progress) return 'Starting…';
  if (progress.stage === 'map') return `Summarising part ${progress.done} of ${progress.total}…`;
  if (progress.stage === 'reduce') return 'Combining the parts…';
  return 'Summarising…';
};

const errorMessage = (err: unknown, fallback: string): string => {
  const detail = (err as any)?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  return err instanceof Error && err.message ? err.message : fallback;
};

const RegeneratePanel: React.FC<{
  admin: SummaryAdmin;
  docId: string;
  onGenerated: (generated: GeneratedSummary) => void;
  onCancel: () => void;
}> = ({ admin, docId, onGenerated, onCancel }) => {
  const [settings, setSettings] = useState<SummarySettings>(admin.defaults);
  const [sections, setSections] = useState<DocumentSections | null>(null);
  const [progress, setProgress] = useState<SummaryProgress | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    fetchDocumentSections(admin.dataSource, docId, admin.model.max_tokens)
      .then(setSections)
      .catch((err) => setError(errorMessage(err, 'The document sections could not be loaded.')));
    return () => abortRef.current?.abort();
  }, [admin.dataSource, admin.model.max_tokens, docId]);

  const generate = async () => {
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setError(null);
    setProgress(null);
    try {
      const generated = await generateDocumentSummary({
        dataSource: admin.dataSource,
        docId,
        settings,
        model: admin.model,
        onProgress: setProgress,
        signal: controller.signal,
      });
      onGenerated(generated);
    } catch (err) {
      if (!controller.signal.aborted) setError(errorMessage(err, 'The summary could not be generated.'));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="doc-summary-regenerate">
      <SummarySettingsPanel
        settings={settings}
        onChange={setSettings}
        allSectionTypes={admin.allSectionTypes}
        defaultPrompt={admin.defaults.prompt}
        sections={sections}
        disabled={running}
      />
      {error && <p className="doc-summary-error" role="alert">{error}</p>}
      <div className="doc-summary-actions">
        {running ? (
          <>
            <span className="doc-summary-progress" role="status">{progressText(progress)}</span>
            <button type="button" className="btn-sm" onClick={() => abortRef.current?.abort()}>
              Stop
            </button>
          </>
        ) : (
          <>
            <button type="button" className="btn-sm" onClick={onCancel}>Cancel</button>
            <button
              type="button"
              className="btn-sm btn-primary"
              disabled={!settings.prompt.trim() || (sections?.has_section_types !== false && !settings.sectionTypes.length)}
              onClick={generate}
            >
              Generate
            </button>
          </>
        )}
      </div>
    </div>
  );
};

/** Edit, regenerate and save a document's summary (administrators). */
export const SummaryEditor: React.FC<SummaryEditorProps> = ({ admin, docId, summary, renderSummary }) => {
  const [view, setView] = useState<EditorView>('view');
  const [draft, setDraft] = useState(summary);
  const [generated, setGenerated] = useState<GeneratedSummary | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startEdit = () => {
    setDraft(summary);
    setGenerated(null);
    setError(null);
    setView('edit');
  };

  const onGenerated = (result: GeneratedSummary) => {
    setGenerated(result);
    setDraft(result.summary);
    setView('edit');
  };

  const save = async () => {
    const method: SaveMethod = generated && draft === generated.summary ? generated.method : 'ui_edited';
    setSaving(true);
    setError(null);
    try {
      const saved = await saveDocumentSummary(admin.dataSource, docId, draft, method);
      admin.onSaved(saved);
      setGenerated(null);
      setView('view');
    } catch (err) {
      setError(errorMessage(err, 'The summary could not be saved.'));
    } finally {
      setSaving(false);
    }
  };

  if (view === 'regenerate') {
    return <RegeneratePanel admin={admin} docId={docId} onGenerated={onGenerated} onCancel={() => setView('view')} />;
  }
  if (view === 'edit') {
    return (
      <div className="doc-summary-edit">
        {generated && (
          <p className="doc-summary-note" role="status">
            New summary written with {SUMMARY_MODE_LABELS[generated.mode]} ({generated.calls}{' '}
            {generated.calls === 1 ? 'model call' : 'model calls'}). Review it, then save; nothing is saved yet.
          </p>
        )}
        {generated && summary && (
          <details className="doc-summary-current">
            <summary>Current summary</summary>
            {renderSummary()}
          </details>
        )}
        <textarea
          className="doc-summary-textarea"
          aria-label="Summary text"
          value={draft}
          rows={18}
          onChange={(e) => setDraft(e.target.value)}
        />
        {error && <p className="doc-summary-error" role="alert">{error}</p>}
        <p className="doc-summary-note">
          Saving replaces the summary for everyone. Document taxonomy tags were built from the previous summary
          and are not updated.
        </p>
        <div className="doc-summary-actions">
          <button type="button" className="btn-sm" disabled={saving} onClick={() => setView('view')}>
            Cancel
          </button>
          <button type="button" className="btn-sm btn-primary" disabled={saving || !draft.trim()} onClick={save}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    );
  }
  return (
    <>
      <div className="doc-summary-toolbar">
        <button type="button" className="btn-sm" onClick={startEdit}>Edit</button>
        <button type="button" className="btn-sm btn-primary" onClick={() => setView('regenerate')}>
          Regenerate with AI
        </button>
      </div>
      {summary ? renderSummary() : <p className="doc-summary-note">This document has no summary yet.</p>}
    </>
  );
};
