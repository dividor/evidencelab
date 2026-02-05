import React from 'react';
import { getFormatLabel } from './documentsTableRowUtils';

export const DocumentFormatCell: React.FC<{ fileFormat?: string }> = ({ fileFormat }) => (
  <td>
    <span className="format-badge" role="img" aria-label={fileFormat || 'unknown'}>
      {getFormatLabel(fileFormat)}
    </span>
  </td>
);
