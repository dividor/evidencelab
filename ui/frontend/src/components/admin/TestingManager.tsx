import React from 'react';
import type { TestDataset, TestExperiment } from '../../types/testing';
import { openAdminLocation, useAdminLocation } from '../../utils/adminLocation';
import DatasetList from './testing/DatasetList';
import BriefEvaluationTemplates from './testing/BriefEvaluationTemplates';
import DatasetEditor from './testing/DatasetEditor';
import ExperimentList from './testing/ExperimentList';
import ExperimentEditor from './testing/ExperimentEditor';
import ExperimentDetail from './testing/ExperimentDetail';
import SavedEvaluationRecord from './testing/SavedEvaluationRecord';

function DatasetsView({ id }: { id?: string }) {
  const back = () => openAdminLocation({ page: 'testing', testing: 'datasets' });
  const openDataset = (dataset: TestDataset) => openAdminLocation({ page: 'testing', dataset: dataset.id });
  const viewExperiments = (dataset: TestDataset) =>
    openAdminLocation({ page: 'testing', testing: 'experiments', dataset: dataset.id });

  if (!id) return <DatasetList onOpen={openDataset} />;
  return (
    <SavedEvaluationRecord<TestDataset> key={id} id={id} collection="datasets" onBack={back}>
      {dataset => {
        const Editor = dataset.capability === 'brief' ? BriefEvaluationTemplates : DatasetEditor;
        return <Editor dataset={dataset} onBack={back} onViewExperiments={viewExperiments} />;
      }}
    </SavedEvaluationRecord>
  );
}

function ExperimentsView() {
  const { dataset, experiment, mode } = useAdminLocation();
  const list = { page: 'testing', testing: 'experiments', dataset };
  const back = () => openAdminLocation(list);
  const detail = (id: string) => openAdminLocation({ ...list, experiment: id });
  const edit = (exp: TestExperiment) => openAdminLocation({ ...list, experiment: exp.id, mode: 'edit' });
  const create = () => openAdminLocation({ ...list, mode: 'create' });

  if (experiment && mode === 'edit') return (
    <SavedEvaluationRecord<TestExperiment> key={experiment} id={experiment} collection="experiments" onBack={back}>
      {record => <ExperimentEditor experiment={record} onBack={back} onSaved={detail} />}
    </SavedEvaluationRecord>
  );
  if (experiment) return <ExperimentDetail key={experiment} experimentId={experiment} onBack={back} onEdit={edit} />;
  if (mode === 'create') return <ExperimentEditor initialDatasetId={dataset} onBack={back} onSaved={detail} />;

  const clearDataset = () => openAdminLocation({ page: 'testing', testing: 'experiments' });
  const renderList = (record: TestDataset | null) => (
    <ExperimentList
      dataset={record}
      onOpen={exp => detail(exp.id)}
      onEdit={edit}
      onCreate={create}
      onBack={record ? clearDataset : undefined}
    />
  );
  if (!dataset) return renderList(null);
  return (
    <SavedEvaluationRecord<TestDataset> key={dataset} id={dataset} collection="datasets" onBack={clearDataset}>
      {renderList}
    </SavedEvaluationRecord>
  );
}

export default function TestingManager() {
  const { testing, dataset } = useAdminLocation();
  const experiments = testing === 'experiments' || (!testing && !dataset);
  return (
    <div className="admin-tab-content testing-manager">
      <h3>{experiments ? 'Experiments' : 'Experiment datasets'}</h3>
      <div className="testing-subnav">
        <button className={`btn-sm ${experiments ? '' : 'btn-primary'}`}
          onClick={() => openAdminLocation({ page: 'testing', testing: 'datasets' })}>Datasets</button>
        <button className={`btn-sm ${experiments ? 'btn-primary' : ''}`}
          onClick={() => openAdminLocation({ page: 'testing', testing: 'experiments' })}>Experiments</button>
      </div>
      {experiments ? <ExperimentsView /> : <DatasetsView id={dataset} />}
    </div>
  );
}
