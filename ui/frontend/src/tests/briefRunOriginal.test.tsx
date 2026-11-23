import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { UnresolvedCitationsWarning } from '../components/brief/BriefDocument';
import { BriefRunOriginal } from '../components/brief/BriefRunOriginal';
import { BriefSectionAudit } from '../components/brief/BriefSectionAudit';
import { SectionRunDetail, SectionRunSummary } from '../components/brief/briefTypes';

jest.mock('../config', () => ({ __esModule: true, default: '/api', API_KEY: undefined, USER_MODULE: true }));

const run = (over: Partial<SectionRunSummary> = {}): SectionRunSummary => ({
  id: 'r1',
  mode: 'generate',
  at: Date.UTC(2026, 10, 20, 17, 43),
  status: 'current',
  sourcesRetained: 'exact',
  mapping: { '1': 's1', '2': 's2' },
  unresolved: [],
  rejected: [],
  sourceCount: 2,
  citedCount: 1,
  ...over,
});

const detail = (over: Partial<SectionRunDetail> = {}): SectionRunDetail => ({
  ...run(),
  runId: '47665ba4-0af1-4cc3-a3a9-f459fc619353',
  sectionId: 'a',
  content: 'Cash helps [2]. Planning converges [2, 25].',
  sources: [
    { index: 1, chunkId: 'c-1', title: 'Resilience evaluation', page: 8 },
    { index: 2, chunkId: 'c-2', title: 'Cash transfers review', page: 14 },
  ] as SectionRunDetail['sources'],
  displayNumbers: { '2': 1 },
  unresolved: [{ n: 25, reason: 'no-source' }],
  ...over,
});

const auditOf = (onViewOriginal: (runId: string) => void, canViewOriginal: boolean) => (
  <BriefSectionAudit
    title="Findings"
    audit={[
      { id: 'a-r1', kind: 'generate', at: Date.now(), runId: 'r1', before: '', after: 'Text.' },
      { id: 'a-r0', kind: 'generate', at: Date.now() - 1000, runId: 'r0' },
    ]}
    pendingRunId={null}
    onShowChanges={jest.fn()}
    runs={[run()]}
    canViewOriginal={canViewOriginal}
    onViewOriginal={onViewOriginal}
    onClose={jest.fn()}
  />
);

describe('Section History: Original link', () => {
  test('an administrator can open a retained original and sees which are gone', () => {
    const onView = jest.fn();
    render(auditOf(onView, true));
    fireEvent.click(screen.getByRole('button', { name: '· Original' }));
    expect(onView).toHaveBeenCalledWith('r1');
    expect(screen.getByText('· original no longer retained')).toBeInTheDocument();
  });

  test('for other users no row mentions an original', () => {
    render(auditOf(jest.fn(), false));
    expect(screen.queryByText('· Original')).not.toBeInTheDocument();
    expect(screen.queryByText('· original no longer retained')).not.toBeInTheDocument();
  });
});

describe('unresolved citations warning', () => {
  test('points an administrator at the original', () => {
    render(<UnresolvedCitationsWarning unresolved={[{ n: 25, reason: 'no-source' }]} canViewOriginal />);
    expect(screen.getByRole('status')).toHaveTextContent('shown as [?25]');
    expect(screen.getByRole('status')).toHaveTextContent('choose Original');
  });

  test('does not mention the original to other users', () => {
    render(<UnresolvedCitationsWarning unresolved={[{ n: 25, reason: 'no-source' }]} />);
    expect(screen.getByRole('status')).toHaveTextContent('a number it never returned.');
    expect(screen.getByRole('status')).not.toHaveTextContent('Original');
  });
});

describe('Original output modal', () => {
  test('summarises the run and lists each marker without a source once', () => {
    render(
      <BriefRunOriginal
        title="Findings"
        detail={detail({
          unresolved: [
            { n: 25, reason: 'no-source' },
            { n: 25, reason: 'no-source' },
            { n: 44, reason: 'no-chunk-id' },
          ],
        })}
        error={null}
        onClose={jest.fn()}
      />,
    );
    const dialog = screen.getByRole('dialog', { name: 'Original output' });
    expect(within(dialog).getByText('r1 · Current')).toBeInTheDocument();
    expect(within(dialog).getByText('Exactly as returned')).toBeInTheDocument();
    expect(within(dialog).getByText('47665ba4-0af1-4cc3-a3a9-f459fc619353')).toBeInTheDocument();
    const notice = within(dialog).getByRole('status');
    expect(notice).toHaveTextContent('2 citation markers have no source');
    expect(within(notice).getAllByRole('listitem')).toHaveLength(2);
    expect(notice).toHaveTextContent('[44], shown to readers as [?44]: the source record had no chunk id.');
  });

  test('marks the markers without a source in the text and in the trace table', () => {
    const { container } = render(
      <BriefRunOriginal title="Findings" detail={detail()} error={null} onClose={jest.fn()} />,
    );
    const bad = container.querySelectorAll('.brief-original-marker-bad');
    expect(Array.from(bad).map((el) => el.textContent)).toEqual(['[2, 25]']);
    expect(container.querySelector('.brief-original-text')).toHaveTextContent(
      'Cash helps [2]. Planning converges [2, 25].',
    );
    const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1);
    expect(rows.map((r) => r.textContent)).toEqual([
      '[1]Not citeds1Resilience evaluation8c-1',
      '[2][1]s2Cash transfers review14c-2',
      '[25][?25]The agent returned no source with this number',
    ]);
  });

  test('an earlier run has no shown-as numbers and says why', () => {
    render(
      <BriefRunOriginal
        title="Findings"
        detail={detail({
          status: 'superseded',
          sourcesRetained: 'cited-without-excerpt',
          displayNumbers: {},
          unresolved: [],
        })}
        error={null}
        onClose={jest.fn()}
      />,
    );
    expect(screen.getByText(/Shown-as numbers apply to the current run only/)).toBeInTheDocument();
    expect(screen.getByText('r1 · Superseded')).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.queryByText('Not cited')).not.toBeInTheDocument();
  });

  test('shows a load error, a loading note, and closes', () => {
    const onClose = jest.fn();
    const { rerender } = render(
      <BriefRunOriginal title="Findings" detail={null} error={null} onClose={onClose} />,
    );
    expect(screen.getByText('Loading the stored original…')).toBeInTheDocument();
    rerender(<BriefRunOriginal title="Findings" detail={null} error="Not allowed" onClose={onClose} />);
    expect(screen.getByText('Not allowed')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalled();
  });
});
