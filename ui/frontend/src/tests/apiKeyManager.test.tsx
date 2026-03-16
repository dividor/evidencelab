import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';

// Mock config
jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
}));

// Mock axios
jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;
if (!mockedAxios.delete) {
  (mockedAxios as any).delete = jest.fn();
}

import ApiKeyManager from '../components/admin/ApiKeyManager';

const mockActiveKey = {
  id: 'key-1',
  label: 'API Key',
  key_prefix: 'el_abc12ab',
  is_active: true,
  created_at: '2026-01-15T00:00:00Z',
  created_by_email: 'admin@test.com',
  last_used_at: null,
};

describe('ApiKeyManager', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('shows loading state initially', () => {
    mockedAxios.get.mockReturnValue(new Promise(() => {}));
    render(<ApiKeyManager />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  test('shows Generate button when no key exists', async () => {
    mockedAxios.get.mockResolvedValue({ data: [] });
    render(<ApiKeyManager />);
    await waitFor(() => {
      expect(screen.getByText('Generate')).toBeInTheDocument();
    });
    expect(screen.getByPlaceholderText('No API key generated')).toBeInTheDocument();
  });

  test('shows masked key and Regenerate button when key exists', async () => {
    mockedAxios.get.mockResolvedValue({ data: [mockActiveKey] });
    render(<ApiKeyManager />);
    await waitFor(() => {
      expect(screen.getByText('Regenerate')).toBeInTheDocument();
    });
    const input = screen.getByDisplayValue(/el_abc12ab/);
    expect(input).toBeInTheDocument();
  });

  test('generates key on Generate click', async () => {
    const createdKey = {
      ...mockActiveKey,
      id: 'key-new',
      key: 'el_new123n-full-secret-key-value',
    };
    mockedAxios.get.mockResolvedValue({ data: [] });
    mockedAxios.post.mockResolvedValue({ data: createdKey });
    render(<ApiKeyManager />);
    await waitFor(() => {
      expect(screen.getByText('Generate')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(mockedAxios.post).toHaveBeenCalledWith('/api/api-keys/', {
        label: 'API Key',
      });
    });
  });

  test('shows confirmation dialog before regenerating', async () => {
    mockedAxios.get.mockResolvedValue({ data: [mockActiveKey] });
    render(<ApiKeyManager />);
    await waitFor(() => {
      expect(screen.getByText('Regenerate')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Regenerate'));

    expect(screen.getByText('Regenerate API Key')).toBeInTheDocument();
    expect(
      screen.getByText(/This will revoke the current key/)
    ).toBeInTheDocument();
  });

  test('shows revealed key with copy warning after generation', async () => {
    const createdKey = {
      ...mockActiveKey,
      id: 'key-new',
      key: 'el_new123n-full-secret-key-value',
    };
    mockedAxios.get
      .mockResolvedValueOnce({ data: [] })
      .mockResolvedValueOnce({ data: [createdKey] });
    mockedAxios.post.mockResolvedValue({ data: createdKey });
    render(<ApiKeyManager />);
    await waitFor(() => {
      expect(screen.getByText('Generate')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(
        screen.getByText(/will not be shown again/)
      ).toBeInTheDocument();
    });
  });

  test('Copy button disabled when no revealed key', async () => {
    mockedAxios.get.mockResolvedValue({ data: [mockActiveKey] });
    render(<ApiKeyManager />);
    await waitFor(() => {
      expect(screen.getByText('Copy')).toBeInTheDocument();
    });
    expect(screen.getByText('Copy')).toBeDisabled();
  });

  test('shows error on fetch failure', async () => {
    mockedAxios.get.mockRejectedValue(new Error('Network error'));
    render(<ApiKeyManager />);
    await waitFor(() => {
      expect(screen.getByText('Failed to load API key')).toBeInTheDocument();
    });
  });

  test('dismisses error on close click', async () => {
    mockedAxios.get.mockRejectedValue(new Error('fail'));
    render(<ApiKeyManager />);
    await waitFor(() => {
      expect(screen.getByText('Failed to load API key')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('\u00d7'));
    expect(
      screen.queryByText('Failed to load API key')
    ).not.toBeInTheDocument();
  });

  test('shows creation date when key exists', async () => {
    mockedAxios.get.mockResolvedValue({ data: [mockActiveKey] });
    render(<ApiKeyManager />);
    await waitFor(() => {
      expect(screen.getByText(/Created/)).toBeInTheDocument();
    });
    expect(screen.getByText(/admin@test.com/)).toBeInTheDocument();
  });
});
