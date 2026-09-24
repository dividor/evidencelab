import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  getAnalyticsConsent,
  grantAnalyticsConsent,
  isAnalyticsConfigured,
  revokeAnalyticsConsent,
} from '../../utils/analytics';
import DocsPage from '../docs/DocsPage';
import { parseDocLink, repositoryFileUrl } from '../../utils/docLinks';

type TabName = 'search' | 'assistant' | 'brief' | 'heatmap' | 'documents' | 'pipeline' | 'processing' | 'info' | 'tech' | 'data' | 'privacy' | 'terms' | 'stats' | 'admin' | 'docs';

interface TabContentProps {
  activeTab: TabName;
  hasSearched: boolean;
  searchTab: React.ReactNode;
  assistantTab?: React.ReactNode;
  briefTab?: React.ReactNode;
  heatmapTab: React.ReactNode;
  documentsTab: React.ReactNode;
  statsTab: React.ReactNode;
  pipelineTab: React.ReactNode;
  processingTab: React.ReactNode;
  aboutContent: string;
  techContent: string;
  dataContent: string;
  privacyContent: string;
  termsContent: string;
  basePath?: string;
  docsInitialPath?: string;
  onTabChange: (tab: TabName) => void;
}

const INFO_TAB_LABELS: Record<string, string> = {
  info: 'About',
  tech: 'Tech',
  data: 'Data',
  privacy: 'Privacy',
  terms: 'Terms of Service',
};

const INFO_TAB_LINKS: Record<string, TabName[]> = {
  info: ['tech', 'data'],
  tech: ['info', 'data'],
  data: ['info', 'tech'],
  privacy: ['info', 'terms'],
  terms: ['info', 'privacy'],
};

const InfoFooterLinks = ({ currentTab, onTabChange }: { currentTab: TabName; onTabChange: (tab: TabName) => void }) => {
  const links = INFO_TAB_LINKS[currentTab];
  if (!links) return null;
  return (
    <div className="info-footer-links">
      <span className="info-footer-heading">Read more</span>
      <div className="info-footer-buttons">
        {links.map((tab) => (
          <button key={tab} className="info-footer-link" onClick={() => onTabChange(tab)}>
            {INFO_TAB_LABELS[tab]}
          </button>
        ))}
      </div>
    </div>
  );
};

// Docs pages that have a tab of their own rather than opening in the docs viewer.
const PAGE_TABS = new Map<string, TabName>([
  ['overview/about.md', 'info'],
  ['overview/tech.md', 'tech'],
  ['overview/data.md', 'data'],
  ['overview/privacy.md', 'privacy'],
  ['overview/terms.md', 'terms'],
]);

/**
 * Link rendering for a docs page shown outside the docs viewer (Privacy, Terms).
 * The markdown links are relative to the page, as on GitHub (utils/docLinks.ts):
 * another page opens its own tab or the docs viewer, a repository file opens on
 * GitHub, and everything else is left to the browser.
 */
