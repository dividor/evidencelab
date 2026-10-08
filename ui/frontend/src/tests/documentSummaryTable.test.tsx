import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { DocumentsSummaryCell } from '../components/documents/DocumentsSummaryCell';
import { DocumentsTableRow } from '../components/documents/DocumentsTableRow';
import { docSummaryPayload, readDocSummaryDefaults } from '../components/admin/DocumentSummaryGroupSection';
import { formatProvenance, summaryProvenance } from '../components/documents/summary/summaryProvenance';

jest.mock('../config', () => ({ __esModule: true, default: '/api', API_KEY: undefined, USER_FEEDBACK: false }));

const SUMMARY = 'A short summary of the evaluation.';
const TITLE = 'Kenya school meals';

describe('Summary cell', () => {
  test('clicking the summary opens it', () => {
    const onOpen = jest.fn();
    render(<DocumentsSummaryCell summary={SUMMARY} docTitle={TITLE} onOpenSummary={onOpen} />);
    fireEvent.click(screen.getByRole('button', { name: /A short summary/ }));
    expect(onOpen).toHaveBeenCalledWith(SUMMARY, TITLE);
  });

  test('an empty summary offers administrators "Add summary"', () => {
    const onOpen = jest.fn();
    const { rerender } = render(<DocumentsSummaryCell summary="" docTitle={TITLE} onOpenSummary={onOpen} />);
    expect(screen.getByText('-')).toBeInTheDocument();
    rerender(<DocumentsSummaryCell summary="" docTitle={TITLE} onOpenSummary={onOpen} canEdit />);
    fireEvent.click(screen.getByRole('button', { name: 'Add summary' }));
    expect(onOpen).toHaveBeenCalledWith('', TITLE);
  });
});

const renderRow = (props: Record<string, unknown>) =>
  render(
    <table>
      <tbody>
        <DocumentsTableRow
          doc={{ id: 'd1', doc_id: 'd1', title: TITLE, full_summary: SUMMARY }}
          index={0}
          onOpenSummary={jest.fn()}
          onOpenToc={jest.fn()}
          onOpenMetadata={jest.fn()}
          onOpenTimeline={jest.fn()}
          onOpenLogs={jest.fn()}
          onViewChunks={jest.fn()}
          onReprocess={jest.fn()}
          onOpenQueue={jest.fn()}
          onOpenPdfPreview={jest.fn()}
          reprocessingDocId={null}
          {...props}
        />
      </tbody>
    </table>,
  );

describe('Row selection', () => {
  test('administrators can tick a document', () => {
    const onToggleSelect = jest.fn();
    renderRow({ selected: true, onToggleSelect });
    const box = screen.getByLabelText(`Select ${TITLE}`);
    expect(box).toBeChecked();
    fireEvent.click(box);
    expect(onToggleSelect).toHaveBeenCalledWith(expect.objectContaining({ doc_id: 'd1' }));
  });

  test('no checkbox for everyone else', () => {
    renderRow({});
    expect(screen.queryByLabelText(`Select ${TITLE}`)).toBeNull();
  });
});

describe('Group defaults for document summaries', () => {
  test('only the keys that are set are saved', () => {
    expect(docSummaryPayload({ docSummaryMode: 'single_prompt', docSummarySectionTypes: [], docSummaryPrompt: '  ' })).toEqual({
      docSummaryMode: 'single_prompt',
    });
    expect(docSummaryPayload({ docSummarySectionTypes: ['findings'], docSummaryPrompt: 'Mine.' })).toEqual({
      docSummarySectionTypes: ['findings'],
      docSummaryPrompt: 'Mine.',
    });
  });

  test('reads the keys from a group, ignoring blanks', () => {
    expect(readDocSummaryDefaults(null)).toEqual({});
    expect(
      readDocSummaryDefaults({ docSummaryMode: '', docSummaryPrompt: 'Mine.', docSummarySectionTypes: ['findings'] }),
    ).toEqual({ docSummaryPrompt: 'Mine.', docSummarySectionTypes: ['findings'] });
  });
});

describe('Summary provenance', () => {
  const AT = '2026-10-06T17:55:00Z';

  test('a summary changed in the app says how, by whom and when', () => {
    expect(
      summaryProvenance({
        summary_user_set: true,
        summarization_method: 'ui_edited',
        summary_updated_by: 'admin@example.org',
        summary_updated_at: AT,
      }),
    ).toEqual({ label: 'Edited by admin@example.org', at: AT });
    expect(
      summaryProvenance({ summary_user_set: true, summarization_method: 'ui_single_prompt', summary_updated_at: AT })?.label,
    ).toBe('Regenerated with AI (single prompt)');
    expect(summaryProvenance({ summary_user_set: true, summarization_method: 'ui_map_reduce', summary_updated_by: 'a@b.org' })?.label).toBe(
      'Regenerated with AI (map reduce) by a@b.org',
    );
  });

  test('a pipeline summary says when the pipeline wrote it', () => {
    expect(summaryProvenance({ stages: { summarize: { at: AT, method: 'llm_summary' } } })).toEqual({
      label: 'Written by the pipeline',
      at: AT,
    });
    expect(summaryProvenance({ stages: { summarize: { at: AT, method: 'centroid_only' } } })?.label).toMatch(
      /key sentences, no AI summary/,
    );
    expect(summaryProvenance({ stages: {} })).toBeNull();
    expect(summaryProvenance(null)).toBeNull();
  });

  test('the cell shows it under the summary', () => {
    const provenance = { label: 'Edited by admin@example.org', at: AT };
    render(<DocumentsSummaryCell summary={SUMMARY} docTitle={TITLE} onOpenSummary={jest.fn()} provenance={provenance} />);
    expect(screen.getByText(formatProvenance(provenance))).toBeInTheDocument();
    expect(formatProvenance(provenance)).toMatch(/^Edited by admin@example\.org · .*2026/);
  });
});
