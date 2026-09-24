import React from 'react';
import { render, screen } from '@testing-library/react';

import { TabContent } from '../components/app/TabContent';

jest.mock('../components/docs/DocsPage', () => () => <div>docs viewer</div>);

const TERMS =
  '## Terms\n\n' +
  'See the [Privacy Policy](privacy.md) and the [content policy](terms.md#content-policy). ' +
  'Reports are handled per [Content Moderation](../admin/content-moderation.md#handling-a-report). ' +
  'The [licence](../../LICENSE) and [the site](https://example.org) are elsewhere. ' +
  'Write to [us](mailto:x@y.z).';

const renderTab = (activeTab: 'terms' | 'privacy', basePath = '') =>
  render(
    <TabContent
      activeTab={activeTab}
      hasSearched={false}
      searchTab={null}
      heatmapTab={null}
      documentsTab={null}
      statsTab={null}
      pipelineTab={null}
      processingTab={null}
      aboutContent=""
      techContent=""
      dataContent=""
      privacyContent={TERMS}
      termsContent={TERMS}
      basePath={basePath}
      onTabChange={jest.fn()}
    />
  );

const href = (text: string) => screen.getByText(text).getAttribute('href');

describe('links on the Terms and Privacy tabs', () => {
  test('a page with its own tab opens that tab', () => {
    renderTab('terms');
    expect(href('Privacy Policy')).toBe('/privacy');
    expect(href('content policy')).toBe('/terms#content-policy');
  });

  test('any other docs page opens the docs viewer at that page and heading', () => {
    renderTab('terms');
    expect(href('Content Moderation')).toBe(
      '/?tab=docs&path=admin%2Fcontent-moderation.md#handling-a-report'
    );
  });

  test('the app base path is honoured', () => {
    renderTab('privacy', '/lab');
    expect(href('Privacy Policy')).toBe('/lab/privacy');
    expect(href('Content Moderation')).toBe(
      '/lab/?tab=docs&path=admin%2Fcontent-moderation.md#handling-a-report'
    );
  });

  test('repository files open on GitHub, external links in a new tab, mailto untouched', () => {
    renderTab('terms');
    expect(href('licence')).toBe('https://github.com/dividor/evidencelab/blob/main/LICENSE');
    expect(screen.getByText('the site')).toHaveAttribute('target', '_blank');
    expect(href('us')).toBe('mailto:x@y.z');
  });
});
