import React from 'react';
import { buildTimelineStages, formatTimestamp } from './documentsModalUtils';

interface TimelineModalProps {
  isOpen: boolean;
  onClose: () => void;
  timelineDoc: any;
}

export const TimelineModal: React.FC<TimelineModalProps> = ({ isOpen, onClose, timelineDoc }) => {
  if (!isOpen || !timelineDoc) {
    return null;
  }

  const stages = buildTimelineStages(timelineDoc.stages || {});

  return (
    <div className="preview-overlay" onClick={onClose}>
      <div className="modal-panel timeline-modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h2>Processing Timeline</h2>
          <button onClick={onClose} className="modal-close">
            ×
          </button>
        </div>
        <div className="modal-body">
          <div className="timeline-doc-title">{timelineDoc.title || 'Untitled'}</div>
          <div className="timeline-container">
            {stages.map((stageInfo, index) => (
              <TimelineStageItem
                key={stageInfo.stageName}
                stageInfo={stageInfo}
                isLast={index === stages.length - 1}
              />
            ))}
          </div>
          {timelineDoc.pipeline_elapsed_seconds !== undefined && (
            <div className="timeline-total">
              Total pipeline time: <strong>{timelineDoc.pipeline_elapsed_seconds}s</strong>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const TimelineStageItem: React.FC<{
  stageInfo: ReturnType<typeof buildTimelineStages>[number];
  isLast: boolean;
}> = ({ stageInfo, isLast }) => (
  <div
    className={`timeline-item ${stageInfo.isSuccess ? 'success' : ''} ${
      stageInfo.isFailed ? 'failed' : ''
    } ${stageInfo.isPending ? 'pending' : ''}`}
  >
    <div className="timeline-marker">
      {stageInfo.isSuccess && <span className="marker-icon success">✓</span>}
      {stageInfo.isFailed && <span className="marker-icon failed">✗</span>}
      {stageInfo.isPending && <span className="marker-icon pending">○</span>}
    </div>
    <div className="timeline-content">
      <div className="timeline-label">
        {stageInfo.label}
        {stageInfo.stage?.elapsed_seconds !== undefined && (
          <span className="timeline-elapsed">{stageInfo.stage.elapsed_seconds}s</span>
        )}
      </div>
      {stageInfo.stage && (
        <>
          <div className="timeline-timestamp">{formatTimestamp(stageInfo.stage.at)}</div>
          {stageInfo.stage.error && <div className="timeline-error">{stageInfo.stage.error}</div>}
          {stageInfo.stage.page_count !== undefined && (
            <div className="timeline-meta">
              {stageInfo.stage.page_count} pages, {stageInfo.stage.word_count || 0} words
            </div>
          )}
          {stageInfo.stage.method && (
            <div className="timeline-meta">Method: {stageInfo.stage.method}</div>
          )}
          {stageInfo.stage.sections_count !== undefined && (
            <div className="timeline-meta">{stageInfo.stage.sections_count} sections</div>
          )}
          {stageInfo.stage.chunks_count !== undefined && (
            <div className="timeline-meta">{stageInfo.stage.chunks_count} chunks</div>
          )}
        </>
      )}
    </div>
    {!isLast && (
      <div className={`timeline-connector ${stageInfo.isSuccess ? 'completed' : ''}`}></div>
    )}
  </div>
);
