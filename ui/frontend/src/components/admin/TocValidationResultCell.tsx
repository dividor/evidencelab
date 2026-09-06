import React from 'react';
import type { TocValidationResult } from '../../types/api';

interface TocValidationResultCellProps {
  result?: TocValidationResult;
  /** True when this row's result was added or changed by the most recent run. */
  changed?: boolean;
  /** True when a human reviewer has approved this document's section tagging. */
  approved?: boolean;
}

/**
 * Prominent, self-contained marker that a human signed off on the tagging.
 * Shown independently of the automated verdict (an approved document may still
 * be "Fail" or "Not tested" — approval records human judgement, not the check).
 */
const ApprovedBadge: React.FC = () => (
  <span
    className="toc-approved-badge"
    title="A human reviewer approved this document's section classifications"
  >
    <span aria-hidden="true">✓</span> Human-approved
  </span>
);

const STATUS_LABEL = new Map<string, string>([
  ['pass', 'Pass'],
  ['fail', 'Fail'],
  ['skipped', 'Skipped'],
]);

const formatTimestamp = (iso: string): string => {
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? iso : parsed.toLocaleString();
};

/** Short explanation of why a document could not be validated. */
const REASON_LABEL = new Map<string, string>([
  ['missing_metadata_range', 'no body page range in metadata'],
  ['missing_toc_classified', 'no classified contents'],
]);

const describeReasons = (reasons: string[]): string =>
  reasons.map((reason) => REASON_LABEL.get(reason) || reason).join(', ');

/**
 * Renders a document's TOC validation verdict: status chip, what was flagged,
 * and when it was last checked. Shows "Not tested" when there is no result yet.
 */
export const TocValidationResultCell: React.FC<TocValidationResultCellProps> = ({
  result,
  changed,
  approved,
}) => {
  if (!result) {
    return (
      <td className="toc-validation-cell">
        <div className="toc-validation-chips">
          <span className="status-badge status-untested">Not tested</span>
          {approved && <ApprovedBadge />}
        </div>
      </td>
    );
  }

  return (
    <td className="toc-validation-cell">
      <div className="toc-validation-chips">
        <span className={`status-badge status-${result.status}`}>
          {STATUS_LABEL.get(result.status) || result.status}
        </span>
        {approved && <ApprovedBadge />}
        {changed && <span className="badge badge-default">updated</span>}
      </div>
      {result.status === 'fail' && (
        <div className="toc-validation-detail" title={
          result.excluded_sections
            .map((sec) => `[${sec.label}] ${sec.title} (p.${sec.page})`)
            .join('\n')
        }>
          {result.num_excluded} excluded section
          {result.num_excluded === 1 ? '' : 's'}: {result.excluded_section_types.join(', ')}
        </div>
      )}
      {result.status === 'skipped' && result.reasons.length > 0 && (
        <div className="toc-validation-detail">{describeReasons(result.reasons)}</div>
      )}
      {result.status === 'pass' && (
        <div className="toc-validation-detail">
          {result.sections_in_range} section
          {result.sections_in_range === 1 ? '' : 's'} in range, all included
        </div>
      )}
      <div className="toc-validation-meta">{formatTimestamp(result.validated_at)}</div>
    </td>
  );
};

export default TocValidationResultCell;
