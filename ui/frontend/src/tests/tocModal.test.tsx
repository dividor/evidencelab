import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';

import TocModal from '../components/TocModal';

jest.mock('axios');

const mockedAxios = axios as jest.Mocked<typeof axios>;

jest.setTimeout(20000);

describe('TocModal', () => {
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
});
