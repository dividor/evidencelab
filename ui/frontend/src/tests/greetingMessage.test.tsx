import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import axios from 'axios';
import { SearchBox } from '../components/SearchBox';
import {
  getSearchStateFromURL,
  mergeGroupSettings,
  SYSTEM_DEFAULTS,
  DEFAULT_SECTION_TYPES,
} from '../utils/searchUrl';
import type { SearchSettings } from '../types/auth';

jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

jest.mock('../../src/config', () => ({
  __esModule: true,
  default: '/api',
}));

// ---------------------------------------------------------------------------
// SearchBox greeting message tests
// ---------------------------------------------------------------------------

describe('SearchBox greetingMessage', () => {
  const baseProps = {
    isActive: true,
    hasSearched: false,
    query: '',
    loading: false,
    searchError: null,
    onQueryChange: jest.fn(),
    onSubmit: jest.fn(),
    datasetName: 'Reports',
    documentCount: 1500,
  };

  test('shows default placeholder when no greetingMessage', () => {
    render(<SearchBox {...baseProps} />);
    const input = screen.getByPlaceholderText('Search 1,500 Reports');
    expect(input).toBeInTheDocument();
  });

  test('shows greetingMessage as placeholder on landing page', () => {
    render(<SearchBox {...baseProps} greetingMessage="What are you looking for today?" />);
    const input = screen.getByPlaceholderText('What are you looking for today?');
    expect(input).toBeInTheDocument();
  });

  test('shows default placeholder on results page even when greetingMessage set', () => {
    render(
      <SearchBox {...baseProps} hasSearched={true} greetingMessage="What are you looking for today?" />
    );
    const input = screen.getByPlaceholderText('Search 1,500 Reports');
    expect(input).toBeInTheDocument();
  });

  test('shows default placeholder when greetingMessage is empty string', () => {
    render(<SearchBox {...baseProps} greetingMessage="" />);
    const input = screen.getByPlaceholderText('Search 1,500 Reports');
    expect(input).toBeInTheDocument();
  });

  test('shows default placeholder when greetingMessage is whitespace only', () => {
    render(<SearchBox {...baseProps} greetingMessage="   " />);
    const input = screen.getByPlaceholderText('Search 1,500 Reports');
    expect(input).toBeInTheDocument();
  });

  test('trims greetingMessage whitespace', () => {
    render(<SearchBox {...baseProps} greetingMessage="  Hello world  " />);
    const input = screen.getByPlaceholderText('Hello world');
    expect(input).toBeInTheDocument();
  });

  test('falls back to generic placeholder when no datasetName/count', () => {
    render(
      <SearchBox
        {...baseProps}
        datasetName={undefined}
        documentCount={undefined}
        greetingMessage={undefined}
      />
    );
    const input = screen.getByPlaceholderText('Search documents');
    expect(input).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// SYSTEM_DEFAULTS includes greetingMessage
// ---------------------------------------------------------------------------

describe('SYSTEM_DEFAULTS greetingMessage', () => {
  test('includes greetingMessage as empty string', () => {
    expect(SYSTEM_DEFAULTS.greetingMessage).toBe('');
  });
});

// ---------------------------------------------------------------------------
// mergeGroupSettings with greetingMessage
// ---------------------------------------------------------------------------

describe('mergeGroupSettings with greetingMessage', () => {
  test('includes greetingMessage from group settings', () => {
    const result = mergeGroupSettings([
      { search_settings: { greetingMessage: 'Welcome!' } },
    ]);
    expect(result).toEqual({ greetingMessage: 'Welcome!' });
  });

  test('first non-null greetingMessage wins', () => {
    const result = mergeGroupSettings([
      { search_settings: { greetingMessage: 'First' } },
      { search_settings: { greetingMessage: 'Second' } },
    ]);
    expect(result.greetingMessage).toBe('First');
  });

  test('skips groups without greetingMessage', () => {
    const result = mergeGroupSettings([
      { search_settings: { denseWeight: 0.5 } },
      { search_settings: { greetingMessage: 'Hello' } },
    ]);
    expect(result.greetingMessage).toBe('Hello');
    expect(result.denseWeight).toBe(0.5);
  });
});

// ---------------------------------------------------------------------------
// GroupSettingsManager greetingMessage UI
// ---------------------------------------------------------------------------

import GroupSettingsManager from '../components/admin/GroupSettingsManager';

const mockGroups = [
  {
    id: 'g1',
    name: 'TestGroup',
    description: 'Test',
    is_default: true,
    created_at: '2026-01-01T00:00:00Z',
    datasource_keys: [],
    member_count: 5,
    search_settings: { greetingMessage: 'Welcome to the portal' },
  },
];

describe('GroupSettingsManager greetingMessage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedAxios.get.mockResolvedValue({ data: mockGroups });
  });

  test('shows Appearance section header', async () => {
    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText('Appearance')).toBeInTheDocument();
    });
  });

  test('shows override greeting message checkbox', async () => {
    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText('Override greeting message')).toBeInTheDocument();
    });
  });

  test('loads greetingMessage value from group settings', async () => {
    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText('Override greeting message')).toBeInTheDocument();
    });

    // The greeting message input should show the saved value
    const input = screen.getByDisplayValue('Welcome to the portal');
    expect(input).toBeInTheDocument();
  });

  test('saves greetingMessage in search_settings payload', async () => {
    mockedAxios.patch.mockResolvedValue({ data: { ...mockGroups[0] } });

    render(<GroupSettingsManager />);
    await waitFor(() => {
      expect(screen.getByText('Save Settings')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Save Settings'));

    await waitFor(() => {
      expect(mockedAxios.patch).toHaveBeenCalledWith('/api/groups/g1', {
        search_settings: expect.objectContaining({ greetingMessage: 'Welcome to the portal' }),
        summary_prompt: '',
      });
    });
  });
});
