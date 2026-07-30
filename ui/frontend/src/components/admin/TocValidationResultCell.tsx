import React from 'react';
import type { TocValidationResult } from '../../types/api';

interface TocValidationResultCellProps {
  result?: TocValidationResult;
  /** True when this row's result was added or changed by the most recent run. */
  changed?: boolean;
}

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
}) => {
  if (!result) {
    return (
      <td className="toc-validation-cell">
        <span className="status-badge status-untested">Not tested</span>
      </td>
    );
  }

  return (
    <td className="toc-validation-cell">
      <span className={`status-badge status-${result.status}`}>
        {STATUS_LABEL.get(result.status) || result.status}
      </span>
      {changed && <span className="badge badge-default">updated</span>}
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
