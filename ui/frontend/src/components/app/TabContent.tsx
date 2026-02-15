import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { GA_MEASUREMENT_ID } from '../../config';
import { getGaConsent, setGaConsent } from '../CookieConsent';

type TabName = 'search' | 'heatmap' | 'documents' | 'pipeline' | 'processing' | 'help' | 'tech' | 'data' | 'privacy' | 'stats';

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
}

const HelpTabContent = ({ content }: { content: string }) => (
  <div className="main-content">
    <div className="about-page-container">
      <div className="about-content">
        <ReactMarkdown>{content}</ReactMarkdown>
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
          <button
            type="button"
            onClick={handleRevoke}
            className="app-footer-link"
            style={{ fontSize: 'inherit' }}
          >
            Withdraw consent
          </button>
        </p>
      </div>
    );
  }

  return (
    <div style={{ marginTop: '1.5em' }}>
      <h3>Your cookie preferences</h3>
      <p>
        You have declined analytics cookies. Tracking is <strong>disabled</strong>.
        {' '}
        If you change your mind,{' '}
        <button
          type="button"
          onClick={handleGrant}
          className="app-footer-link"
          style={{ fontSize: 'inherit' }}
        >
          accept analytics cookies
        </button>.
      </p>
    </div>
  );
};

const PrivacyTabContent = ({ content }: { content: string }) => (
  <div className="main-content">
    <div className="about-page-container">
      <div className="about-content">
        <ReactMarkdown>{content}</ReactMarkdown>
        {GA_MEASUREMENT_ID && <TrackingToggle />}
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
    case 'help':
      return <HelpTabContent content={aboutContent} />;
    case 'tech':
      return <HelpTabContent content={techContent} />;
    case 'data':
      return <HelpTabContent content={dataContent} />;
    case 'stats':
      return <>{statsTab}</>;
    case 'privacy':
      return <PrivacyTabContent content={privacyContent} />;
    default:
      return null;
  }
};
