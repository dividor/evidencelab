import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import DocsPage from '../components/docs/DocsPage';

// Mock fetch: the manifest, then a markdown doc.
const MANIFEST = {
  title: 'Evidence Lab Documentation',
  tree: [
    {
      title: 'Using Evidence Lab',
      children: [
        { title: 'Search', path: 'using-evidence-lab/search.md' },
        { title: 'Brief', path: 'using-evidence-lab/brief.md' },
      ],
    },
  ],
};

beforeEach(() => {
  global.fetch = jest.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('docs.json')) {
      return Promise.resolve({
        json: () => Promise.resolve(MANIFEST),
        text: () => Promise.resolve(JSON.stringify(MANIFEST)),
      }) as unknown as Promise<Response>;
    }
    return Promise.resolve({
      text: () => Promise.resolve('# Search\n\nThis is the Search guide.'),
      json: () => Promise.resolve({}),
    }) as unknown as Promise<Response>;
  }) as unknown as typeof fetch;
});

describe('DocsPage', () => {
  test('loads the manifest and renders the sidebar + first doc (no longer stuck loading)', async () => {
    render(<DocsPage />);
    // Initially the loading placeholder shows…
    expect(screen.getByText('Loading documentation...')).toBeInTheDocument();

    // …then the manifest resolves and the docs render.
    await waitFor(() => expect(screen.getByText('Brief')).toBeInTheDocument());
    expect(screen.queryByText('Loading documentation...')).toBeNull();
    // Sidebar entries from the manifest are present.
    expect(screen.getAllByText('Search').length).toBeGreaterThanOrEqual(1);
    // The manifest fetch hit the docs.json endpoint.
    expect((global.fetch as jest.Mock).mock.calls.some((c) => String(c[0]).includes('docs.json'))).toBe(
      true,
    );
  });
});
