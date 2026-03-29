import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';

// This file tests the legacy key section separately so the mock can be set
// before the module is imported (jest.mock is hoisted, jest.doMock is not).
jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  API_KEY: 'legacy-static-key-abc123', // pragma: allowlist secret
}));

jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

import ApiKeyManager from '../components/admin/ApiKeyManager';

describe('ApiKeyManager — legacy key', () => {
  test('shows Legacy Key section and value when API_KEY is set', async () => {
    mockedAxios.get.mockResolvedValue({ data: [] });
    render(<ApiKeyManager />);
    await waitFor(() => {
      expect(screen.getByText('Legacy Key')).toBeInTheDocument();
    });
    expect(screen.getByDisplayValue('legacy-static-key-abc123')).toBeInTheDocument();
  });

  test('Copy button for legacy key is enabled', async () => {
    mockedAxios.get.mockResolvedValue({ data: [] });
    render(<ApiKeyManager />);
    await waitFor(() => {
      expect(screen.getByText('Legacy Key')).toBeInTheDocument();
    });
    // Two Copy buttons: one for generated key (disabled, no key), one for legacy (enabled)
    const copyButtons = screen.getAllByText('Copy');
    expect(copyButtons).toHaveLength(2);
    expect(copyButtons[0]).toBeDisabled();   // generated key — none exists
    expect(copyButtons[1]).not.toBeDisabled(); // legacy key
  });
});
