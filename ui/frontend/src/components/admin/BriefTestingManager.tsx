import React from 'react';
import { useAdminLocation, openAdminLocation } from '../../utils/adminLocation';
import type { SearchResult } from '../../types/api';
import BriefCheckDetail from './testing/BriefCheckDetail';
import BriefCheckList from './testing/BriefCheckList';

interface BriefTestingManagerProps {
  dataSource: string;
  // The model combo selected at the top of the page (judge = its summarisation model).
  modelCombo: string | null;
  onResultClick?: (result: SearchResult) => void;
}

/** Admin → Testing (Brief): pick a brief, run the citation check, review it. */
const BriefTestingManager: React.FC<BriefTestingManagerProps> = ({
  dataSource,
  modelCombo,
  onResultClick,
}) => {
  const { check } = useAdminLocation();
  return (
    <div className="admin-tab-content testing-manager">
      {check ? (
        <BriefCheckDetail
          key={check}
          checkId={check}
          dataSource={dataSource}
          onBack={() => openAdminLocation({page: 'testing-brief'})}
          onResultClick={onResultClick}
        />
      ) : (
        <BriefCheckList modelCombo={modelCombo} onOpenCheck={record => openAdminLocation({page: 'testing-brief', check: record.id})} />
      )}
    </div>
  );
};

export default BriefTestingManager;
