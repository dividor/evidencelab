import React, { useState } from 'react';
import type { Assertion, TestCapability, TestCase } from '../../../types/testing';
import AssertionBuilder from './AssertionBuilder';
import { prettyJson } from './testingFormat';

export interface CaseDraft {
  query: string;
  extraJson: string; // JSON object holding filters/params (everything but `query`)
  expectations: Assertion[];
  tags: string; // comma separated
  notes: string;
}

export interface CasePayload {
  input: Record<string, unknown>;
  expectations: Assertion[];
  tags?: string[];
  notes?: string;
}

/* ------------------------------------------------------------------ */
/*  Draft <-> case conversion                                         */
/* ------------------------------------------------------------------ */

export const emptyDraft = (): CaseDraft => ({
  query: '',
  extraJson: '',
  expectations: [],
  tags: '',
  notes: '',
});

export const caseToDraft = (testCase: TestCase): CaseDraft => {
  const input = testCase.input || {};
  const { query, ...rest } = input as { query?: unknown; [k: string]: unknown };
  return {
    query: typeof query === 'string' ? query : '',
    extraJson: Object.keys(rest).length > 0 ? prettyJson(rest) : '',
    expectations: testCase.expectations || [],
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
    expectations: draft.expectations,
    tags: tags.length > 0 ? tags : undefined,
    notes: draft.notes.trim() || undefined,
  };
};

/* ------------------------------------------------------------------ */
/*  Editor form                                                       */
/* ------------------------------------------------------------------ */

interface CaseEditorProps {
  capability: TestCapability;
  initial: CaseDraft;
  saving: boolean;
  submitLabel: string;
  onSubmit: (payload: CasePayload) => void;
  onCancel: () => void;
}

const CaseEditor: React.FC<CaseEditorProps> = ({
  capability,
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

      <label className="testing-field">
        <span>Query</span>
        <input
          type="text"
          value={draft.query}
          onChange={(e) => update({ query: e.target.value })}
          placeholder="Search query / question"
        />
      </label>

      <label className="testing-field">
        <span>Filters / params (JSON object, optional)</span>
        <textarea
          className="testing-json-textarea"
          value={draft.extraJson}
          onChange={(e) => update({ extraJson: e.target.value })}
          placeholder={'{\n  "filters": {},\n  "params": {}\n}'}
          rows={5}
        />
      </label>

      <div className="testing-field">
        <span>Assertions</span>
        <AssertionBuilder
          capability={capability}
          assertions={draft.expectations}
          onChange={(expectations) => update({ expectations })}
        />
      </div>

      <label className="testing-field">
        <span>Tags (comma separated)</span>
        <input
          type="text"
          value={draft.tags}
          onChange={(e) => update({ tags: e.target.value })}
          placeholder="regression, smoke"
        />
      </label>

      <label className="testing-field">
        <span>Notes</span>
        <textarea
          value={draft.notes}
          onChange={(e) => update({ notes: e.target.value })}
          rows={2}
        />
      </label>

      <div className="testing-case-editor-actions">
        <button type="button" className="btn-sm" onClick={onCancel} disabled={saving}>
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
