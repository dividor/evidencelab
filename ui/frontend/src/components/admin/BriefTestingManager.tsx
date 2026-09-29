import React, { useState } from 'react';
import type { SearchResult } from '../../types/api';
import type { BriefCitationCheck } from '../../types/testing';
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
  const [check, setCheck] = useState<BriefCitationCheck | null>(null);
  return (
    <div className="admin-tab-content testing-manager">
      {check ? (
        <BriefCheckDetail
          check={check}
          dataSource={dataSource}
          onBack={() => setCheck(null)}
          onResultClick={onResultClick}
        />
      ) : (
        <BriefCheckList modelCombo={modelCombo} onOpenCheck={setCheck} />
      )}
    </div>
  );
};

export default BriefTestingManager;
