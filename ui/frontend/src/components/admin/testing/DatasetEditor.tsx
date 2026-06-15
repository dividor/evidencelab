import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';
import type { TestCase, TestDataset } from '../../../types/testing';
import ConfirmModal from '../ConfirmModal';
import CaseEditor, {
  CasePayload,
  caseToDraft,
  emptyDraft,
} from './CaseEditor';

interface DatasetEditorProps {
  dataset: TestDataset;
  onBack: () => void;
  onViewExperiments: (dataset: TestDataset) => void;
}

/* ------------------------------------------------------------------ */
/*  Case field accessors for the table view                           */
/* ------------------------------------------------------------------ */

const caseQuery = (testCase: TestCase): string => {
  const q = (testCase.input as { query?: unknown }).query;
  return typeof q === 'string' ? q : '';
};

// Everything in the case input except the query (filters/params), compacted.
const caseExtra = (testCase: TestCase): string => {
  const input = (testCase.input || {}) as Record<string, unknown>;
  const rest: Record<string, unknown> = {};
  Object.keys(input).forEach((k) => {
    if (k !== 'query') rest[k] = input[k];
  });
  return Object.keys(rest).length > 0 ? JSON.stringify(rest) : '';
};

/* ------------------------------------------------------------------ */
/*  Dataset editor (manages input rows only)                          */
/* ------------------------------------------------------------------ */

const DatasetEditor: React.FC<DatasetEditorProps> = ({
  dataset,
  onBack,
  onViewExperiments,
}) => {
  const [cases, setCases] = useState<TestCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<TestCase | null>(null);

  const fetchCases = useCallback(async () => {
    try {
      const resp = await axios.get<TestCase[]>(
        `${API_BASE_URL}/testing/datasets/${dataset.id}/cases`,
      );
      setCases(resp.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load test cases');
    } finally {
      setLoading(false);
    }
  }, [dataset.id]);

  useEffect(() => {
    fetchCases();
  }, [fetchCases]);

  const createCase = async (payload: CasePayload) => {
    setSaving(true);
    setError('');
    try {
      await axios.post(`${API_BASE_URL}/testing/datasets/${dataset.id}/cases`, payload);
      setCreating(false);
      await fetchCases();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create test case');
    } finally {
      setSaving(false);
    }
  };

  const updateCase = async (caseId: string, payload: CasePayload) => {
    setSaving(true);
    setError('');
    try {
      await axios.put(`${API_BASE_URL}/testing/cases/${caseId}`, payload);
      setEditingId(null);
      await fetchCases();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to update test case');
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      await axios.delete(`${API_BASE_URL}/testing/cases/${deleteTarget.id}`);
      setDeleteTarget(null);
      await fetchCases();
    } catch (err: any) {
      setDeleteTarget(null);
      setError(err.response?.data?.detail || 'Failed to delete test case');
    }
  };

  const editingCase = cases.find((c) => c.id === editingId) || null;

  if (loading) return <div className="admin-loading">Loading...</div>;

  return (
    <div className="admin-section testing-section">
      {error && (
        <div className="auth-error">
          {error}
          <button className="auth-error-dismiss" onClick={() => setError('')}>&times;</button>
        </div>
      )}

      <div className="testing-editor-header">
        <button className="btn-sm" onClick={onBack}>&larr; Back to datasets</button>
        <div className="testing-editor-title">
          <h3 style={{ margin: 0 }}>{dataset.name}</h3>
          <p className="text-muted" style={{ margin: 0 }}>
            {dataset.capability} &middot; {dataset.data_source}
            {dataset.description ? ` — ${dataset.description}` : ''}
          </p>
        </div>
        <div className="testing-editor-header-actions">
          <button className="btn-sm" onClick={() => onViewExperiments(dataset)}>
            View experiments
          </button>
        </div>
      </div>

      <div className="testing-cases">
        <div className="testing-controls">
          <p className="text-muted" style={{ margin: 0 }}>
            {cases.length} test case{cases.length !== 1 ? 's' : ''}
          </p>
          {!creating && !editingCase && (
            <button
              className="btn-sm btn-primary"
              style={{ marginLeft: 'auto' }}
              onClick={() => setCreating(true)}
            >
              + Add case
            </button>
          )}
        </div>

        {creating && (
          <div className="testing-case-editor-wrap">
            <CaseEditor
              initial={emptyDraft()}
              saving={saving}
              submitLabel="Create Case"
              onSubmit={createCase}
              onCancel={() => setCreating(false)}
            />
          </div>
        )}

        {editingCase && (
          <div className="testing-case-editor-wrap">
            <CaseEditor
              initial={caseToDraft(editingCase)}
              saving={saving}
              submitLabel="Save Case"
              onSubmit={(payload) => updateCase(editingCase.id, payload)}
              onCancel={() => setEditingId(null)}
            />
          </div>
        )}

        {cases.length === 0 ? (
          !creating && <p className="text-muted">No test cases yet.</p>
        ) : (
          <table className="admin-table testing-cases-table">
            <thead>
              <tr>
                <th>Query</th>
                <th>Filters / params</th>
                <th>Tags</th>
                <th>Notes</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {cases.map((testCase) => {
                const extra = caseExtra(testCase);
                return (
                  <tr key={testCase.id}>
                    <td className="testing-cases-query">{caseQuery(testCase) || '—'}</td>
                    <td className="testing-cases-extra">
                      {extra ? (
                        <code title={extra}>{extra}</code>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                    <td>
                      <div className="testing-case-tags">
                        {(testCase.tags || []).map((t) => (
                          <span key={t} className="testing-tag">
                            {t}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="testing-cases-notes">{testCase.notes || ''}</td>
                    <td className="testing-row-actions">
                      <button className="btn-sm" onClick={() => setEditingId(testCase.id)}>
                        Edit
                      </button>
                      <button
                        className="btn-sm btn-danger"
                        onClick={() => setDeleteTarget(testCase)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {deleteTarget && (
        <ConfirmModal
          title="Delete Test Case"
          message="Permanently delete this test case? This cannot be undone."
          confirmLabel="Delete Case"
          onConfirm={confirmDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
};

export default DatasetEditor;
