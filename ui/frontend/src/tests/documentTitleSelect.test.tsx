import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';
import DocumentTitleSelect from '../components/admin/testing/DocumentTitleSelect';

jest.mock('../config', () => ({ __esModule: true, default: '/api' }));
jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

describe('DocumentTitleSelect', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders selected titles as chips and removes on click', () => {
    const onChange = jest.fn();
    render(
      <DocumentTitleSelect
        dataSource="uneg"
        value={['Report A', 'Report B']}
        onChange={onChange}
      />,
    );
    expect(screen.getByText('Report A')).toBeInTheDocument();
    expect(screen.getByText('Report B')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Remove Report A'));
    expect(onChange).toHaveBeenCalledWith(['Report B']);
  });

  test('disables the input when no data source is set', () => {
    render(<DocumentTitleSelect dataSource="" value={[]} onChange={jest.fn()} />);
    expect(screen.getByPlaceholderText(/no data source/i)).toBeDisabled();
  });

  test('fetches and adds a suggested title, excluding already-selected ones', async () => {
    mockedAxios.get.mockResolvedValue({
      data: { documents: [{ title: 'Report A' }, { title: 'Report C' }] },
    });
    const onChange = jest.fn();
    render(
      <DocumentTitleSelect dataSource="uneg" value={['Report A']} onChange={onChange} />,
    );
    fireEvent.change(screen.getByPlaceholderText(/type to search/i), {
      target: { value: 'Rep' },
    });
    // Only the not-yet-selected suggestion is offered.
    const suggestion = await screen.findByRole('button', { name: 'Report C' });
    await waitFor(() =>
      expect(mockedAxios.get).toHaveBeenCalledWith(
        '/api/documents',
        expect.objectContaining({
          params: expect.objectContaining({ data_source: 'uneg', title: 'Rep' }),
        }),
      ),
    );
    expect(screen.queryByRole('button', { name: 'Report A' })).not.toBeInTheDocument();
    fireEvent.click(suggestion);
    expect(onChange).toHaveBeenCalledWith(['Report A', 'Report C']);
  });
});
