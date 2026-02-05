import React from 'react';

export const DocumentLinksCell: React.FC<{ doc: any }> = ({ doc }) => {
  const webLink = doc.report_url;
  const pdfLink = doc.pdf_url;

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
          Web
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
          Document
        </a>
      )}
      {!webLink && !pdfLink && '-'}
    </td>
  );
};
