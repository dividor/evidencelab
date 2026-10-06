import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SummaryModal } from '../components/documents/SummaryModal';
import type { SummaryAdmin } from '../components/documents/summary/useSummaryAdmin';
import {
  fetchDocumentSections,
  generateDocumentSummary,
  saveDocumentSummary,
} from '../components/documents/summary/documentSummaryApi';

jest.mock('../config', () => ({ __esModule: true, default: '/api', API_KEY: undefined, USER_MODULE: true }));
jest.mock('../hooks/useAuth', () => ({ useAuth: () => ({ isAuthenticated: false }) }));
jest.mock('../hooks/useRatings', () => ({
  useRatings: () => ({ ratings: new Map(), submitRating: jest.fn(), deleteRating: jest.fn() }),
}));
jest.mock('../components/documents/summary/documentSummaryApi', () => {
  const actual = jest.requireActual('../components/documents/summary/documentSummaryApi');
  return {
    ...actual,
    fetchDocumentSections: jest.fn(),
    generateDocumentSummary: jest.fn(),
    saveDocumentSummary: jest.fn(),
  };
});

const CURRENT = '## Summary\n\nThe current summary of the evaluation.';
const GENERATED = '## Summary\n\nA new summary written by the model.';
const DEFAULT_PROMPT = 'OUTPUT FORMAT: the team prompt';
const REGENERATE = 'Regenerate with AI';
const SAVE = 'Save';

const makeAdmin = (): SummaryAdmin => ({
  dataSource: 'wfp',
  defaults: { mode: 'map_reduce', sectionTypes: ['executive_summary', 'findings'], prompt: DEFAULT_PROMPT },
  allSectionTypes: ['executive_summary', 'findings', 'annexes'],
  model: { model: 'gemini-2.5-flash', max_tokens: 2000, temperature: 0.2, chunk_overlap: 800, chunk_tokens_ratio: 0.5 },
  onSaved: jest.fn(),
});

const saved = (summary: string, method: string) => ({
  doc_id: 'doc-7',
  full_summary: summary,
  summarization_method: method,
  summary_user_set: true,
  summary_updated_by: 'admin@example.org',
  summary_updated_at: '2026-10-06T10:00:00Z',
});

const renderModal = (admin: SummaryAdmin | null, summary = CURRENT) =>
  render(
    <SummaryModal isOpen onClose={jest.fn()} summary={summary} title="Ethiopia evaluation" docId="doc-7" admin={admin} />,
  );

beforeEach(() => {
  (fetchDocumentSections as jest.Mock).mockResolvedValue({
    has_section_types: true,
    sections: [
      { section_type: 'executive_summary', chars: 26000, chunks: 17 },
      { section_type: 'findings', chars: 215000, chunks: 121 },
      { section_type: 'annexes', chars: 1295000, chunks: 824 },
    ],
    single_prompt: { context_window: 1048576, available: true, reason: null },
  });
});

