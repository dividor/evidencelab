import React from 'react';
import { PAGE_SIZE_OPTIONS } from './documentsUtils';

interface DocumentsPaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  /** Documents per page, chosen from PAGE_SIZE_OPTIONS. */
  pageSize: number;
  onPageSizeChange: (size: number) => void;
}

/** How many documents each page shows. */
export const PageSizeSelect: React.FC<{ pageSize: number; onChange: (size: number) => void }> = ({
  pageSize,
  onChange,
}) => (
  <label className="pagination-page-size">
    <span>Per page</span>
    <select value={pageSize} onChange={(e) => onChange(Number(e.target.value))} aria-label="Documents per page">
      {PAGE_SIZE_OPTIONS.map((size) => (
        <option key={size} value={size}>
          {size}
        </option>
      ))}
    </select>
  </label>
);

/** Page size, and the page buttons when there is more than one page. */
export const DocumentsPagination: React.FC<DocumentsPaginationProps> = ({
  currentPage,
  totalPages,
  onPageChange,
  pageSize,
  onPageSizeChange,
}) => (
  <div className="pagination-controls">
    {totalPages > 1 && (
      <PageButtons currentPage={currentPage} totalPages={totalPages} onPageChange={onPageChange} />
    )}
    <PageSizeSelect pageSize={pageSize} onChange={onPageSizeChange} />
  </div>
);

const PageButtons: React.FC<{
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}> = ({ currentPage, totalPages, onPageChange }) => {
  const pageButtons = Array.from({ length: totalPages }, (_, index) => index + 1)
    .filter((page) => Math.abs(page - currentPage) <= 2)
    .map((page) => (
      <button
        key={page}
        className={`pagination-button ${page === currentPage ? 'pagination-button-active' : ''}`}
        onClick={() => onPageChange(page)}
      >
        {page}
      </button>
    ));

  return (
    <>
      <button
        className="pagination-button"
        onClick={() => onPageChange(Math.max(1, currentPage - 1))}
        disabled={currentPage === 1}
      >
        « Previous
      </button>
      <div className="pagination-pages">
        {currentPage > 3 && (
          <>
            <button className="pagination-button" onClick={() => onPageChange(1)}>
              1
            </button>
            {currentPage > 4 && <span className="pagination-ellipsis">...</span>}
          </>
        )}
        {pageButtons}
        {currentPage < totalPages - 2 && (
          <>
            {currentPage < totalPages - 3 && <span className="pagination-ellipsis">...</span>}
            <button className="pagination-button" onClick={() => onPageChange(totalPages)}>
              {totalPages}
            </button>
          </>
        )}
      </div>
      <button
        className="pagination-button"
        onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
        disabled={currentPage === totalPages}
      >
        Next »
      </button>
    </>
  );
};
