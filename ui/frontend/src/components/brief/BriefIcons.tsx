import React from 'react';

// Crisp inline SVG icons (Feather-style, stroke-based) so the Brief tab matches
// the rest of the app's iconography instead of inconsistent unicode glyphs.

interface IconProps {
  size?: number;
}

const svgProps = (size: number) => ({
  width: size,
  height: size,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
});

export const IconPlus: React.FC<IconProps> = ({ size = 15 }) => (
  <svg {...svgProps(size)}>
    <line x1="12" y1="5" x2="12" y2="19" />
    <line x1="5" y1="12" x2="19" y2="12" />
  </svg>
);

export const IconShare: React.FC<IconProps> = ({ size = 14 }) => (
  <svg {...svgProps(size)}>
    <circle cx="18" cy="5" r="3" />
    <circle cx="6" cy="12" r="3" />
    <circle cx="18" cy="19" r="3" />
    <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
    <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
  </svg>
);

export const IconArrowLeft: React.FC<IconProps> = ({ size = 14 }) => (
  <svg {...svgProps(size)}>
    <line x1="19" y1="12" x2="5" y2="12" />
    <polyline points="12 19 5 12 12 5" />
  </svg>
);

export const IconHistory: React.FC<IconProps> = ({ size = 15 }) => (
  <svg {...svgProps(size)}>
    <path d="M3 3v5h5" />
    <path d="M3.05 13A9 9 0 1 0 6 5.3L3 8" />
    <path d="M12 7v5l3 2" />
  </svg>
);

export const IconRefresh: React.FC<IconProps> = ({ size = 14 }) => (
  <svg {...svgProps(size)}>
    <path d="M23 4v6h-6" />
    <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
  </svg>
);

export const IconClock: React.FC<IconProps> = ({ size = 14 }) => (
  <svg {...svgProps(size)}>
    <circle cx="12" cy="12" r="9" />
    <polyline points="12 7 12 12 16 14" />
  </svg>
);

export const IconEdit: React.FC<IconProps> = ({ size = 14 }) => (
  <svg {...svgProps(size)}>
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
    <path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4z" />
  </svg>
);

export const IconDownload: React.FC<IconProps> = ({ size = 14 }) => (
  <svg {...svgProps(size)}>
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="7 10 12 15 17 10" />
    <line x1="12" y1="15" x2="12" y2="3" />
  </svg>
);

export const IconSparkle: React.FC<IconProps> = ({ size = 14 }) => (
  <svg {...svgProps(size)}>
    <path d="M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17l-1.9-5.1L4.5 10l5.6-1.4z" />
  </svg>
);

export const IconCopy: React.FC<IconProps> = ({ size = 14 }) => (
  <svg {...svgProps(size)}>
    <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </svg>
);

export const IconSearch: React.FC<IconProps> = ({ size = 14 }) => (
  <svg {...svgProps(size)}>
    <circle cx="11" cy="11" r="8" />
    <line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
);

export const IconGrip: React.FC<IconProps> = ({ size = 14 }) => (
  <svg {...svgProps(size)}>
    <line x1="3" y1="6" x2="21" y2="6" />
    <line x1="3" y1="12" x2="21" y2="12" />
    <line x1="3" y1="18" x2="21" y2="18" />
  </svg>
);
