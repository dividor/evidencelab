import React from 'react';

interface DocumentsPaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export const DocumentsPagination: React.FC<DocumentsPaginationProps> = ({
  currentPage,
  totalPages,
  onPageChange,
}) => {
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
    <div className="pagination-controls">
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
    </div>
  );
};
