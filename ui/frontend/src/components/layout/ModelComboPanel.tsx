import React from 'react';
import { ModelComboConfig } from '../../types/api';

interface ModelComboPanelProps {
  config: ModelComboConfig;
  displayName: string;
}

interface ModelRowProps {
  label: string;
  value: string;
  location?: string;
}

const ModelRow: React.FC<ModelRowProps> = ({ label, value, location }) => (
  <div className="model-combo-panel-row">
    <span className="model-combo-panel-label">{label}</span>
    <span className="model-combo-panel-value">{value}</span>
    {location && (
      <span className="model-combo-panel-badge">{location}</span>
    )}
  </div>
);

export const ModelComboPanel: React.FC<ModelComboPanelProps> = ({ config, displayName }) => (
  <div className="model-combo-panel">
    <div className="model-combo-panel-title">{displayName}</div>
    <ModelRow
      label="Embedding"
      value={config.embedding_model_id ?? config.embedding_model}
      location={config.embedding_model_location}
    />
    {config.sparse_model && (
      <ModelRow
        label="Sparse"
        value={config.sparse_model}
        location={config.sparse_model_location}
      />
    )}
    <ModelRow
      label="Summary"
      value={config.summarization_model.model}
      location={config.summarization_model_location}
    />
    <ModelRow
      label="Highlighting"
      value={config.semantic_highlighting_model.model}
      location={config.semantic_highlighting_location}
    />
    {config.assistant_model && (
      <ModelRow
        label="Assistant"
        value={config.assistant_model.model}
        location={config.assistant_model_location}
      />
    )}
    <ModelRow
      label="Reranker"
      value={config.reranker_model}
      location={config.reranker_model_location}
    />
  </div>
);
