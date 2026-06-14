import React, { useState } from 'react';
import type { TestDataset, TestExperiment } from '../../types/testing';
import DatasetList from './testing/DatasetList';
import DatasetEditor from './testing/DatasetEditor';
import ExperimentList from './testing/ExperimentList';
import ExperimentDetail from './testing/ExperimentDetail';

type SubView = 'datasets' | 'experiments';

/* ------------------------------------------------------------------ */
/*  Datasets sub-view (list -> editor)                                */
/* ------------------------------------------------------------------ */

interface DatasetsViewProps {
  onViewExperiments: (dataset: TestDataset) => void;
}

const DatasetsView: React.FC<DatasetsViewProps> = ({ onViewExperiments }) => {
  const [selected, setSelected] = useState<TestDataset | null>(null);

  if (selected) {
    return (
      <DatasetEditor
        dataset={selected}
        onBack={() => setSelected(null)}
        onViewExperiments={onViewExperiments}
      />
    );
  }
  return <DatasetList onOpen={setSelected} />;
};

/* ------------------------------------------------------------------ */
/*  Experiments sub-view (list -> detail)                             */
/* ------------------------------------------------------------------ */

interface ExperimentsViewProps {
  dataset: TestDataset | null;
  onClearDataset: () => void;
}

const ExperimentsView: React.FC<ExperimentsViewProps> = ({ dataset, onClearDataset }) => {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  if (selectedId) {
    return (
      <ExperimentDetail
        experimentId={selectedId}
        onBack={() => setSelectedId(null)}
      />
    );
  }
  return (
    <ExperimentList
      dataset={dataset}
      onOpen={(exp: TestExperiment) => setSelectedId(exp.id)}
      onBack={dataset ? onClearDataset : undefined}
    />
  );
};

/* ------------------------------------------------------------------ */
/*  Shell                                                             */
/* ------------------------------------------------------------------ */

const TestingManager: React.FC = () => {
  const [subView, setSubView] = useState<SubView>('datasets');
  // When the user clicks "view experiments" from a dataset, we scope the
  // experiments list to that dataset.
  const [experimentDataset, setExperimentDataset] = useState<TestDataset | null>(null);

  const goToExperiments = (dataset: TestDataset) => {
    setExperimentDataset(dataset);
    setSubView('experiments');
  };

  const switchSubView = (view: SubView) => {
    if (view === 'experiments') {
      setExperimentDataset(null);
    }
    setSubView(view);
  };

  return (
    <div className="admin-tab-content testing-manager">
      <div className="testing-subnav">
        <button
          className={`btn-sm ${subView === 'datasets' ? 'btn-primary' : ''}`}
          onClick={() => switchSubView('datasets')}
        >
          Datasets
        </button>
        <button
          className={`btn-sm ${subView === 'experiments' ? 'btn-primary' : ''}`}
          onClick={() => switchSubView('experiments')}
        >
          Experiments
        </button>
      </div>

      {subView === 'datasets' ? (
        <DatasetsView onViewExperiments={goToExperiments} />
      ) : (
        <ExperimentsView
          dataset={experimentDataset}
          onClearDataset={() => setExperimentDataset(null)}
        />
      )}
    </div>
  );
};

export default TestingManager;
