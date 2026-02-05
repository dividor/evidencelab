import React from 'react';
import { render, screen } from '@testing-library/react';
import axios from 'axios';

jest.mock('react-markdown', () => {
  const React = jest.requireActual('react');
  return {
    __esModule: true,
    default: ({ children }: { children: React.ReactNode }) =>
      React.createElement('div', null, children),
  };
});

import { Documents } from '../components/Documents';

jest.mock('axios');

const mockedAxios = axios as jest.Mocked<typeof axios>;

describe('Documents', () => {
  test('loads stats and renders document rows', async () => {
    mockedAxios.get.mockImplementation((url) => {
      if (url.includes('/stats')) {
        return Promise.resolve({
          data: {
            total_documents: 1,
            indexed_documents: 1,
            total_agencies: 1,
            status_breakdown: {},
            agency_breakdown: {},
            agency_indexed: {},
            type_breakdown: {},
            type_indexed: {},
            year_breakdown: {},
            year_indexed: {},
            language_breakdown: {},
            language_indexed: {},
            format_breakdown: {},
            format_indexed: {},
          },
        });
      }
      if (url.includes('/facets')) {
        return Promise.resolve({ data: { facets: { title: [] } } });
      }
      if (url.includes('/documents?')) {
        return Promise.resolve({
          data: {
            documents: [
              {
                id: 'doc-1',
                title: 'Report Title',
                organization: 'UN',
                status: 'indexed',
                document_type: 'type',
                published_year: 2024,
                language: 'en',
                file_format: 'pdf',
                page_count: 10,
                file_size_mb: 1.2,
              },
            ],
            pagination: { total_pages: 1, total_count: 1 },
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    render(<Documents dataSource="uneg" />);

    expect(await screen.findByText('Documents Library')).toBeInTheDocument();
    expect(await screen.findByText('Report Title')).toBeInTheDocument();
  });
});
