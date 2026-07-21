// Cases x assertions matrix for the experiment editor.
//
// Rows are the chosen dataset's test cases; columns are assertion definitions.
// Each row has an active toggle (disable a case), each column a "select all"
// toggle, and each cell a checkbox. The experiment runs only active cases and,
// per case, only the assertion columns whose cell is checked.

import React, { useState } from 'react';
import type {
  Assertion,
  AssertionMatrix as MatrixValue,
  CaseRowState,
  TestCapability,
  TestCase,
} from '../../../types/testing';
import AssertionColumnForm from './AssertionColumnForm';
import { summarizeAssertion } from './assertionFields';

interface AssertionMatrixProps {
  capability: TestCapability;
  cases: TestCase[];
  value: MatrixValue;
  onChange: (value: MatrixValue) => void;
}

const caseTitle = (testCase: TestCase): string => {
  const query = (testCase.input as { query?: unknown }).query;
  if (typeof query === 'string' && query.trim()) return query;
  return `Case ${testCase.id.slice(0, 8)}`;
};

// Build a fully-populated row state for a case, padding cols/ovr to `ncols`.
const normalizedRow = (prev: CaseRowState | undefined, ncols: number): CaseRowState => ({
  active: prev ? prev.active : true,
  cols: Array.from({ length: ncols }, (_, i) => Boolean(prev?.cols?.[i])),
  ovr: Array.from({ length: ncols }, (_, i) => prev?.ovr?.[i] ?? ''),
});

const isLlmJudge = (assertion: Assertion): boolean => assertion.type === 'llm_judge';

