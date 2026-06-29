import React from 'react';
import { IconHistory, IconSparkle } from './BriefIcons';
import { UseBriefReturn } from './useBrief';

const tagClass = (tag: string): string => `brief-tag brief-tag-${tag.toLowerCase()}`;

interface BriefSeedProps {
  brief: UseBriefReturn;
}

export const BriefSeed: React.FC<BriefSeedProps> = ({ brief }) => {
  const {
    query,
    setQuery,
    instructions,
    setInstructions,
    numHeadings,
    setNumHeadings,
    generateOutline,
    startManual,
    outlineLoading,
    error,
  } = brief;

  // While the outline-generation deep research runs, show its live activity.
  if (outlineLoading) {
    return (
      <div className="brief-seed">
        <div className="brief-eyebrow">EVIDENCE BRIEF</div>
        <h2 className="brief-seed-title">Researching “{query.trim()}”</h2>
        <p className="brief-seed-lede">
          Surveying the document library to shape an outline grounded in what the system contains…
        </p>
        <div className="brief-generating">
          <div className="brief-researching-head">
            <span className="brief-spinner" />
            <span className="brief-researching-label">Deep research in progress</span>
          </div>
          <div className="brief-activity">
            {brief.generatingActivity.map((ev, i) => (
              <div className="brief-activity-row" key={`${ev.tag}-${i}`}>
                <span className={tagClass(ev.tag)}>{ev.tag}</span>
                <span>{ev.text}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="brief-seed">
      <div className="brief-eyebrow">EVIDENCE BRIEF</div>
      <h2 className="brief-seed-title">Turn a topic into a research brief</h2>
      <p className="brief-seed-lede">
        Enter a topic to automatically generate a brief outline based on the documents library, or
        enter the outline yourself. Then in the next screen you can have Evidence Lab research each
        heading to generate a brief with citations.
      </p>

      <div className="brief-seed-card">
        <label className="brief-label" htmlFor="brief-topic">
          Topic
        </label>
        <textarea
          id="brief-topic"
          className="brief-textarea"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Enter your brief title here"
          rows={2}
        />

        <label className="brief-label brief-label-spaced" htmlFor="brief-instructions">
          Instructions <span className="brief-label-hint">(optional — guides the headings)</span>
        </label>
        <textarea
          id="brief-instructions"
          className="brief-textarea brief-textarea-sm"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          placeholder="e.g. focus on East Africa, prioritise RCTs since 2018, structure around outcomes"
          rows={2}
        />

        <div className="brief-seed-num">
          <label className="brief-label" htmlFor="brief-numheadings">
            Number of sections
          </label>
          <input
            id="brief-numheadings"
            type="number"
            min={1}
            max={20}
            className="brief-number"
            value={numHeadings}
            onChange={(e) =>
              setNumHeadings(Math.max(1, Math.min(20, Number(e.target.value) || 1)))
            }
          />
        </div>

        {error && <div className="brief-error">{error}</div>}
        <div className="brief-seed-actions">
          <button
            className="brief-btn brief-btn-primary"
            onClick={generateOutline}
            disabled={!query.trim()}
          >
            <IconSparkle /> Generate outline
          </button>
          <button className="brief-btn brief-btn-secondary" onClick={startManual}>
            Write my own headings
          </button>
          <button
            className="brief-btn brief-btn-secondary brief-seed-load"
            onClick={() => brief.setHistoryOpen(true)}
          >
            <IconHistory /> Load a saved brief
            {brief.history.length > 0 && (
              <span className="brief-count-badge">{brief.history.length}</span>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
