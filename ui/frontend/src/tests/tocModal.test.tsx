import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';

import TocModal from '../components/TocModal';

jest.mock('axios');
jest.mock('../config', () => ({
  ...jest.requireActual('../config'),
  USER_FEEDBACK: true,
}));

// Editing the contents is an administrator action; the API refuses everyone
// else, so the modal only shows the controls to a superuser.
let mockUser: { is_superuser: boolean } | null = { is_superuser: true };
jest.mock('../hooks/useAuth', () => ({
  ...jest.requireActual('../hooks/useAuth'),
  useAuth: () => ({ user: mockUser }),
}));

const mockedAxios = axios as jest.Mocked<typeof axios>;

jest.setTimeout(20000);

describe('TocModal', () => {
  beforeEach(() => {
    mockUser = { is_superuser: true };
  });

  test('updates toc category and notifies parent', async () => {
    mockedAxios.put.mockResolvedValueOnce({ data: {} });

    const onTocUpdated = jest.fn();
    render(
      <TocModal
        isOpen={true}
        onClose={jest.fn()}
        toc="[H2] Intro | other | page 1"
        docId="doc-1"
        dataSource="uneg"
        loading={false}
        onTocUpdated={onTocUpdated}
      />
    );

    fireEvent.change(screen.getByDisplayValue('other'), {
      target: { value: 'findings' },
    });

    await waitFor(() => expect(mockedAxios.put).toHaveBeenCalled());
    await waitFor(() =>
      expect(onTocUpdated).toHaveBeenCalledWith(
        '[H2] Intro | findings | page 1'
      )
    );
  });

  test('toggles approval and calls API', async () => {
    mockedAxios.patch.mockResolvedValueOnce({ data: {} });
    const onTocApprovedChange = jest.fn();

    render(
      <TocModal
        isOpen={true}
        onClose={jest.fn()}
        toc="[H2] Intro | other"
        docId="doc-2"
        dataSource="uneg"
        loading={false}
        tocApproved={false}
        onTocApprovedChange={onTocApprovedChange}
      />
    );

    fireEvent.click(screen.getByRole('checkbox'));

    await waitFor(() => expect(mockedAxios.patch).toHaveBeenCalled());
    await waitFor(() => expect(onTocApprovedChange).toHaveBeenCalledWith(true));
  });

  test.each([
    ['signed out', null],
    ['not an administrator', { is_superuser: false }],
  ])('shows no edit controls when %s', (_label, user) => {
    mockUser = user;
    render(
      <TocModal
        isOpen={true}
        onClose={jest.fn()}
        toc="[H2] Intro | other | page 1"
        docId="doc-3"
        dataSource="uneg"
        loading={false}
      />
    );

    expect(screen.queryByDisplayValue('other')).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.getByText(/Intro/)).toBeInTheDocument();
  });
});
