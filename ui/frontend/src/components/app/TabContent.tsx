import React from 'react';
import ReactMarkdown from 'react-markdown';

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
      return <HelpTabContent content={privacyContent} />;
    default:
      return null;
  }
};
