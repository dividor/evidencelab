import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import axios from 'axios';

import { DocumentModerationCell } from '../components/documents/DocumentActionsCell';
import { DocumentStatusCell } from '../components/documents/DocumentStatusCell';
import { setDocumentHidden } from '../components/documents/documentsActions';

jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

const renderInRow = (cell: React.ReactElement) =>
  render(
    <table>
      <tbody>
        <tr>{cell}</tr>
      </tbody>
    </table>
  );

describe('DocumentModerationCell', () => {
  test('offers Hide for a visible document and calls back with the document', () => {
    const doc = { id: 'd1', title: 'Doc', hidden: false };
    const onToggleHidden = jest.fn();
    renderInRow(
      <DocumentModerationCell doc={doc} moderatingDocId={null} onToggleHidden={onToggleHidden} />
    );

    const button = screen.getByRole('button', { name: 'Hide' });
    fireEvent.click(button);

    expect(onToggleHidden).toHaveBeenCalledWith(doc);
  });

  test('offers Restore for a hidden document', () => {
    renderInRow(
      <DocumentModerationCell
        doc={{ id: 'd1', hidden: true }}
        moderatingDocId={null}
        onToggleHidden={jest.fn()}
      />
    );
    expect(screen.getByRole('button', { name: 'Restore' })).toBeInTheDocument();
  });

  test('is disabled while its own request is in flight', () => {
    renderInRow(
      <DocumentModerationCell
        doc={{ id: 'd1', hidden: false }}
        moderatingDocId="d1"
        onToggleHidden={jest.fn()}
      />
    );
    const button = screen.getByRole('button', { name: 'Saving...' });
    expect(button).toBeDisabled();
  });

  test('renders nothing actionable for a row without an id', () => {
    renderInRow(
      <DocumentModerationCell doc={{}} moderatingDocId={null} onToggleHidden={jest.fn()} />
    );
    expect(screen.queryByRole('button')).toBeNull();
  });
});

describe('DocumentStatusCell hidden badge', () => {
  test('shows a hidden badge with the reason when the document is hidden', () => {
    renderInRow(
      <DocumentStatusCell
        doc={{ id: 'd1', status: 'indexed', hidden: true, hidden_reason: 'copyright' }}
        onOpenTimeline={jest.fn()}
        onOpenLogs={jest.fn()}
      />
    );
    const badge = screen.getByText('hidden');
    expect(badge).toHaveAttribute('title', 'Hidden: copyright');
  });

  test('shows no badge for a visible document', () => {
    renderInRow(
      <DocumentStatusCell
        doc={{ id: 'd1', status: 'indexed' }}
        onOpenTimeline={jest.fn()}
        onOpenLogs={jest.fn()}
      />
    );
    expect(screen.queryByText('hidden')).toBeNull();
  });
});

describe('setDocumentHidden', () => {
  beforeEach(() => {
    mockedAxios.post.mockReset();
  });

  test('posts to the moderation endpoint and refreshes on success', async () => {
    mockedAxios.post.mockResolvedValue({ data: { doc_id: 'd1', hidden: true } });
    const setModeratingDocId = jest.fn();
    const onRefresh = jest.fn();

    await setDocumentHidden({
      doc: { id: 'd1' },
      dataSource: 'uneg',
      hidden: true,
      reason: 'copyright',
      moderatingDocId: null,
      setModeratingDocId,
      onRefresh,
    });

    expect(mockedAxios.post).toHaveBeenCalledWith(
      expect.stringMatching(/\/moderation\/documents\/d1\/hidden$/),
      { hidden: true, reason: 'copyright' },
      { params: { data_source: 'uneg' } }
    );
    expect(onRefresh).toHaveBeenCalled();
    expect(setModeratingDocId).toHaveBeenNthCalledWith(1, 'd1');
    expect(setModeratingDocId).toHaveBeenLastCalledWith(null);
  });

  test('sends a null reason when restoring without one', async () => {
    mockedAxios.post.mockResolvedValue({ data: {} });

    await setDocumentHidden({
      doc: { id: 'd1' },
      dataSource: 'uneg',
      hidden: false,
      moderatingDocId: null,
      setModeratingDocId: jest.fn(),
      onRefresh: jest.fn(),
    });

    expect(mockedAxios.post.mock.calls[0][1]).toEqual({ hidden: false, reason: null });
  });

  test('does nothing while another request is in flight', async () => {
    await setDocumentHidden({
      doc: { id: 'd2' },
      dataSource: 'uneg',
      hidden: true,
      moderatingDocId: 'd1',
      setModeratingDocId: jest.fn(),
      onRefresh: jest.fn(),
    });
    expect(mockedAxios.post).not.toHaveBeenCalled();
  });

  test('clears the in-flight id and rethrows when the request fails', async () => {
    mockedAxios.post.mockRejectedValue(new Error('403'));
    const setModeratingDocId = jest.fn();

    await expect(
      setDocumentHidden({
        doc: { id: 'd1' },
        dataSource: 'uneg',
        hidden: true,
        moderatingDocId: null,
        setModeratingDocId,
        onRefresh: jest.fn(),
      })
    ).rejects.toThrow('403');
    expect(setModeratingDocId).toHaveBeenLastCalledWith(null);
  });
});
