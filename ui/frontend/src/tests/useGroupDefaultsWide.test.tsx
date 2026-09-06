import React from 'react';
import { render, waitFor } from '@testing-library/react';
import axios from 'axios';
import { useGroupDefaults } from '../hooks/useGroupDefaults';
import type { SearchSettings } from '../types/auth';

jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

jest.mock('../../src/config', () => ({
  __esModule: true,
  default: '/api',
}));

const SETTING_KEYS: (keyof SearchSettings)[] = [
  'denseWeight', 'rerank', 'recencyBoost', 'recencyWeight', 'recencyScaleDays', 'sectionTypes',
  'keywordBoostShortQueries', 'minChunkSize', 'semanticHighlighting', 'autoMinScore', 'deduplicate',
  'fieldBoost', 'fieldBoostFields', 'wideSearch', 'wideGroupSize', 'wideLimit', 'summaryLimitResults',
  'summaryMaxResults', 'summaryTemperature', 'greetingMessage',
];

const makeSetters = () =>
  Object.fromEntries(SETTING_KEYS.map((k) => [k, jest.fn()])) as Record<keyof SearchSettings, jest.Mock>;

const Harness: React.FC<{ setters: Record<keyof SearchSettings, jest.Mock> }> = ({ setters }) => {
  useGroupDefaults(true, { isLoading: false, isAuthenticated: true, user: { id: 'u1' } }, setters);
  return null;
};

describe('useGroupDefaults applies wide search team defaults', () => {
  const originalLocation = window.location;
  afterEach(() => {
    Object.defineProperty(window, 'location', { value: originalLocation, writable: true });
    jest.clearAllMocks();
  });
  const setURL = (search: string) =>
    Object.defineProperty(window, 'location', { value: { ...originalLocation, search }, writable: true });

  test('applies wideSearch, wideGroupSize and wideLimit when the URL does not set them', async () => {
    setURL('?q=test');
    mockedAxios.get.mockResolvedValue({ data: { wideSearch: true, wideGroupSize: 3, wideLimit: 40 } });
    const setters = makeSetters();
    render(<Harness setters={setters} />);
    await waitFor(() => expect(setters.wideSearch).toHaveBeenCalledWith(true));
    expect(setters.wideGroupSize).toHaveBeenCalledWith(3);
    expect(setters.wideLimit).toHaveBeenCalledWith(40);
  });

  test('applies the AI summary cap team defaults', async () => {
    setURL('?q=test');
    mockedAxios.get.mockResolvedValue({ data: { summaryLimitResults: false, summaryMaxResults: 60, summaryTemperature: 0.4 } });
    const setters = makeSetters();
    render(<Harness setters={setters} />);
    await waitFor(() => expect(setters.summaryLimitResults).toHaveBeenCalledWith(false));
    expect(setters.summaryMaxResults).toHaveBeenCalledWith(60);
    expect(setters.summaryTemperature).toHaveBeenCalledWith(0.4);
  });

  test('a URL value wins over the team default for that key only', async () => {
    setURL('?q=test&wide_limit=9');
    mockedAxios.get.mockResolvedValue({ data: { wideSearch: true, wideGroupSize: 3, wideLimit: 40 } });
    const setters = makeSetters();
    render(<Harness setters={setters} />);
    await waitFor(() => expect(setters.wideSearch).toHaveBeenCalledWith(true));
    expect(setters.wideGroupSize).toHaveBeenCalledWith(3);
    expect(setters.wideLimit).not.toHaveBeenCalled();
  });
});