const AssertionMatrix: React.FC<AssertionMatrixProps> = ({
  capability,
  cases,
  value,
  onChange,
}) => {
  // Be defensive: legacy/empty values may lack columns/cases.
  const columns = Array.isArray(value.columns) ? value.columns : [];
  const safeCases: Record<string, CaseRowState> = value.cases || {};
  const [adding, setAdding] = useState(false);
  const [editIndex, setEditIndex] = useState<number | null>(null);

  const rowOf = (caseId: string): CaseRowState =>
    normalizedRow(safeCases[caseId], columns.length);

  // Rebuild every row's state over the current columns, applying `fn`.
  const mutateRows = (fn: (caseId: string, row: CaseRowState) => CaseRowState) => {
    const next: Record<string, CaseRowState> = {};
    cases.forEach((c) => {
      next[c.id] = fn(c.id, rowOf(c.id));
    });
    onChange({ columns, cases: next });
  };

  const setRowActive = (caseId: string, active: boolean) =>
    mutateRows((id, row) => (id === caseId ? { ...row, active } : row));

  const setAllRows = (active: boolean) =>
    mutateRows((_, row) => ({ ...row, active }));

  const setCell = (caseId: string, col: number, on: boolean) =>
    mutateRows((id, row) =>
      id === caseId
        ? { ...row, cols: row.cols.map((v, i) => (i === col ? on : v)) }
        : row,
    );

  // Per-cell override prompt for an llm_judge column. Typing one also enables
  // the cell, so "type an override -> that row runs that test".
  const setCellOverride = (caseId: string, col: number, text: string) =>
    mutateRows((id, row) => {
      if (id !== caseId) return row;
      const ovr = (row.ovr || []).map((v, i) => (i === col ? text : v));
      const cols = text.trim()
        ? row.cols.map((v, i) => (i === col ? true : v))
        : row.cols;
      return { ...row, ovr, cols };
    });

  const setColumnAll = (col: number, on: boolean) =>
    mutateRows((_, row) => ({
      ...row,
      cols: row.cols.map((v, i) => (i === col ? on : v)),
    }));

  const addColumn = (assertion: Assertion) => {
    const nextColumns = [...columns, assertion];
    const last = nextColumns.length - 1;
    const next: Record<string, CaseRowState> = {};
    cases.forEach((c) => {
      const row = normalizedRow(safeCases[c.id], nextColumns.length);
      row.cols[last] = true; // default: applies to all cases (select-all on)
      next[c.id] = row;
    });
    onChange({ columns: nextColumns, cases: next });
    setAdding(false);
  };

  const editColumn = (index: number, assertion: Assertion) => {
    onChange({
      columns: columns.map((c, i) => (i === index ? assertion : c)),
      cases: safeCases,
    });
    setEditIndex(null);
  };

  const removeColumn = (index: number) => {
    const next: Record<string, CaseRowState> = {};
    cases.forEach((c) => {
      const row = rowOf(c.id);
      next[c.id] = {
        active: row.active,
        cols: row.cols.filter((_, i) => i !== index),
        ovr: (row.ovr || []).filter((_, i) => i !== index),
      };
    });
    onChange({ columns: columns.filter((_, i) => i !== index), cases: next });
  };

  const allRowsActive = cases.length > 0 && cases.every((c) => rowOf(c.id).active);
  const columnAllOn = (col: number): boolean =>
    cases.length > 0 && cases.every((c) => rowOf(c.id).cols[col]);

  if (cases.length === 0) {
    return (
      <p className="text-muted">
        This dataset has no test cases yet. Add input rows in the dataset editor first.
      </p>
    );
  }

  return (
    <div className="testing-matrix-wrap">
      <table className="admin-table testing-matrix">
        <thead>
          <tr>
            <th className="testing-matrix-case-col">
              <label className="testing-matrix-head-toggle">
                <input
                  type="checkbox"
                  checked={allRowsActive}
                  onChange={(e) => setAllRows(e.target.checked)}
                />{' '}
                Test case
              </label>
            </th>
            {columns.map((col, i) => (
              <th key={i} className="testing-matrix-assert-col">
                <div className="testing-matrix-col-head">
                  <label className="testing-matrix-head-toggle">
                    <input
                      type="checkbox"
                      checked={columnAllOn(i)}
                      onChange={(e) => setColumnAll(i, e.target.checked)}
                    />{' '}
                    <span title={summarizeAssertion(col)}>{summarizeAssertion(col)}</span>
                  </label>
                  <div className="testing-matrix-col-actions">
                    <button
                      type="button"
                      className="btn-sm"
                      onClick={() => {
                        setAdding(false);
                        setEditIndex(i);
                      }}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="btn-sm btn-danger"
                      onClick={() => removeColumn(i)}
                    >
                      &times;
                    </button>
                  </div>
                </div>
              </th>
            ))}
            <th className="testing-matrix-add-col">
              <button
                type="button"
                className="btn-sm btn-primary"
                onClick={() => {
                  setEditIndex(null);
                  setAdding(true);
                }}
              >
                + Expectation
              </button>
            </th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => {
            const row = rowOf(c.id);
            return (
              <tr key={c.id} className={row.active ? '' : 'testing-matrix-row-off'}>
                <td className="testing-matrix-case-col">
                  <label className="testing-matrix-row-toggle">
                    <input
                      type="checkbox"
                      checked={row.active}
                      onChange={(e) => setRowActive(c.id, e.target.checked)}
                    />{' '}
                    <span title={caseTitle(c)}>{caseTitle(c)}</span>
                  </label>
                </td>
                {columns.map((col, i) => (
                  <td key={i} className="testing-matrix-cell">
                    <input
                      type="checkbox"
                      checked={Boolean(row.cols[i])}
                      disabled={!row.active}
                      onChange={(e) => setCell(c.id, i, e.target.checked)}
                    />
                    {isLlmJudge(col) && (
                      <textarea
                        className="testing-matrix-override"
                        placeholder="Override prompt for this case (optional)"
                        value={row.ovr?.[i] || ''}
                        disabled={!row.active}
                        onChange={(e) => setCellOverride(c.id, i, e.target.value)}
                      />
                    )}
                  </td>
                ))}
                <td className="testing-matrix-add-col" />
              </tr>
            );
          })}
        </tbody>
      </table>

      {columns.length === 0 && !adding && (
        <p className="text-muted">
          No expectations yet. Use <strong>+ Expectation</strong> to add a column.
        </p>
      )}

      {adding && (
        <AssertionColumnForm
          capability={capability}
          onSubmit={addColumn}
          onCancel={() => setAdding(false)}
        />
      )}
      {editIndex !== null && columns[editIndex] && (
        <AssertionColumnForm
          capability={capability}
          initial={columns[editIndex]}
          onSubmit={(a) => editColumn(editIndex, a)}
          onCancel={() => setEditIndex(null)}
        />
      )}
    </div>
  );
};

export default AssertionMatrix;
