import React from 'react';

interface DocumentMetadataCellProps {
  doc: any;
  onOpenToc: (doc: any) => void;
  onOpenMetadata: (doc: any) => void;
}

export const DocumentMetadataCell: React.FC<DocumentMetadataCellProps> = ({
  doc,
  onOpenToc,
  onOpenMetadata,
}) => (
  <td className="doc-metadata">
    {doc.toc && (
      <a
        href="#"
        className="doc-link"
        title="Display document table of contents if the parser was able to extract"
        onClick={(event) => {
          event.preventDefault();
          onOpenToc(doc);
        }}
      >
        Contents
      </a>
    )}
    <a
      href="#"
      className="doc-link"
      title="Display all fields for this document"
      onClick={(event) => {
        event.preventDefault();
        onOpenMetadata(doc);
      }}
    >
      JSON
    </a>
  </td>
);
