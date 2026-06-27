import React from 'react';
import { BRIEF_EXAMPLES } from './briefTypes';
import { UseBriefReturn } from './useBrief';

interface BriefSeedProps {
  brief: UseBriefReturn;
}

export const BriefSeed: React.FC<BriefSeedProps> = ({ brief }) => {
  const { query, setQuery, generateOutline, startManual, outlineLoading, error } = brief;

  return (
    <div className="brief-seed">
      <div className="brief-eyebrow">EVIDENCE BRIEF</div>
      <h2 className="brief-seed-title">Turn a question into a research brief</h2>
      <p className="brief-seed-lede">
        Start from a question and let Evidence Lab draft an outline, then run deep research
        across the corpus for each section — with sources you can verify and regenerate.
      </p>

      <div className="brief-seed-card">
        <label className="brief-label" htmlFor="brief-question">
          What is the brief about?
        </label>
        <textarea
          id="brief-question"
          className="brief-textarea"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Type your topic and guidance here"
          rows={2}
        />
        {error && <div className="brief-error">{error}</div>}
        <div className="brief-seed-actions">
          <button
            className="brief-btn brief-btn-primary"
            onClick={generateOutline}
            disabled={outlineLoading || !query.trim()}
          >
            {outlineLoading ? 'Generating…' : '✦ Generate outline'}
          </button>
          <button className="brief-btn brief-btn-secondary" onClick={startManual}>
            Write my own headings
          </button>
          <button
            className="brief-btn brief-btn-secondary brief-seed-load"
            onClick={() => brief.setHistoryOpen(true)}
            disabled={brief.history.length === 0}
          >
            ⟲ Load a saved brief
            {brief.history.length > 0 && (
              <span className="brief-count-badge">{brief.history.length}</span>
            )}
          </button>
        </div>
      </div>

      <div className="brief-examples">
        <div className="brief-section-label">Try a question</div>
        <div className="brief-example-list">
          {BRIEF_EXAMPLES.map((ex) => (
            <button key={ex} className="brief-example" onClick={() => setQuery(ex)}>
              {ex}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};
