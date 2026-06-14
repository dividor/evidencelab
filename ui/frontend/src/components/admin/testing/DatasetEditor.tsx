import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import API_BASE_URL from '../../../config';
import type { TestCase, TestDataset } from '../../../types/testing';
import ConfirmModal from '../ConfirmModal';
import CaseEditor, {
  CaseDraft,
  CasePayload,
  caseToDraft,
  emptyDraft,
} from './CaseEditor';
import RunExperimentModal from './RunExperimentModal';
import { prettyJson } from './testingFormat';

interface DatasetEditorProps {
  dataset: TestDataset;
  onBack: () => void;
  onViewExperiments: (dataset: TestDataset) => void;
}

/* ------------------------------------------------------------------ */
/*  Read-only display of an existing case                             */
/* ------------------------------------------------------------------ */

interface CaseCardProps {
  testCase: TestCase;
  onEdit: () => void;
  onDelete: () => void;
}

const CaseCard: React.FC<CaseCardProps> = ({ testCase, onEdit, onDelete }) => (
  <div className="testing-case-card">
    <div className="testing-case-card-header">
      <div className="testing-case-tags">
        {(testCase.tags || []).map((t) => (
          <span key={t} className="testing-tag">{t}</span>
        ))}
      </div>
      <div className="testing-case-card-actions">
        <button className="btn-sm" onClick={onEdit}>Edit</button>
        <button className="btn-sm btn-danger" onClick={onDelete}>Delete</button>
      </div>
    </div>
    <div className="testing-case-block">
      <span className="testing-case-label">Input</span>
      <pre className="testing-pre">{prettyJson(testCase.input)}</pre>
    </div>
    <div className="testing-case-block">
      <span className="testing-case-label">Expectations</span>
      <pre className="testing-pre">{prettyJson(testCase.expectations)}</pre>
    </div>
    {testCase.notes && (
      <div className="testing-case-block">
        <span className="testing-case-label">Notes</span>
        <p className="testing-notes">{testCase.notes}</p>
      </div>
    )}
  </div>
);

/* ------------------------------------------------------------------ */
/*  Dataset editor                                                    */
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
  const [showRun, setShowRun] = useState(false);

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

  const renderCase = (testCase: TestCase) => {
    if (editingId === testCase.id) {
      return (
        <CaseEditor
          key={testCase.id}
          capability={dataset.capability}
          initial={caseToDraft(testCase)}
          saving={saving}
          submitLabel="Save Case"
          onSubmit={(payload) => updateCase(testCase.id, payload)}
          onCancel={() => setEditingId(null)}
        />
      );
    }
    return (
      <CaseCard
        key={testCase.id}
        testCase={testCase}
        onEdit={() => setEditingId(testCase.id)}
        onDelete={() => setDeleteTarget(testCase)}
      />
    );
  };

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
          <button className="btn-sm btn-primary" onClick={() => setShowRun(true)}>
            Run experiment
          </button>
        </div>
      </div>

      <div className="testing-cases">
        <div className="testing-controls">
          <p className="text-muted" style={{ margin: 0 }}>
            {cases.length} test case{cases.length !== 1 ? 's' : ''}
          </p>
          {!creating && (
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
          <CaseEditor
            capability={dataset.capability}
            initial={emptyDraft() as CaseDraft}
            saving={saving}
            submitLabel="Create Case"
            onSubmit={createCase}
            onCancel={() => setCreating(false)}
          />
        )}

        {cases.map(renderCase)}
        {cases.length === 0 && !creating && (
          <p className="text-muted">No test cases yet.</p>
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

      {showRun && (
        <RunExperimentModal
          datasetId={dataset.id}
          onLaunched={() => {
            setShowRun(false);
            onViewExperiments(dataset);
          }}
          onCancel={() => setShowRun(false)}
        />
      )}
    </div>
  );
};

export default DatasetEditor;
