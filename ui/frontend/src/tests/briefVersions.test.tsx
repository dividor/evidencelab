import React from 'react';
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { ReviewBar, SectionVersionView, useSectionChanges } from '../components/brief/BriefSectionChanges';
import { BriefSectionAudit } from '../components/brief/BriefSectionAudit';
import { BriefVersionsModal } from '../components/brief/BriefVersionsModal';
import { BriefSection, SectionAuditEntry } from '../components/brief/briefTypes';
import * as versionsApi from '../components/brief/briefVersionsApi';

jest.mock('../config', () => ({ __esModule: true, default: '/api', API_KEY: undefined, USER_MODULE: true }));
jest.mock('../components/brief/briefVersionsApi');

const mocked = versionsApi as jest.Mocked<typeof versionsApi>;

const entry = (over: Partial<SectionAuditEntry>): SectionAuditEntry => ({
  id: 'a-r1',
  kind: 'edit',
  at: Date.UTC(2026, 10, 13, 10, 0),
  before: 'Old words here.',
  after: 'New words here.',
  ...over,
});

describe('review bar for a change awaiting Keep or Reject', () => {
  test('offers Hide Changes, Keep Edits and Reject Edits', () => {
    const onToggle = jest.fn();
    const onKeep = jest.fn();
    const onReject = jest.fn();
    render(
      <ReviewBar kind="generate" showingChanges onToggle={onToggle} onKeep={onKeep} onReject={onReject} />,
    );
    expect(screen.getByText('Changes from the regeneration')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Hide Changes' }));
    fireEvent.click(screen.getByRole('button', { name: 'Keep Edits' }));
    fireEvent.click(screen.getByRole('button', { name: 'Reject Edits' }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(onKeep).toHaveBeenCalledTimes(1);
    expect(onReject).toHaveBeenCalledTimes(1);
  });

  test('reads Show Changes once the changes are hidden', () => {
    render(
      <ReviewBar kind="edit" showingChanges={false} onToggle={jest.fn()} onKeep={jest.fn()} onReject={jest.fn()} />,
    );
    expect(screen.getByRole('button', { name: 'Show Changes' })).toBeInTheDocument();
  });
});

describe('when a change awaiting review shows its tracked changes', () => {
  const awaiting = (runId: string | null): BriefSection =>
    ({
      id: 's1',
      title: 'Findings',
      level: 1,
      status: 'done',
      content: 'New words here.',
      sources: [],
      audit: [entry({ id: 'a-r1', runId: 'r1' }), entry({ id: 'a-r2', runId: 'r2' })],
      pendingReview: runId ? { runId, baseRunId: 'r1', kind: 'edit', at: 1, before: 'Old words here.' } : undefined,
    }) as BriefSection;

  test('a change already awaiting review when the brief opens shows plain text', () => {
    const { result } = renderHook(() => useSectionChanges(awaiting('r2'), false));
    expect(result.current.pendingRunId).toBe('r2');
    expect(result.current.showingChanges).toBe(false);
  });

  test('a change made while the brief is open shows its tracked changes', () => {
    const { result, rerender } = renderHook(({ section }) => useSectionChanges(section, false), {
      initialProps: { section: awaiting(null) },
    });
    rerender({ section: awaiting('r2') });
    expect(result.current.showingChanges).toBe(true);
  });

  test('choosing the waiting change in Section History shows its tracked changes', () => {
    const { result } = renderHook(() => useSectionChanges(awaiting('r2'), false));
    act(() => result.current.openEntry('a-r2'));
    expect(result.current.showingChanges).toBe(true);
    expect(result.current.versionEntry).toBeNull();
  });
});

describe('an earlier section version opened from the Log', () => {
  test('shows tracked changes and only the restore button', () => {
    const onRestore = jest.fn();
    const { container } = render(
      <SectionVersionView entry={entry({ restorable: true })} canRestore onRestore={onRestore} onClose={jest.fn()} />,
    );
    expect(container.querySelector('del')).toHaveTextContent('Old');
    expect(container.querySelector('ins')).toHaveTextContent('New');
    const buttons = screen.getAllByRole('button');
    expect(buttons.map((b) => b.textContent)).toEqual(['Restore this section version', '×']);
    fireEvent.click(screen.getByRole('button', { name: 'Restore this section version' }));
    expect(onRestore).toHaveBeenCalledTimes(1);
  });

  test('a viewer or the current version gets no restore button', () => {
    render(<SectionVersionView entry={entry({ current: true })} canRestore={false} onRestore={jest.fn()} onClose={jest.fn()} />);
    expect(screen.queryByText('Restore this section version')).not.toBeInTheDocument();
    expect(screen.getByText(/current version/)).toBeInTheDocument();
  });
});

describe('section Log', () => {
  test('labels current, rejected, awaiting-review and restored rows; rows with text open', () => {
    const onShow = jest.fn();
    render(
      <BriefSectionAudit
        title="Findings"
        audit={[
          entry({ id: 'a-r1', kind: 'generate', before: '', current: false }),
          entry({ id: 'a-r2', status: 'rejected', runId: 'r2' }),
          entry({ id: 'a-r3', kind: 'restore', runId: 'r3', restoredFrom: { version: 4 }, current: true }),
          entry({ id: 'a-r4', kind: 'generate', before: undefined, after: undefined }),
        ]}
        pendingRunId="r3"
        onShowChanges={onShow}
        onClose={jest.fn()}
      />,
    );
    expect(screen.getByText('Section History')).toBeInTheDocument();
    expect(screen.getByText('Restored')).toBeInTheDocument();
    expect(screen.getByText('· rejected')).toBeInTheDocument();
    expect(screen.getByText('· current')).toBeInTheDocument();
    expect(screen.getByText('· awaiting review')).toBeInTheDocument();
    expect(screen.getByText('With the whole brief, to version 4')).toBeInTheDocument();
    // Three rows carry text and open; the legacy row without text does not.
    expect(screen.getAllByText('· view changes')).toHaveLength(3);
    const rows = screen.getAllByTitle('View this version, compared with the version before it');
    expect(rows).toHaveLength(3);
    fireEvent.click(rows[0]);
    expect(onShow).toHaveBeenCalledWith('a-r3');
  });
});

describe('brief log (whole-brief versions)', () => {
  beforeEach(() => {
    mocked.listBriefVersions.mockResolvedValue([
      {
        number: 2,
        kind: 'edit',
        section_id: 's1',
        summary: 'Edited “Findings” with AI',
        author_name: 'Jan',
        created_at: '2026-11-13T10:00:00Z',
        updated_at: '2026-11-13T10:00:00Z',
        is_current: true,
      },
      {
        number: 1,
        kind: 'created',
        section_id: null,
        summary: 'Created the brief',
        author_name: 'Jan',
        created_at: '2026-11-13T09:00:00Z',
        updated_at: '2026-11-13T09:00:00Z',
        is_current: false,
      },
    ]);
    mocked.getBriefVersion.mockImplementation(async (_id, number) => ({
      number,
      kind: number === 1 ? 'created' : 'edit',
      section_id: null,
      summary: number === 1 ? 'Created the brief' : 'Edited “Findings” with AI',
      author_name: 'Jan',
      created_at: '2026-11-13T09:00:00Z',
      updated_at: '2026-11-13T09:00:00Z',
      is_current: number === 2,
      previous_number: number === 1 ? null : 1,
      title: 'Food security brief',
      settings: [],
      can_restore: number !== 2,
      sections: [
        { id: 's1', title: 'Findings', level: 1, change: 'changed', before: 'Old.', after: 'New.', beforeTitle: 'Findings' },
        { id: 's2', title: 'Gone', level: 1, change: 'removed', before: 'Bye.', after: null, beforeTitle: null },
      ],
    }));
  });

  test('lists versions, shows the newest with tracked changes, restores an older one', async () => {
    const onRestore = jest.fn().mockResolvedValue(undefined);
    const onClose = jest.fn();
    const { container } = render(<BriefVersionsModal briefId="b1" onRestore={onRestore} onClose={onClose} />);
    expect(await screen.findByText('Version 2')).toBeInTheDocument();
    expect(screen.getByText('Document History')).toBeInTheDocument();
    expect(container.querySelector('.brief-version-section-removed')).toHaveTextContent('Gone');
    // The current version cannot be restored.
    expect(screen.queryByText('Restore whole brief to this version')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('option', { name: /v1/ }));
    fireEvent.click(await screen.findByRole('button', { name: 'Restore whole brief to this version' }));
    await waitFor(() => expect(onRestore).toHaveBeenCalledWith(1));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  test('an unsaved brief explains that its log starts with the first save', () => {
    render(<BriefVersionsModal briefId={null} onRestore={jest.fn()} onClose={jest.fn()} />);
    expect(screen.getByText(/its log starts with the first save/)).toBeInTheDocument();
  });
});
