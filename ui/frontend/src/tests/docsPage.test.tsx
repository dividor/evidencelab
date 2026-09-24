import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
    const text = url.includes('admin/pipeline-configuration.md')
      ? '# Pipeline\n\n## Data sources\n\nConfigured here.'
      : '# Search\n\nThis is the Search guide. ' +
        'See [Pipeline Configuration](../admin/pipeline-configuration.md#data-sources), ' +
        'the [branding script](../../scripts/custom/apply_branding.sh) and ' +
        '![a screenshot](../images/search-guide/filters-crop.png).';
    return Promise.resolve({
      text: () => Promise.resolve(text),
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

  test('resolves relative links and images against the page being shown', async () => {
    render(<DocsPage basePath="/lab" />);
    const link = await screen.findByText('Pipeline Configuration');
    // A page link carries the real file address, so it also works when copied.
    expect(link).toHaveAttribute('href', '/lab/docs/admin/pipeline-configuration.md');
    expect(screen.getByText('branding script')).toHaveAttribute(
      'href',
      'https://github.com/dividor/evidencelab/blob/main/scripts/custom/apply_branding.sh'
    );
    expect(screen.getByAltText('a screenshot')).toHaveAttribute(
      'src',
      '/lab/docs/images/search-guide/filters-crop.png'
    );
  });

  test('clicking a page link opens that page in the viewer at its heading', async () => {
    const scrollIntoView = jest.fn();
    window.HTMLElement.prototype.scrollIntoView = scrollIntoView;
    render(<DocsPage />);
    fireEvent.click(await screen.findByText('Pipeline Configuration'));
    await waitFor(() => expect(screen.getByText('Configured here.')).toBeInTheDocument());
    expect(
      (global.fetch as jest.Mock).mock.calls.some((c) => String(c[0]).includes('/docs/admin/pipeline-configuration.md'))
    ).toBe(true);
    expect(scrollIntoView).toHaveBeenCalled();
    expect(window.location.search).toContain('path=admin%2Fpipeline-configuration.md');
  });
});
