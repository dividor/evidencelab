import React, { useState } from 'react';
import type { TestCase } from '../../../types/testing';
import { prettyJson } from './testingFormat';

export interface CaseDraft {
  query: string;
  extraJson: string; // JSON object holding filters/params (everything but `query`)
  tags: string; // comma separated
  notes: string;
}

export interface CasePayload {
  input: Record<string, unknown>;
  tags?: string[];
  notes?: string;
}

/* ------------------------------------------------------------------ */
/*  Draft <-> case conversion                                         */
/* ------------------------------------------------------------------ */

export const emptyDraft = (): CaseDraft => ({
  query: '',
  extraJson: '',
  tags: '',
  notes: '',
});

export const caseToDraft = (testCase: TestCase): CaseDraft => {
  const input = testCase.input || {};
  const { query, ...rest } = input as { query?: unknown; [k: string]: unknown };
  return {
    query: typeof query === 'string' ? query : '',
    extraJson: Object.keys(rest).length > 0 ? prettyJson(rest) : '',
    tags: (testCase.tags || []).join(', '),
    notes: testCase.notes || '',
  };
};

export const draftToPayload = (draft: CaseDraft): CasePayload => {
  let extra: Record<string, unknown> = {};
  if (draft.extraJson.trim()) {
    const parsed = JSON.parse(draft.extraJson);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      extra = parsed as Record<string, unknown>;
    } else {
      throw new Error('Filters/params JSON must be an object');
    }
  }
  const tags = draft.tags
    .split(',')
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
  return {
    input: { query: draft.query, ...extra },
    tags: tags.length > 0 ? tags : undefined,
    notes: draft.notes.trim() || undefined,
  };
};

/* ------------------------------------------------------------------ */
/*  Editor form (inputs only — assertions live on experiments)        */
/* ------------------------------------------------------------------ */

interface CaseEditorProps {
  initial: CaseDraft;
  saving: boolean;
  submitLabel: string;
  onSubmit: (payload: CasePayload) => void;
  onCancel: () => void;
}

const CaseEditor: React.FC<CaseEditorProps> = ({
  initial,
  saving,
  submitLabel,
  onSubmit,
  onCancel,
}) => {
  const [draft, setDraft] = useState<CaseDraft>(initial);
  const [localError, setLocalError] = useState('');

  const update = (patch: Partial<CaseDraft>) => setDraft((d) => ({ ...d, ...patch }));

  const handleSubmit = () => {
    setLocalError('');
    try {
      onSubmit(draftToPayload(draft));
    } catch (err: any) {
      setLocalError(err.message || 'Invalid JSON in filters/params');
    }
  };

  return (
    <div className="testing-case-editor">
      {localError && <div className="auth-error">{localError}</div>}

      <div className="form-group">
        <label htmlFor="case-query">Query</label>
        <input
          id="case-query"
          type="text"
          value={draft.query}
          onChange={(e) => update({ query: e.target.value })}
          placeholder="Search query / question"
        />
      </div>

      <div className="form-group">
        <label htmlFor="case-extra">Filters / params (JSON object, optional)</label>
        <textarea
          id="case-extra"
          className="testing-json-textarea"
          value={draft.extraJson}
          onChange={(e) => update({ extraJson: e.target.value })}
          placeholder={'{\n  "filters": {},\n  "params": {}\n}'}
          rows={5}
        />
      </div>

      <div className="form-group">
        <label htmlFor="case-tags">Tags (comma separated)</label>
        <input
          id="case-tags"
          type="text"
          value={draft.tags}
          onChange={(e) => update({ tags: e.target.value })}
          placeholder="regression, smoke"
        />
      </div>

      <div className="form-group">
        <label htmlFor="case-notes">Notes</label>
        <textarea
          id="case-notes"
          className="testing-json-textarea"
          value={draft.notes}
          onChange={(e) => update({ notes: e.target.value })}
          rows={2}
        />
      </div>

      <div className="testing-case-editor-actions">
        <button type="button" className="btn-sm btn-cancel" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <button
          type="button"
          className="btn-sm btn-primary"
          onClick={handleSubmit}
          disabled={saving}
        >
          {saving ? 'Saving...' : submitLabel}
        </button>
      </div>
    </div>
  );
};

export default CaseEditor;
