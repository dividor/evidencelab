import React, { useState } from 'react';

interface StarRatingProps {
  /** Current score (0 = no rating, 1–5 = rated) */
  score: number;
  /** Callback when a star is clicked — receives new score (1–5) */
  onChange?: (score: number) => void;
  /** Size in pixels for each star (default 16) */
  size?: number;
  /** If provided, clicking opens the full rating modal with the selected score */
  onRequestModal?: (selectedScore: number) => void;
  /** If true, render read-only (no hover/click) */
  readOnly?: boolean;
  /** Extra class name */
  className?: string;
}

const StarRating: React.FC<StarRatingProps> = ({
  score,
  onChange,
  size = 16,
  onRequestModal,
  readOnly = false,
  className = '',
}) => {
  const [hoverIndex, setHoverIndex] = useState<number>(0);

  const handleClick = (starIndex: number) => {
    if (readOnly) return;
    if (onRequestModal) {
      onRequestModal(starIndex);
      return;
    }
    onChange?.(starIndex);
  };

  const displayScore = hoverIndex || score;

  return (
    <span
      className={`star-rating ${className}`}
      style={{ display: 'inline-flex', gap: '1px', cursor: readOnly ? 'default' : 'pointer' }}
    >
      {[1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          className={`star-rating-star ${i <= displayScore ? 'filled' : ''}`}
          style={{
            fontSize: `${size}px`,
            lineHeight: 1,
            transition: 'color 0.15s',
            color: i <= displayScore ? '#F59E0B' : '#D1D9D7',
            userSelect: 'none',
          }}
          onClick={(e) => {
            e.stopPropagation();
            handleClick(i);
          }}
          onMouseEnter={() => !readOnly && setHoverIndex(i)}
          onMouseLeave={() => !readOnly && setHoverIndex(0)}
          role={readOnly ? undefined : 'button'}
          aria-label={`Rate ${i} star${i !== 1 ? 's' : ''}`}
          tabIndex={readOnly ? undefined : 0}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              handleClick(i);
            }
          }}
        >
          ★
        </span>
      ))}
    </span>
  );
};

export default StarRating;
