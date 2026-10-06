import React from 'react';
import axios from 'axios';
import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { BulkSummaryModal } from '../components/documents/summary/BulkSummaryModal';
import { ReprocessSummaryChoice } from '../components/documents/summary/ReprocessSummaryChoice';
import { SummaryBulkBar } from '../components/documents/summary/SummaryBulkBar';
import { useDocumentSelection } from '../components/documents/summary/useDocumentSelection';
import type { SummaryAdmin } from '../components/documents/summary/useSummaryAdmin';
import { reprocessDocument } from '../components/documents/documentsActions';
import {
  generateDocumentSummary,
  saveDocumentSummary,
} from '../components/documents/summary/documentSummaryApi';

jest.mock('../config', () => ({ __esModule: true, default: '/api', API_KEY: undefined, USER_MODULE: true }));
jest.mock('axios', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn(), put: jest.fn() } }));
jest.mock('../components/documents/summary/documentSummaryApi', () => {
  const actual = jest.requireActual('../components/documents/summary/documentSummaryApi');
  return { ...actual, generateDocumentSummary: jest.fn(), saveDocumentSummary: jest.fn() };
});

const DOCS = [
  { id: 'd1', title: 'Kenya school meals' },
  { id: 'd2', title: 'Cash transfers review' },
  { id: 'd3', title: 'Nutrition in schools' },
];
const START = 'Regenerate and save';

const makeAdmin = (): SummaryAdmin => ({
  dataSource: 'wfp',
  defaults: { mode: 'single_prompt', sectionTypes: ['findings'], prompt: 'Team prompt' },
  allSectionTypes: ['executive_summary', 'findings'],
  model: { model: 'gemini-2.5-flash', max_tokens: 2000, temperature: 0.2, chunk_overlap: 800, chunk_tokens_ratio: 0.5 },
  onSaved: jest.fn(),
});

const itemFor = (title: string) => screen.getByText(title).closest('li') as HTMLElement;

describe('Bulk regenerate', () => {
  test('generates and saves each document, and lists failures without stopping', async () => {
    const admin = makeAdmin();
    (generateDocumentSummary as jest.Mock).mockImplementation(async ({ docId }) => {
      if (docId === 'd2') throw new Error('Single prompt is not available for this data source');
      return { summary: `Summary of ${docId}`, mode: 'single_prompt', method: 'ui_single_prompt', calls: 1 };
    });
    (saveDocumentSummary as jest.Mock).mockImplementation(async (_ds, docId, summary, method) => ({
      doc_id: docId,
      full_summary: summary,
      summarization_method: method,
    }));
    const onFinished = jest.fn();
    render(<BulkSummaryModal isOpen onClose={jest.fn()} admin={admin} documents={DOCS} onFinished={onFinished} />);

    expect(screen.getByRole('heading', { name: 'Regenerate 3 summaries' })).toBeInTheDocument();
    expect(screen.getByLabelText(/Single prompt/)).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: START }));

    await waitFor(() => expect(within(itemFor('Nutrition in schools')).getByText('Saved')).toBeInTheDocument());
    expect(within(itemFor('Kenya school meals')).getByText('Saved')).toBeInTheDocument();
    expect(
      within(itemFor('Cash transfers review')).getByText(
        'Failed: Single prompt is not available for this data source',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/2 saved · 1 failed · 0 to go/)).toBeInTheDocument();
    expect(saveDocumentSummary).toHaveBeenCalledWith('wfp', 'd1', 'Summary of d1', 'ui_single_prompt');
    expect(saveDocumentSummary).not.toHaveBeenCalledWith('wfp', 'd2', expect.anything(), expect.anything());
    expect(admin.onSaved).toHaveBeenCalledTimes(2);
    const settings = (generateDocumentSummary as jest.Mock).mock.calls[0][0].settings;
    expect(settings).toEqual({ mode: 'single_prompt', sectionTypes: ['findings'], prompt: 'Team prompt' });

    fireEvent.click(screen.getByText('Close'));
    expect(onFinished).toHaveBeenCalled();
  });

  test('runs two at a time, and Stop leaves the rest unchanged', async () => {
    const pending: Array<{ signal: AbortSignal; reject: (e: Error) => void }> = [];
    (generateDocumentSummary as jest.Mock).mockImplementation(
      ({ signal }) =>
        new Promise((_resolve, reject) => {
          pending.push({ signal, reject });
          signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
        }),
    );
    render(<BulkSummaryModal isOpen onClose={jest.fn()} admin={makeAdmin()} documents={DOCS} />);

    fireEvent.click(screen.getByRole('button', { name: START }));
    await waitFor(() => expect(pending).toHaveLength(2));
    expect(within(itemFor('Nutrition in schools')).getByText('Waiting')).toBeInTheDocument();

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Stop' })));

    await waitFor(() => expect(screen.getByText(/0 saved · 0 failed · 0 to go · 3 not changed/)).toBeInTheDocument());
    expect(pending.every((p) => p.signal.aborted)).toBe(true);
    expect(generateDocumentSummary).toHaveBeenCalledTimes(2);
    expect(saveDocumentSummary).not.toHaveBeenCalled();
  });
});

describe('Selecting documents', () => {
  test('selection is kept across pages and the bar starts the run', () => {
    const { result } = renderHook(() => useDocumentSelection());
    act(() => result.current.setPage([{ doc_id: 'd1', title: 'A' }, { doc_id: 'd2', title: 'B' }], true));
    act(() => result.current.toggle({ doc_id: 'd9', title: 'On page 2' }));
    act(() => result.current.toggle({ doc_id: 'd1', title: 'A' }));
    expect(result.current.documents).toEqual([
      { id: 'd2', title: 'B' },
      { id: 'd9', title: 'On page 2' },
    ]);

    const onRegenerate = jest.fn();
    render(
      <SummaryBulkBar
        selection={result.current}
        pageDocuments={[{ doc_id: 'd1', title: 'A' }, { doc_id: 'd2', title: 'B' }]}
        onRegenerate={onRegenerate}
      />,
    );
    expect(screen.getByText('2 selected')).toBeInTheDocument();
    expect(screen.getByLabelText('Select all on this page')).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate summaries (2)' }));
    expect(onRegenerate).toHaveBeenCalled();
  });
});

describe('Reprocessing a document whose summary was set in the app', () => {
  test('offers to keep or replace the summary, or cancel', () => {
    const onChoose = jest.fn();
    render(
      <ReprocessSummaryChoice
        doc={{ title: 'Kenya school meals', summary_updated_by: 'admin@example.org' }}
        onChoose={onChoose}
      />,
    );
    expect(screen.getByText(/written or edited in the app by admin@example.org/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reprocess and keep the summary' }));
    fireEvent.click(screen.getByRole('button', { name: 'Reprocess and replace the summary' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onChoose.mock.calls).toEqual([[false], [true], [null]]);
  });

  test('the reprocess request asks to replace the summary only when chosen', async () => {
    (axios.post as jest.Mock).mockResolvedValue({ data: {} });
    const args = { doc: { id: 'd1' }, dataSource: 'wfp', reprocessingDocId: null, setReprocessingDocId: jest.fn(), onRefresh: jest.fn() };

    await reprocessDocument({ ...args, replaceSummary: true });
    await reprocessDocument(args);

    expect((axios.post as jest.Mock).mock.calls.map((c) => c[0])).toEqual([
      '/api/documents/d1/reprocess?data_source=wfp&replace_summary=true',
      '/api/documents/d1/reprocess?data_source=wfp',
    ]);
  });
});
