import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';

jest.mock('../config', () => ({ __esModule: true, default: '/api' }));
jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

import CaseEditor from '../components/admin/testing/CaseEditor';
import type { TestCase } from '../types/testing';

// A config-driven facet response, as the /facets endpoint builds it from the
// data source's filter fields in config.json.
const FACETS = {
  facets: {
    src_evaluation_category: [
      { value: 'Centralized', count: 3 },
      { value: 'Decentralized', count: 5 },
    ],
    country: [{ value: 'Kenya', count: 4 }],
    language: [{ value: 'English', count: 9 }],
    published_year: [
      { value: '2020', count: 2 },
      { value: '2021', count: 7 },
    ],
  },
  filter_fields: {
    title: 'Document Title',
    src_evaluation_category: 'Evaluation Category',
    published_year: 'Year Published',
    country: 'Country',
    language: 'Language',
  },
  range_fields: {},
};

beforeEach(() => {
  jest.clearAllMocks();
  mockedAxios.get.mockImplementation((url: string) => {
    if (url.includes('/facets')) return Promise.resolve({ data: FACETS });
    return Promise.resolve({ data: {} });
  });
});

const COUNTRY_FIELD = 'Country (optional)';
const SUBMIT = 'Create Case';
const EXTRAS_LABEL = 'Other filters / params (read-only)';
const EDIT_QUERY = 'school feeding';

const renderEditor = (initialCase: TestCase | null = null) => {
  const onSubmit = jest.fn();
  render(
    <CaseEditor
      initialCase={initialCase}
      dataSource="wfp"
      saving={false}
      submitLabel={SUBMIT}
      onSubmit={onSubmit}
      onCancel={jest.fn()}
    />,
  );
  return onSubmit;
};

describe('CaseEditor', () => {
  test('renders one picker per config-declared filter field', async () => {
    renderEditor();
    await waitFor(() => screen.getByText('Document Title (optional)'));
    expect(screen.getByText('Evaluation Category (optional)')).toBeInTheDocument();
    expect(screen.getByText('Year Published (optional)')).toBeInTheDocument();
    expect(screen.getByText(COUNTRY_FIELD)).toBeInTheDocument();
    expect(screen.getByText('Language (optional)')).toBeInTheDocument();
    expect(mockedAxios.get).toHaveBeenCalledWith(
      expect.stringContaining('/facets'),
      expect.objectContaining({ params: { data_source: 'wfp' } }),
    );
  });

  test('omits fields the config does not declare', async () => {
    renderEditor();
    await waitFor(() => screen.getByText(COUNTRY_FIELD));
    expect(screen.queryByText('Region (optional)')).not.toBeInTheDocument();
  });

  test('selecting a facet value submits it under the field key', async () => {
    const onSubmit = renderEditor();
    await waitFor(() => screen.getByText('Evaluation Category (optional)'));
    const picker = screen.getByPlaceholderText('Type to filter evaluation category…');
    fireEvent.change(picker, { target: { value: 'Centr' } });
    fireEvent.click(screen.getByRole('button', { name: 'Centralized' }));
    fireEvent.change(screen.getByLabelText('Query'), { target: { value: 'q' } });
    fireEvent.click(screen.getByRole('button', { name: SUBMIT }));
    expect(onSubmit).toHaveBeenCalledWith({
      input: { query: 'q', filters: { src_evaluation_category: ['Centralized'] } },
      tags: undefined,
      notes: undefined,
    });
  });

  test('loads an existing case and preserves keys the builder does not own', async () => {
    const onSubmit = renderEditor({
      id: 'c1',
      input: {
        query: EDIT_QUERY,
        filters: { country: ['Kenya'], organization: 'WFP' },
        params: { rerank: true },
      },
    } as TestCase);
    await waitFor(() => screen.getByText(COUNTRY_FIELD));
    expect(screen.getByDisplayValue(EDIT_QUERY)).toBeInTheDocument();
    expect(screen.getByText('Kenya')).toBeInTheDocument();
    // Keys the config does not declare are shown read-only and kept on save.
    const extras = screen.getByLabelText(EXTRAS_LABEL) as HTMLTextAreaElement;
    expect(extras).toHaveAttribute('readOnly');
    expect(JSON.parse(extras.value)).toEqual({
      params: { rerank: true },
      filters: { organization: 'WFP' },
    });
    fireEvent.click(screen.getByRole('button', { name: SUBMIT }));
    expect(onSubmit).toHaveBeenCalledWith({
      input: {
        query: EDIT_QUERY,
        params: { rerank: true },
        filters: { organization: 'WFP', country: ['Kenya'] },
      },
      tags: undefined,
      notes: undefined,
    });
  });

  test('omits the read-only extras block when the builder owns every key', async () => {
    renderEditor();
    await waitFor(() => screen.getByText(COUNTRY_FIELD));
    expect(screen.queryByLabelText(EXTRAS_LABEL)).not.toBeInTheDocument();
  });

  test('keeps existing filters untouched when facets cannot load', async () => {
    mockedAxios.get.mockRejectedValue(new Error('boom'));
    const onSubmit = renderEditor({
      id: 'c1',
      input: { query: 'q', filters: { country: ['Kenya'] } },
    } as TestCase);
    await waitFor(() =>
      screen.getByText(/Couldn't load the data source's filter fields/),
    );
    expect(screen.queryByText(COUNTRY_FIELD)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: SUBMIT }));
    expect(onSubmit).toHaveBeenCalledWith({
      input: { query: 'q', filters: { country: ['Kenya'] } },
      tags: undefined,
      notes: undefined,
    });
  });
});
