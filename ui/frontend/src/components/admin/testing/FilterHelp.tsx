import React from 'react';

/**
 * Collapsible help explaining how to format the `filters` column of a case
 * CSV upload. Manual case entry needs no JSON — the case editor builds its
 * filter controls from the data source's configured search filter fields.
 * Rendered as a native <details> disclosure (the app has no dedicated tooltip
 * component).
 */
const FilterHelp: React.FC = () => (
  <details className="testing-filter-help">
    <summary className="testing-raw-toggle">ⓘ How do CSV filters work?</summary>
    <div className="text-muted testing-filter-help-body">
      <p style={{ margin: '0.4rem 0' }}>
        The optional <code>filters</code> column restricts which documents a
        case searches, using the same filter fields the search page offers for
        the data source (they come from the data source&apos;s configuration).
        The cell holds a JSON object:
      </p>
      <ul style={{ margin: '0.4rem 0 0', paddingLeft: '1.1rem' }}>
        <li>
          <strong>Facet fields</strong> — lists of values keyed by the field
          name, e.g.
          {' '}
          <code>{'"country": ["Kenya"]'}</code>.
        </li>
        <li>
          <strong>Range fields</strong> — <code>{'<field>_min'}</code> /{' '}
          <code>{'<field>_max'}</code> (numbers), e.g.
          {' '}
          <code>{'"published_year_min": 2018'}</code>.
        </li>
        <li>
          <strong>Specific documents</strong> — <code>doc_titles</code>: a list of
          exact document titles <em>as they appear in the UI</em>, e.g.
          {' '}
          <code>{'"doc_titles": ["Evaluation of X", "Annual Report 2021"]'}</code>.
          Titles are matched exactly (case-insensitive). A value that matches no
          document yields zero results for the case, never an unfiltered run.
        </li>
      </ul>
    </div>
  </details>
);

export default FilterHelp;
