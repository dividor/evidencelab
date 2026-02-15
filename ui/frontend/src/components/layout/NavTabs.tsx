import React, { useState } from 'react';

type TabName = 'search' | 'heatmap' | 'documents' | 'pipeline' | 'processing' | 'help' | 'tech' | 'data' | 'privacy' | 'stats';

interface NavTabsProps {
  activeTab: TabName;
  onTabChange: (tab: TabName) => void;
}

const ACTIVE_CLASS = 'nav-tab-active';

export const NavTabs = ({ activeTab, onTabChange }: NavTabsProps) => {
  const [monitorDropdownOpen, setMonitorDropdownOpen] = useState(false);
  const monitorActive = activeTab === 'documents' || activeTab === 'pipeline' || activeTab === 'processing' || activeTab === 'stats';

  const handleToggleMonitorDropdown = () => {
    setMonitorDropdownOpen((open) => !open);
  };

  const handleMonitorBlur = () => {
    setTimeout(() => setMonitorDropdownOpen(false), 200);
  };

  const handleMonitorSelect = (tab: 'documents' | 'pipeline' | 'processing' | 'stats') => {
    onTabChange(tab);
    setMonitorDropdownOpen(false);
  };

  return (
    <nav className="nav-tabs">
      <button
        className={`nav-tab ${activeTab === 'heatmap' ? ACTIVE_CLASS : ''}`}
        onClick={() => onTabChange('heatmap')}
      >
        Heatmapper
      </button>
      <button
        className={`nav-tab ${activeTab === 'search' ? ACTIVE_CLASS : ''}`}
        onClick={() => onTabChange('search')}
      >
        Search
      </button>
      <span className="nav-separator">|</span>
      <div className="dropdown-container nav-dropdown">
        <button
          className={`nav-tab nav-tab-dropdown ${monitorActive ? ACTIVE_CLASS : ''}`}
          onClick={handleToggleMonitorDropdown}
          onBlur={handleMonitorBlur}
        >
          <span>Monitor</span>
          <span className="dropdown-arrow">▾</span>
        </button>
        {monitorDropdownOpen && (
          <div className="dropdown-menu nav-dropdown-menu">
            <button className="dropdown-item" onClick={() => handleMonitorSelect('documents')}>
              Documents
            </button>
            <button className="dropdown-item" onClick={() => handleMonitorSelect('stats')}>
              Stats
            </button>
            <button className="dropdown-item" onClick={() => handleMonitorSelect('pipeline')}>
              Pipeline
            </button>
            <button className="dropdown-item" onClick={() => handleMonitorSelect('processing')}>
              Processing
            </button>
          </div>
        )}
      </div>
    </nav>
  );
};
