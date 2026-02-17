import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { GA_MEASUREMENT_ID } from '../../config';
import { getGaConsent, setGaConsent } from '../CookieConsent';

type TabName = 'search' | 'heatmap' | 'documents' | 'pipeline' | 'processing' | 'info' | 'tech' | 'data' | 'privacy' | 'stats';

interface TabContentProps {
  activeTab: TabName;
  hasSearched: boolean;
  searchTab: React.ReactNode;
  heatmapTab: React.ReactNode;
  documentsTab: React.ReactNode;
  statsTab: React.ReactNode;
  pipelineTab: React.ReactNode;
  processingTab: React.ReactNode;
  aboutContent: string;
  techContent: string;
  dataContent: string;
  privacyContent: string;
  onTabChange: (tab: TabName) => void;
}

const INFO_TAB_LABELS: Record<string, string> = {
  info: 'About',
  tech: 'Tech',
  data: 'Data',
  privacy: 'Privacy',
};

const INFO_TAB_LINKS: Record<string, TabName[]> = {
  info: ['tech', 'data'],
  tech: ['info', 'data'],
  data: ['info', 'tech'],
  privacy: ['info', 'tech', 'data'],
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

const HelpTabContent = ({ content, currentTab, onTabChange }: { content: string; currentTab: TabName; onTabChange: (tab: TabName) => void }) => (
  <div className="main-content">
    <div className="about-page-container">
      <div className="about-content">
        <ReactMarkdown>{content}</ReactMarkdown>
        <InfoFooterLinks currentTab={currentTab} onTabChange={onTabChange} />
      </div>
    </div>
  </div>
);

const TrackingToggle = () => {
  const [consent, setConsent] = useState(getGaConsent);

  const handleRevoke = () => {
    setGaConsent('denied');
    window[`ga-disable-${GA_MEASUREMENT_ID}` as any] = true as any;
    setConsent('denied');
  };

  const handleGrant = () => {
    setGaConsent('granted');
    window.location.reload();
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
      </p>
    </div>
  );
};

const PrivacyTabContent = ({ content, onTabChange }: { content: string; onTabChange: (tab: TabName) => void }) => (
  <div className="main-content">
    <div className="about-page-container">
      <div className="about-content">
        <ReactMarkdown>{content}</ReactMarkdown>
        {GA_MEASUREMENT_ID && <TrackingToggle />}
        <InfoFooterLinks currentTab="privacy" onTabChange={onTabChange} />
      </div>
    </div>
  </div>
);

export const TabContent: React.FC<TabContentProps> = ({
  activeTab,
  hasSearched,
  searchTab,
  heatmapTab,
  documentsTab,
  statsTab,
  pipelineTab,
  processingTab,
  aboutContent,
  techContent,
  dataContent,
  privacyContent,
  onTabChange,
}) => {
  switch (activeTab) {
    case 'search':
      return hasSearched ? <>{searchTab}</> : null;
    case 'heatmap':
      return <>{heatmapTab}</>;
    case 'documents':
      return <>{documentsTab}</>;
    case 'pipeline':
      return <>{pipelineTab}</>;
    case 'processing':
      return <>{processingTab}</>;
    case 'info':
      return <HelpTabContent content={aboutContent} currentTab="info" onTabChange={onTabChange} />;
    case 'tech':
      return <HelpTabContent content={techContent} currentTab="tech" onTabChange={onTabChange} />;
    case 'data':
      return <HelpTabContent content={dataContent} currentTab="data" onTabChange={onTabChange} />;
    case 'stats':
      return <>{statsTab}</>;
    case 'privacy':
      return <PrivacyTabContent content={privacyContent} onTabChange={onTabChange} />;
    default:
      return null;
  }
};
