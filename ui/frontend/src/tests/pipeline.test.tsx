import React from 'react';
import { render, screen } from '@testing-library/react';
import axios from 'axios';
import { Pipeline } from '../components/Pipeline';

jest.mock('axios');
jest.mock('react-plotly.js', () => ({
  __esModule: true,
  default: () => <div data-testid="plot" />,
}));

const mockedAxios = axios as jest.Mocked<typeof axios>;

jest.setTimeout(20000);

const statsResponse = {
  total_documents: 10,
  indexed_documents: 8,
  total_agencies: 3,
  status_breakdown: { indexed: 8, failed: 2 },
};

const sankeyResponse = {
  nodes: ['A', 'B'],
  node_colors: ['#000', '#111'],
  links: { source: [0], target: [1], value: [5], color: ['#ccc'] },
  annotations: { num_orgs: 1, total_records: 2, layer2_count: 0, layer3_count: 0, layer4_count: 0 },
};

const timelineResponse = {
  histogram: { x: [], y: [] },
  phase_distribution: { x: [], Parsing: [], Summarizing: [], Tagging: [], Indexing: [] },
  pages_histogram: { x: [], y: [] },
  errors_histogram: { x: [], 'Parse Failed': [], 'Summarization Failed': [], 'Indexing Failed': [] },
};

describe('Pipeline', () => {
  test('loads and renders pipeline stats', async () => {
    mockedAxios.get.mockImplementation((url) => {
      if (url.includes('/stats/sankey')) {
        return Promise.resolve({ data: sankeyResponse });
      }
      if (url.includes('/stats/timeline')) {
        return Promise.resolve({ data: timelineResponse });
      }
      return Promise.resolve({ data: statsResponse });
    });

    render(<Pipeline dataSource="uneg" />);

    expect(await screen.findByText('Total Reports')).toBeInTheDocument();
    expect(screen.getByText('Agencies')).toBeInTheDocument();
    expect(mockedAxios.get).toHaveBeenCalledTimes(3);
  });
});
