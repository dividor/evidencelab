import React from 'react';

/**
 * Collapsible help explaining how to format a test case's search filters.
 *
 * Shared by the manual case editor and the "Create Dataset + Experiment" upload
 * modal so both entry points describe the same filter contract. Rendered as a
 * native <details> disclosure (the app has no dedicated tooltip component).
 */
const FilterHelp: React.FC = () => (
  <details className="testing-filter-help">
    <summary className="testing-raw-toggle">ⓘ How do filters work?</summary>
    <div className="text-muted testing-filter-help-body">
      <p style={{ margin: '0.4rem 0' }}>
        Filters restrict which documents a case searches. In JSON they live under
        a <code>filters</code> key, e.g.
        {' '}
        <code>{'{ "filters": { … }, "params": { … } }'}</code>.
      </p>
      <ul style={{ margin: '0.4rem 0 0', paddingLeft: '1.1rem' }}>
        <li>
          <strong>Publication year</strong> — <code>published_year_min</code> and{' '}
          <code>published_year_max</code> (numbers), e.g.
          {' '}
          <code>{'"published_year_min": 2018'}</code>.
        </li>
        <li>
          <strong>Specific documents</strong> — <code>doc_titles</code>: a list of
          exact document titles <em>as they appear in the UI</em>, e.g.
          {' '}
          <code>{'"doc_titles": ["Evaluation of X", "Annual Report 2021"]'}</code>.
          Titles are matched exactly (case-insensitive); use the document picker
          above to avoid typos.
        </li>
        <li>
          <strong>Country / region</strong> — <code>country</code> and{' '}
          <code>region</code> as lists of values, e.g.
          {' '}
          <code>{'"country": ["Kenya"], "region": ["Asia and the Pacific"]'}</code>.
          Use the pickers above to choose from the data source's values.
        </li>
        <li>
          <strong>Other fields</strong> — e.g. <code>organization</code>,{' '}
          <code>document_type</code> as string values.
        </li>
      </ul>
      <p style={{ margin: '0.4rem 0 0' }}>
        Use a separate <code>params</code> key for search behaviour (e.g.{' '}
        <code>rerank</code>, <code>limit</code>), not for document filtering.
      </p>
    </div>
  </details>
);

export default FilterHelp;
