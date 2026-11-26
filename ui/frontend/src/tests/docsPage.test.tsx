import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import DocsPage from '../components/docs/DocsPage';
import { notifyDocsLocation } from '../utils/docsLocation';

const SEARCH_PATH = 'using-evidence-lab/search.md';
const BRIEF_PATH = 'using-evidence-lab/brief.md';
const ADMIN_PATH = 'admin/pipeline-configuration.md';
const PIPELINE_TITLE = 'Pipeline Configuration';
const DOCS_ARTICLES = 'Docs articles';
const ADMIN_ARTICLES = 'Admin articles';
const DATA_SOURCES = 'Data sources';
const SECTION_LENGTH = 'Section length';
const ON_THIS_PAGE = 'On this page';
const MANIFEST = {
  title: 'Evidence Lab Documentation',
  tree: [
    {
      title: 'Using Evidence Lab',
      children: [
        { title: 'Search', path: SEARCH_PATH },
        { title: 'Brief', path: BRIEF_PATH },
      ],
    },
    {
      title: 'Admin',
      children: [
        { title: PIPELINE_TITLE, path: ADMIN_PATH },
        { title: 'Database Maintenance', path: 'admin/database-maintenance.md' },
      ],
    },
  ],
};

const SEARCH_ARTICLE = '# Search\n\nThis is the Search guide. ' +
  'See [Pipeline Configuration](../admin/pipeline-configuration.md#data-sources), ' +
  'the [branding script](../../scripts/custom/apply_branding.sh) and ' +
  '![a screenshot](../images/search-guide/filters-crop.png).';
const PIPELINE_ARTICLE = '# Pipeline\n\n## Data sources\n\nConfigured here. ' +
  'Return to the [Search guide](../using-evidence-lab/search.md).';

const setDocsUrl = (url: string) => {
  act(() => {
    window.history.pushState(null, '', url);
    notifyDocsLocation();
  });
};

const mockDocsFetch = (articles: Record<string, string> = {}) => {
  const pages = new Map(Object.entries({
    [SEARCH_PATH]: SEARCH_ARTICLE,
    [BRIEF_PATH]: '# Brief\n\nUse the outline editor.',
    [ADMIN_PATH]: PIPELINE_ARTICLE,
    ...articles,
  }));

  const fetchDocs = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const path = url.slice(url.indexOf('/docs/') + '/docs/'.length);
    return {
      ok: true,
      json: () => Promise.resolve(MANIFEST),
      text: () => Promise.resolve(pages.get(path) ?? ''),
    };
  });
  global.fetch = fetchDocs as unknown as typeof fetch;
  return fetchDocs;
};

const scrollIntoView = jest.fn();

beforeEach(() => {
  window.history.replaceState(null, '', '/');
  window.scrollTo = jest.fn();
  window.HTMLElement.prototype.scrollIntoView = scrollIntoView;
  scrollIntoView.mockClear();
  window.IntersectionObserver = jest.fn(() => ({
    observe: jest.fn(),
    disconnect: jest.fn(),
  })) as unknown as typeof IntersectionObserver;
  mockDocsFetch();
});