const pageLinkComponents = (pagePath: string, basePath: string) => ({
  a: ({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => {
    const link = parseDocLink(href, pagePath);
    if (link.kind === 'page') {
      const tab = PAGE_TABS.get(link.path);
      const target = tab
        ? `${basePath}/${tab}`
        : `${basePath}/?tab=docs&path=${encodeURIComponent(link.path)}`;
      const hash = link.anchor ? `#${link.anchor}` : '';
      return <a href={`${target}${hash}`} {...props}>{children}</a>;
    }
    if (link.kind === 'repo-file') {
      return (
        <a href={repositoryFileUrl(link.path)} target="_blank" rel="noopener noreferrer" {...props}>
          {children}
        </a>
      );
    }
    if (link.kind === 'external') {
      return <a href={link.href} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>;
    }
    return <a href={href} {...props}>{children}</a>;
  },
});

const HelpTabContent = ({ content, currentTab, pagePath, basePath, onTabChange }: {
  content: string;
  currentTab: TabName;
  pagePath: string;
  basePath: string;
  onTabChange: (tab: TabName) => void;
}) => (
  <div className="main-content">
    <div className="about-page-container">
      <div className="about-content">
        <ReactMarkdown components={pageLinkComponents(pagePath, basePath)}>{content}</ReactMarkdown>
        <InfoFooterLinks currentTab={currentTab} onTabChange={onTabChange} />
      </div>
    </div>
  </div>
);

const TrackingToggle = () => {
  const [consent, setConsent] = useState(getAnalyticsConsent);

  const handleRevoke = () => {
    revokeAnalyticsConsent();
    setConsent('denied');
  };

  const handleGrant = () => {
    grantAnalyticsConsent();
    setConsent('granted');
  };

  if (consent === 'granted') {
    return (
      <div style={{ marginTop: '1.5em' }}>
        <h3>Your cookie preferences</h3>
        <p>
          You have accepted analytics cookies. Tracking is <strong>enabled</strong>.
          {' '}
          <a
            href="#stop-tracking"
            onClick={(e) => { e.preventDefault(); handleRevoke(); }}
          >
            Stop tracking
          </a>
        </p>
      </div>
    );
  }

  return (
    <div style={{ marginTop: '1.5em' }}>
      <h3>Your cookie preferences</h3>
      <p>
        You have declined analytics cookies. Anonymous tracking is <strong>disabled</strong>.
        {' '}
        <a
          href="#enable-tracking"
          onClick={(e) => { e.preventDefault(); handleGrant(); }}
        >
          Enable tracking
        </a>
      </p>
    </div>
  );
};

const PrivacyTabContent = ({ content, basePath, onTabChange }: { content: string; basePath: string; onTabChange: (tab: TabName) => void }) => (
  <div className="main-content">
    <div className="about-page-container">
      <div className="about-content">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={pageLinkComponents('overview/privacy.md', basePath)}
        >
          {content}
        </ReactMarkdown>
        {isAnalyticsConfigured() && <TrackingToggle />}
        <InfoFooterLinks currentTab="privacy" onTabChange={onTabChange} />
      </div>
    </div>
  </div>
);

export const TabContent: React.FC<TabContentProps> = ({
  activeTab,
  hasSearched,
  searchTab,
  assistantTab,
  briefTab,
  heatmapTab,
  documentsTab,
  statsTab,
  pipelineTab,
  processingTab,
  aboutContent,
  techContent,
  dataContent,
  privacyContent,
  termsContent,
  basePath,
  docsInitialPath,
  onTabChange,
}) => {
  // Render the active tab via the switch, plus always render the assistant
  // tab (hidden when inactive) so chat state is preserved across tab switches.
  const activeContent = (() => {
    switch (activeTab) {
      case 'search':
        return hasSearched ? <>{searchTab}</> : null;
      case 'assistant':
        return null; // handled by the always-mounted wrapper below
      case 'brief':
        return null; // handled by the always-mounted wrapper below
      case 'heatmap':
        return <>{heatmapTab}</>;
      case 'documents':
        return <>{documentsTab}</>;
      case 'pipeline':
        return <>{pipelineTab}</>;
      case 'processing':
        return <>{processingTab}</>;
      case 'info':
      case 'tech':
      case 'data':
        return <DocsPage basePath={basePath} initialPath={docsInitialPath} />;
      case 'stats':
        return <>{statsTab}</>;
      case 'privacy':
        return <PrivacyTabContent content={privacyContent} basePath={basePath || ''} onTabChange={onTabChange} />;
      case 'terms':
        return (
          <HelpTabContent
            content={termsContent}
            currentTab="terms"
            pagePath="overview/terms.md"
            basePath={basePath || ''}
            onTabChange={onTabChange}
          />
        );
      case 'docs':
        return <DocsPage basePath={basePath} initialPath={docsInitialPath} />;
      default:
        return null;
    }
  })();

  return (
    <>
      {/* AssistantTab stays mounted (hidden when inactive) to preserve chat state */}
      {assistantTab && (
        <div style={{ display: activeTab === 'assistant' ? 'block' : 'none' }}>
          {assistantTab}
        </div>
      )}
      {/* BriefTab stays mounted (hidden when inactive) to preserve brief state */}
      {briefTab && (
        <div style={{ display: activeTab === 'brief' ? 'block' : 'none' }}>
          {briefTab}
        </div>
      )}
      {activeContent}
    </>
  );
};
