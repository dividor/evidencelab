import React from 'react';

export const DocumentLinksCell: React.FC<{ doc: any; dataSource?: string }> = ({ doc, dataSource }) => {
  const webLink = doc.report_url;
  const pdfLink = doc.pdf_url;
  const source = (doc.data_source || dataSource || '').toUpperCase();
  const org = doc.organization || '';

  return (
    <td className="doc-links">
      {webLink && (
        <a
          href={webLink}
          target="_blank"
          rel="noopener noreferrer"
          className="doc-link"
          title="Hosting page for the document"
        >
          {source ? `${source} Hosting Page` : 'Hosting Page'}
        </a>
      )}
      {pdfLink && (
        <a
          href={pdfLink}
          target="_blank"
          rel="noopener noreferrer"
          className="doc-link"
          title="Source document"
        >
          {org ? `${org} Document` : 'Document'}
        </a>
      )}
      {!webLink && !pdfLink && '-'}
    </td>
  );
};
