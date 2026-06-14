import React, { useState } from 'react';
import type { ExperimentDetail as ExperimentDetailType, TestDataset, TestExperiment } from '../../types/testing';
import DatasetList from './testing/DatasetList';
import DatasetEditor from './testing/DatasetEditor';
import ExperimentList from './testing/ExperimentList';
import ExperimentEditor from './testing/ExperimentEditor';
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
/*  Experiments sub-view (list -> editor / detail)                    */
/* ------------------------------------------------------------------ */

type ExpMode =
  | { kind: 'list' }
  | { kind: 'create' }
  | { kind: 'edit'; experiment: TestExperiment }
  | { kind: 'detail'; id: string };

interface ExperimentsViewProps {
  dataset: TestDataset | null;
  onClearDataset: () => void;
}

const ExperimentsView: React.FC<ExperimentsViewProps> = ({ dataset, onClearDataset }) => {
  const [mode, setMode] = useState<ExpMode>({ kind: 'list' });

  const goList = () => setMode({ kind: 'list' });

  if (mode.kind === 'create' || mode.kind === 'edit') {
    return (
      <ExperimentEditor
        experiment={mode.kind === 'edit' ? mode.experiment : null}
        initialDatasetId={mode.kind === 'create' ? dataset?.id ?? null : null}
        onBack={goList}
        onSaved={(id) => setMode({ kind: 'detail', id })}
      />
    );
  }

  if (mode.kind === 'detail') {
    return (
      <ExperimentDetail
        experimentId={mode.id}
        onBack={goList}
        onEdit={(exp: ExperimentDetailType) => setMode({ kind: 'edit', experiment: exp })}
      />
    );
  }

  return (
    <ExperimentList
      dataset={dataset}
      onOpen={(exp: TestExperiment) => setMode({ kind: 'detail', id: exp.id })}
      onEdit={(exp: TestExperiment) => setMode({ kind: 'edit', experiment: exp })}
      onCreate={() => setMode({ kind: 'create' })}
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
