import React from 'react';
import { buildErrorText } from './documentsTableRowUtils';

export const DocumentErrorCell: React.FC<{ doc: any }> = ({ doc }) => (
  <td className="doc-error">{buildErrorText(doc)}</td>
);