describe('DocsPage', () => {
  test('keeps heading jumps clear of the sticky header as it changes height', () => {
    const header = document.createElement('header');
    header.className = 'top-bar';
    document.body.append(header);
    const bounds = jest.spyOn(header, 'getBoundingClientRect');
    bounds.mockReturnValue({ height: 200 } as DOMRect);
    const disconnect = jest.fn();
    let onResize: ResizeObserverCallback | undefined;
    const observer = { observe: jest.fn(), disconnect, unobserve: jest.fn() };
    window.ResizeObserver = jest.fn((callback: ResizeObserverCallback) => {
      onResize = callback;
      return observer;
    });

    const view = render(<DocsPage />);
    const style = document.documentElement.style;
    const property = '--docs-header-height';
    expect(style.getPropertyValue(property)).toBe('200px');
    expect(observer.observe).toHaveBeenCalledWith(header);

    bounds.mockReturnValue({ height: 168 } as DOMRect);
    onResize?.([], observer);
    expect(style.getPropertyValue(property)).toBe('168px');

    view.unmount();
    expect(style.getPropertyValue(property)).toBe('');
    expect(disconnect).toHaveBeenCalledTimes(1);
    header.remove();
  });

  test('opens on Docs and lists only general guides', async () => {
    render(<DocsPage />);
    expect(screen.getByText('Loading documentation...')).toBeInTheDocument();

    const sidebar = await screen.findByRole('navigation', { name: DOCS_ARTICLES });
    expect(within(sidebar).getByRole('button', { name: 'Search' })).toHaveAttribute('aria-current', 'page');
    expect(within(sidebar).getByRole('button', { name: 'Brief' })).toBeInTheDocument();
    expect(within(sidebar).queryByRole('button', { name: 'Admin' })).toBeNull();
    expect(await screen.findByRole('heading', { name: 'Search' })).toBeInTheDocument();
  });

  test('opens Admin and switches back to Docs while the viewer stays mounted', async () => {
    setDocsUrl('/?tab=docs&section=admin');
    render(<DocsPage />);

    const sidebar = await screen.findByRole('navigation', { name: ADMIN_ARTICLES });
    expect(within(sidebar).getByRole('button', { name: PIPELINE_TITLE }))
      .toHaveAttribute('aria-current', 'page');
    expect(within(sidebar).queryByRole('button', { name: 'Search' })).toBeNull();
    expect(await screen.findByRole('heading', { name: 'Pipeline' })).toBeInTheDocument();

    setDocsUrl('/?tab=docs');
    expect(await screen.findByRole('navigation', { name: DOCS_ARTICLES })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Search' })).toBeInTheDocument();
  });

  test('limits title and article text searches to the open section', async () => {
    const fetchDocs = mockDocsFetch({
      [SEARCH_PATH]: SEARCH_ARTICLE + ' Term in both guides.',
      [ADMIN_PATH]: PIPELINE_ARTICLE + ' Term in both guides.',
    });
    render(<DocsPage />);
    fireEvent.change(await screen.findByRole('searchbox', { name: 'Search docs' }), {
      target: { value: 'term in both guides' },
    });

    const docs = screen.getByRole('navigation', { name: DOCS_ARTICLES });
    expect(await within(docs).findByRole('button', { name: 'Search' })).toBeInTheDocument();
    expect(within(docs).queryByRole('button', { name: PIPELINE_TITLE })).toBeNull();
    expect(fetchDocs).not.toHaveBeenCalledWith(expect.stringContaining('/docs/admin/'), expect.anything());

    setDocsUrl('/?tab=docs&section=admin');
    fireEvent.change(await screen.findByRole('searchbox', { name: 'Search admin docs' }), {
      target: { value: 'term in both guides' },
    });
    const admin = screen.getByRole('navigation', { name: ADMIN_ARTICLES });
    expect(await within(admin).findByRole('button', { name: PIPELINE_TITLE })).toBeInTheDocument();
    expect(within(admin).queryByRole('button', { name: 'Search' })).toBeNull();
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search admin docs' }), {
      target: { value: 'maintenance' },
    });
    expect(within(admin).getByRole('button', { name: 'Database Maintenance' })).toBeInTheDocument();
  });

  test('resolves relative links and images against the article and app base path', async () => {
    render(<DocsPage basePath="/lab" />);
    expect(await screen.findByRole('link', { name: PIPELINE_TITLE })).toHaveAttribute(
      'href',
      '/lab/?tab=docs&path=admin%2Fpipeline-configuration.md#data-sources'
    );
    expect(screen.getByText('branding script')).toHaveAttribute(
      'href',
      'https://github.com/dividor/evidencelab/blob/main/scripts/custom/apply_branding.sh'
    );
    expect(screen.getByAltText('a screenshot')).toHaveAttribute(
      'src',
      '/lab/docs/images/search-guide/filters-crop.png'
    );
  });

  test('opens linked articles in the right section and scrolls to their heading', async () => {
    render(<DocsPage />);
    fireEvent.click(await screen.findByRole('link', { name: PIPELINE_TITLE }));

    expect(await screen.findByRole('navigation', { name: ADMIN_ARTICLES })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: DATA_SOURCES })).toHaveAttribute('id', 'data-sources');
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));
    expect(window.location.search).toContain('path=admin%2Fpipeline-configuration.md');
    expect(window.location.hash).toBe('#data-sources');

    fireEvent.click(screen.getByRole('link', { name: 'Search guide' }));
    expect(await screen.findByRole('navigation', { name: DOCS_ARTICLES })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Search' })).toBeInTheDocument();
  });

  test('opens an existing Docs bookmark for an Admin article at its heading', async () => {
    window.history.replaceState(null, '', '/docs?tab=docs&path=admin%2Fpipeline-configuration.md#data-sources');
    render(<DocsPage />);

    expect(await screen.findByRole('navigation', { name: ADMIN_ARTICLES })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: DATA_SOURCES })).toBeInTheDocument();
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));
  });

  test.each(['features--tabs', 'features-tabs'])('resolves current and older heading links to %s', async (anchor) => {
    mockDocsFetch({ [ADMIN_PATH]: '# Pipeline\n\n## Features & Tabs' });
    window.history.replaceState(null, '', `/?tab=docs&path=${ADMIN_PATH}#${anchor}`);
    render(<DocsPage />);

    expect(await screen.findByRole('heading', { name: 'Features & Tabs' })).toHaveAttribute('id', 'features--tabs');
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));
  });

  test('gives a long article a contents list with links to its rendered headings', async () => {
    mockDocsFetch({
      [SEARCH_PATH]: '# Search\n\n## **Data** `sources`\n\n' + 'word '.repeat(1500) +
        '\n\n### Data sources\n\n#### Section length\n\n~~~md\n## Example code\n~~~',
    });
    const { container } = render(<DocsPage />);
    await screen.findByRole('heading', { name: SECTION_LENGTH });

    const desktopContents = within(screen.getByRole('complementary')).getByRole('navigation', { name: ON_THIS_PAGE });
    const links = within(desktopContents).getAllByRole('link', { name: DATA_SOURCES });
    expect(links[0]).toHaveAttribute('href', '#data-sources');
    expect(links[1]).toHaveAttribute('href', '#data-sources-1');
    expect(container.querySelector('h2#data-sources')).toBeInTheDocument();
    expect(container.querySelector('h3#data-sources-1')).toBeInTheDocument();
    expect(container.querySelector('h4#section-length')).toBeInTheDocument();
    expect(within(desktopContents).getAllByRole('link')).toHaveLength(2);
    expect(container.querySelector('.docs-toc-inline summary')).toHaveTextContent(ON_THIS_PAGE);
  });

  test('keeps headings linkable on a short article without a contents list', async () => {
    mockDocsFetch({ [SEARCH_PATH]: '# Search\n\n## Quick search\n\n## Filters\n\n#### Section length' });
    render(<DocsPage />);

    expect(await screen.findByRole('heading', { name: SECTION_LENGTH })).toHaveAttribute('id', 'section-length');
    expect(screen.queryByRole('navigation', { name: ON_THIS_PAGE })).toBeNull();
    expect(screen.queryByText(ON_THIS_PAGE)).toBeNull();
  });
});
