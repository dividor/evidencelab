import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';

jest.mock('../config', () => ({ __esModule: true, default: '/api' }));
jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

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
  beforeEach(() => jest.clearAllMocks());

  test('shows loading state initially', () => {
    mockedAxios.get.mockReturnValue(new Promise(() => {}));
    render(<ApiKeyManager />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  test('shows Generate button and disabled Copy when no key exists', async () => {
    mockedAxios.get.mockResolvedValue({ data: [] });
    render(<ApiKeyManager />);
    await waitFor(() => expect(screen.getByText('Generate')).toBeInTheDocument());
    expect(screen.getByText('Copy')).toBeDisabled();
  });

  test('shows key prefix, disabled Copy, and Regenerate when key exists (full key not available)', async () => {
    mockedAxios.get.mockResolvedValue({ data: [mockActiveKey] });
    render(<ApiKeyManager />);
    await waitFor(() => expect(screen.getByText('Regenerate')).toBeInTheDocument());
    // Copy is disabled — full key is only available immediately after generation, not on subsequent loads
    expect(screen.getByText('Copy')).toBeDisabled();
    expect(screen.getByDisplayValue(/el_abc12ab/)).toBeInTheDocument();
  });

  test('shows confirmation dialog before regenerating', async () => {
    mockedAxios.get.mockResolvedValue({ data: [mockActiveKey] });
    render(<ApiKeyManager />);
    await waitFor(() => expect(screen.getByText('Regenerate')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Regenerate'));
    expect(screen.getByText('Regenerate API Key')).toBeInTheDocument();
    expect(screen.getByText(/This will revoke/)).toBeInTheDocument();
  });

  test('generates key and shows revealed value with warning', async () => {
    const createdKey = { ...mockActiveKey, id: 'key-new', key: 'el_new123full-secret' };
    mockedAxios.get.mockResolvedValueOnce({ data: [] }).mockResolvedValueOnce({ data: [createdKey] });
    mockedAxios.post.mockResolvedValue({ data: createdKey });
    render(<ApiKeyManager />);
    await waitFor(() => expect(screen.getByText('Generate')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Generate'));
    await waitFor(() => expect(screen.getByText(/will not be shown again/)).toBeInTheDocument());
  });

  test('shows error on fetch failure', async () => {
    mockedAxios.get.mockRejectedValue(new Error('Network error'));
    render(<ApiKeyManager />);
    await waitFor(() => expect(screen.getByText('Failed to load API key')).toBeInTheDocument());
  });

  test('dismisses error on close click', async () => {
    mockedAxios.get.mockRejectedValue(new Error('fail'));
    render(<ApiKeyManager />);
    await waitFor(() => expect(screen.getByText('Failed to load API key')).toBeInTheDocument());
    fireEvent.click(screen.getByText('\u00d7'));
    expect(screen.queryByText('Failed to load API key')).not.toBeInTheDocument();
  });

  test('shows creation date and email', async () => {
    mockedAxios.get.mockResolvedValue({ data: [mockActiveKey] });
    render(<ApiKeyManager />);
    await waitFor(() => expect(screen.getByText(/Created/)).toBeInTheDocument());
    expect(screen.getByText(/admin@test.com/)).toBeInTheDocument();
  });
});
