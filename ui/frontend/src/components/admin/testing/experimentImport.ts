// Orchestrates the "Create Dataset + Experiment" import: create an ai_summary
// dataset, one test case per question, and a draft experiment whose single
// llm_judge column is overridden per row with that row's expected answer. The
// row-level pairing (question <-> expected answer) is built as the cases are
// created, so a question can never end up matched to the wrong rubric.

import axios from 'axios';
import API_BASE_URL from '../../../config';
import type { AssertionMatrix, CaseRowState } from '../../../types/testing';
import type { QaCsvRow } from './csv';

// Fallback rubric for the llm_judge column. Every row supplies its own expected
// answer as a per-cell override (ovr), so this is only used when a row's
// expected answer is blank.
export const DEFAULT_RUBRIC =
  'The AI summary should accurately and completely address the question, '
  + 'consistent with the expected answer provided for the test case.';

export const DEFAULT_THRESHOLD = 0.7;

interface CreatedCase {
  caseId: string;
  expectedAnswer: string;
}

// Build the experiment's assertion matrix: a single llm_judge column plus, per
// case, an active flag, the column toggle, and the expected answer as the
// per-cell rubric override. Matches the shape produced by ExperimentEditor.
export const buildJudgeMatrix = (
  cases: CreatedCase[],
  threshold: number,
): AssertionMatrix => {
  const columns = [{ type: 'llm_judge', rubric: DEFAULT_RUBRIC, threshold }];
  const out: Record<string, CaseRowState> = {};
  cases.forEach(({ caseId, expectedAnswer }) => {
    out[caseId] = { active: true, cols: [true], ovr: [expectedAnswer.trim()] };
  });
  return { columns, cases: out };
};

export interface ImportParams {
  // Base name; saved as `<name>_dataset` and `<name>_experiment`.
  name: string;
  description?: string;
  // What is tested: "search" | "ai_summary". The llm_judge assertion built from
  // the expectation column only applies to ai_summary.
  capability: string;
  dataSource: string;
  threshold: number;
  // Run configuration (model combo / run-as-group); same shape as the
  // experiment editor's config. Omitted keys fall back to run defaults.
  config?: Record<string, unknown>;
  rows: QaCsvRow[];
}

// Best-effort removal of a half-created dataset (cascades its cases). Surfacing
// the original failure to the caller matters more than a cleanup error.
const deleteDatasetQuietly = async (datasetId: string): Promise<void> => {
  try {
    await axios.delete(`${API_BASE_URL}/testing/datasets/${datasetId}`);
  } catch {
    // Intentionally ignored — caller re-throws the original error.
  }
};

const createCases = async (
  datasetId: string,
  rows: QaCsvRow[],
): Promise<CreatedCase[]> => {
  const created: CreatedCase[] = [];
  for (const row of rows) {
    const resp = await axios.post<{ id: string }>(
      `${API_BASE_URL}/testing/datasets/${datasetId}/cases`,
      { input: row.input, tags: row.tags, notes: row.notes },
    );
    created.push({ caseId: resp.data.id, expectedAnswer: row.expectation });
  }
  return created;
};

// Create the dataset, its cases, and the paired draft experiment. On any
// failure after the dataset exists, the dataset is removed so a retry is clean
// (fail hard, no half-imported state). Returns the new dataset id.
export const importDatasetWithExperiment = async (
  params: ImportParams,
): Promise<string> => {
  const base = params.name.trim();
  const datasetResp = await axios.post<{ id: string }>(
    `${API_BASE_URL}/testing/datasets`,
    {
      name: `${base}_dataset`,
      description: params.description?.trim() || undefined,
      capability: params.capability,
      data_source: params.dataSource.trim(),
    },
  );
  const datasetId = datasetResp.data.id;
  try {
    const created = await createCases(datasetId, params.rows);
    const config =
      params.config && Object.keys(params.config).length > 0
        ? params.config
        : null;
    await axios.post(`${API_BASE_URL}/testing/experiments`, {
      dataset_id: datasetId,
      name: `${base}_experiment`,
      config,
      case_expectations: buildJudgeMatrix(created, params.threshold),
    });
    return datasetId;
  } catch (err) {
    await deleteDatasetQuietly(datasetId);
    throw err;
  }
};