describe('Summary modal for administrators', () => {
  test('the modal says how, by whom and when the summary was made', () => {
    render(
      <SummaryModal
        isOpen
        onClose={jest.fn()}
        summary={CURRENT}
        title="Ethiopia evaluation"
        docId="doc-7"
        provenance={{ label: 'Regenerated with AI (map reduce) by admin@example.org', at: '2026-10-06T17:55:00Z' }}
      />,
    );
    expect(screen.getByText(/^Regenerated with AI \(map reduce\) by admin@example\.org · /)).toBeInTheDocument();
  });

  test('everyone else sees the summary read-only', () => {
    renderModal(null);
    expect(screen.getByText('The current summary of the evaluation.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(screen.queryByRole('button', { name: REGENERATE })).toBeNull();
  });

  test('editing saves the text as an edited summary', async () => {
    const admin = makeAdmin();
    (saveDocumentSummary as jest.Mock).mockResolvedValue(saved('Edited text.', 'ui_edited'));
    renderModal(admin);

    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Summary text'), { target: { value: 'Edited text.' } });
    fireEvent.click(screen.getByRole('button', { name: SAVE }));

    await waitFor(() => expect(admin.onSaved).toHaveBeenCalledWith(saved('Edited text.', 'ui_edited')));
    expect(saveDocumentSummary).toHaveBeenCalledWith('wfp', 'doc-7', 'Edited text.', 'ui_edited');
    expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument();
  });

  test('regenerating shows the sections, then puts the new summary in the editor unsaved', async () => {
    const admin = makeAdmin();
    let finish: (value: unknown) => void = () => undefined;
    (generateDocumentSummary as jest.Mock).mockImplementation(
      (options) =>
        new Promise((resolve) => {
          options.onProgress({ stage: 'map', done: 1, total: 3 });
          finish = resolve;
        }),
    );
    renderModal(admin);

    fireEvent.click(screen.getByRole('button', { name: REGENERATE }));
    expect(await screen.findByText(/· 26k/)).toBeInTheDocument();
    expect(screen.getByLabelText('Summary prompt')).toHaveValue(DEFAULT_PROMPT);
    fireEvent.click(screen.getByLabelText(/Annexes/));
    fireEvent.click(screen.getByRole('button', { name: 'Generate' }));

    expect(await screen.findByText('Summarising part 1 of 3…')).toBeInTheDocument();
    const request = (generateDocumentSummary as jest.Mock).mock.calls[0][0];
    expect(request.settings).toEqual({
      mode: 'map_reduce',
      sectionTypes: ['executive_summary', 'findings', 'annexes'],
      prompt: DEFAULT_PROMPT,
    });
    expect(request.model.model).toBe('gemini-2.5-flash');

    await act(async () =>
      finish({ summary: GENERATED, mode: 'map_reduce', method: 'ui_map_reduce', calls: 4, input_chars: 1 }),
    );
    expect(screen.getByLabelText('Summary text')).toHaveValue(GENERATED);
    expect(screen.getByText(/written with Map reduce \(4 model calls\)/)).toBeInTheDocument();
    expect(saveDocumentSummary).not.toHaveBeenCalled();

    (saveDocumentSummary as jest.Mock).mockResolvedValue(saved(GENERATED, 'ui_map_reduce'));
    fireEvent.click(screen.getByRole('button', { name: SAVE }));
    await waitFor(() =>
      expect(saveDocumentSummary).toHaveBeenCalledWith('wfp', 'doc-7', GENERATED, 'ui_map_reduce'),
    );
  });

  test('a generated summary changed before saving is saved as edited', async () => {
    (generateDocumentSummary as jest.Mock).mockResolvedValue({
      summary: GENERATED,
      mode: 'single_prompt',
      method: 'ui_single_prompt',
      calls: 1,
      input_chars: 1,
    });
    (saveDocumentSummary as jest.Mock).mockResolvedValue(saved('Changed.', 'ui_edited'));
    renderModal(makeAdmin());

    fireEvent.click(screen.getByRole('button', { name: REGENERATE }));
    fireEvent.click(await screen.findByLabelText(/Single prompt/));
    expect(screen.getByText(/A single prompt can take up to 1,048,576 tokens/)).toBeInTheDocument();
    expect(fetchDocumentSections).toHaveBeenCalledWith('wfp', 'doc-7', expect.objectContaining({ model: 'gemini-2.5-flash' }));
    fireEvent.click(screen.getByRole('button', { name: 'Generate' }));
    fireEvent.change(await screen.findByLabelText('Summary text'), { target: { value: 'Changed.' } });
    fireEvent.click(screen.getByRole('button', { name: SAVE }));

    await waitFor(() => expect(saveDocumentSummary).toHaveBeenCalledWith('wfp', 'doc-7', 'Changed.', 'ui_edited'));
  });

  test('a generation error is shown and nothing changes', async () => {
    (generateDocumentSummary as jest.Mock).mockRejectedValue(new Error('Choose fewer sections or use map reduce.'));
    renderModal(makeAdmin());

    fireEvent.click(screen.getByRole('button', { name: REGENERATE }));
    await screen.findByText(/· 26k/);
    fireEvent.click(screen.getByRole('button', { name: 'Generate' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Choose fewer sections or use map reduce.');
    expect(screen.queryByLabelText('Summary text')).toBeNull();
  });

  test('single prompt is refused for a model that cannot count tokens', async () => {
    (fetchDocumentSections as jest.Mock).mockResolvedValue({
      has_section_types: true,
      sections: [{ section_type: 'findings', chars: 1000, chunks: 1 }],
      single_prompt: {
        context_window: 1048576,
        available: false,
        reason: 'This model cannot count its tokens exactly, so it cannot be used for a single prompt.',
      },
    });
    renderModal(makeAdmin());
    fireEvent.click(screen.getByRole('button', { name: REGENERATE }));
    fireEvent.click(await screen.findByLabelText(/Single prompt/));
    expect(screen.getByText(/cannot be used for a single prompt/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Generate' })).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/Map reduce/));
    expect(screen.getByRole('button', { name: 'Generate' })).toBeEnabled();
  });

  test('a document without a summary can be given one', () => {
    renderModal(makeAdmin(), '');
    expect(screen.getByText('This document has no summary yet.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: REGENERATE })).toBeInTheDocument();
  });
});
