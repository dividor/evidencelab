import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import * as XLSX from 'xlsx-js-style';
import API_BASE_URL from '../../../config';
import type { TestCase, TestDataset } from '../../../types/testing';
import ConfirmModal from '../ConfirmModal';
import CaseEditor, { CasePayload } from './CaseEditor';
import { SAMPLE_DATASET_CSV } from './csv';

/* ------------------------------------------------------------------ */
/*  CSV import helpers (columns: query, tags, notes, filters)         */
/* ------------------------------------------------------------------ */

const SAMPLE_CSV = SAMPLE_DATASET_CSV;

// Map one parsed CSV row (header-keyed) to a case payload; null if no query.
const rowToPayload = (row: Record<string, unknown>): CasePayload | null => {
  const r: Record<string, string> = {};
  Object.keys(row).forEach((k) => {
    r[k.trim().toLowerCase()] = String(row[k] ?? '').trim();
  });
  const query = r.query;
  if (!query) return null;
  const input: Record<string, unknown> = { query };
  if (r.filters) {
    try {
      const parsed = JSON.parse(r.filters);
      if (parsed && typeof parsed === 'object') input.filters = parsed;
    } catch {
      // Ignore malformed filters JSON — keep the query-only case.
    }
  }
  const tags = (r.tags || '')
    .split(/[;,]/)
    .map((t) => t.trim())
    .filter(Boolean);
  return {
    input,
    tags: tags.length > 0 ? tags : undefined,
    notes: r.notes || undefined,
  };
};

const parseCsvToPayloads = (text: string): CasePayload[] => {
  const wb = XLSX.read(text, { type: 'string' });
  const ws = wb.Sheets[wb.SheetNames[0]];
  if (!ws) return [];
  const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(ws, { defval: '' });
  return rows.map(rowToPayload).filter((p): p is CasePayload => p !== null);
};

const downloadSampleCsv = () => {
  const blob = new Blob([SAMPLE_CSV], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'test-cases-sample.csv';
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
};

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

const DatasetEditor: React.FC<DatasetEditorProps> = ({ dataset, onBack }) => {
  const [cases, setCases] = useState<TestCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<TestCase | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState('');
  const fileRef = useRef<HTMLInputElement | null>(null);

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

  // Import cases from a CSV file — appends to whatever is already in the dataset.
  const handleCsvFile = async (file: File) => {
    setError('');
    setUploadMsg('');
    let payloads: CasePayload[] = [];
    try {
      payloads = parseCsvToPayloads(await file.text());
    } catch {
      setError('Could not parse the CSV file.');
      return;
    }
    if (payloads.length === 0) {
      setError('No rows with a "query" column were found in the CSV.');
      return;
    }
    setUploading(true);
    let ok = 0;
    for (const payload of payloads) {
      try {
        await axios.post(
          `${API_BASE_URL}/testing/datasets/${dataset.id}/cases`,
          payload,
        );
        ok += 1;
      } catch {
        // Continue importing the rest; the final count reflects failures.
      }
    }
    await fetchCases();
    setUploading(false);
    setUploadMsg(
      `Imported ${ok} of ${payloads.length} case${payloads.length === 1 ? '' : 's'}`
        + (ok < payloads.length ? ` (${payloads.length - ok} failed)` : '')
        + '.',
    );
  };

  const onFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // allow re-uploading the same file
    if (file) handleCsvFile(file);
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
          <div className="testing-detail-titlerow">
            <h3 style={{ margin: 0 }}>{dataset.name}</h3>
            <div className="testing-config-badges">
              <span className="testing-config-badge">
                <span className="testing-config-badge-label">Type</span>
                {dataset.capability}
              </span>
              <span className="testing-config-badge">
                <span className="testing-config-badge-label">Source</span>
                {dataset.data_source}
              </span>
            </div>
          </div>
          {dataset.description && (
            <p className="text-muted" style={{ margin: '0.25rem 0 0' }}>
              {dataset.description}
            </p>
          )}
        </div>
      </div>

      <div className="testing-cases">
        <div className="testing-controls">
          <p className="text-muted" style={{ margin: 0 }}>
            {cases.length} test case{cases.length !== 1 ? 's' : ''}
          </p>
          {!creating && !editingCase && (
            <div className="testing-dataset-actions" style={{ marginLeft: 'auto' }}>
              <div className="testing-upload-group">
                <button
                  className="btn-sm"
                  onClick={() => fileRef.current?.click()}
                  disabled={uploading}
                >
                  {uploading ? 'Importing…' : 'Upload CSV'}
                </button>
                <button
                  type="button"
                  className="testing-raw-toggle"
                  onClick={downloadSampleCsv}
                >
                  sample format
                </button>
              </div>
              <button
                className="btn-sm btn-primary"
                onClick={() => setCreating(true)}
              >
                + Add case
              </button>
            </div>
          )}
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            style={{ display: 'none' }}
            onChange={onFileSelected}
          />
        </div>
        {uploadMsg && (
          <p className="text-muted" style={{ margin: '0 0 0.5rem' }}>
            {uploadMsg}
          </p>
        )}

        {creating && (
          <div className="testing-case-editor-wrap">
            <CaseEditor
              initialCase={null}
              dataSource={dataset.data_source}
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
              key={editingCase.id}
              initialCase={editingCase}
              dataSource={dataset.data_source}
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
