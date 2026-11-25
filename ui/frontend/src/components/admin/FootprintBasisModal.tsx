import React, { useCallback, useEffect } from 'react';

// ---------------------------------------------------------------------------
// Types — match the footprint parts of the /llm-usage/summary response.
// ---------------------------------------------------------------------------

// One model a line's figures rest on, with its output tokens on that line.
export interface BasisEntry {
  model: string;
  ecologits_models: string[];
  assumed: boolean;
  assumption: string | null;
  output_tokens: number;
}

interface NumberRange {
  min: number;
  max: number;
}

// The figures EcoLogits used for one of its models.
export interface EcoModelDetail {
  provider: string;
  model: string;
  architecture: string;
  active_parameters_billion: NumberRange;
  total_parameters_billion: NumberRange;
  size_published: boolean;
  model_card: string | null;
  pue: NumberRange;
  onsite_water_l_per_kwh: NumberRange;
  zone: string;
  zone_from_config: boolean;
  grid_gwp_kgco2eq_per_kwh: number;
  grid_water_l_per_kwh: number;
}

// Everything behind one model's figures.
export interface FootprintSource {
  model: string;
  assumed: boolean;
  assumption: string | null;
  citations: { label: string; url: string }[];
  models: EcoModelDetail[];
}

export interface FootprintMethod {
  name: string;
  version: string;
}

// The table line whose badge was clicked.
export interface BasisLine {
  label: string;
  unestimatedTokens: number;
}

// ---------------------------------------------------------------------------
// Static method notes, from EcoLogits' documentation (checked 2026-11-25).
// ---------------------------------------------------------------------------

const ECOLOGITS_SITE = 'https://ecologits.ai/latest/';
const ECOLOGITS_METHOD = 'https://ecologits.ai/latest/methodology/llm_inference/';
const ECOLOGITS_CLOSED_MODELS = 'https://ecologits.ai/latest/methodology/proprietary_models/';
const ECOLOGITS_PAPER = 'https://doi.org/10.21105/joss.07471';
const ECOLOGITS_CODE = 'https://github.com/mlco2/ecologits';
const ML_ENERGY = 'https://ml.energy/leaderboard/';
const WATER_PAPER = 'https://arxiv.org/abs/2304.03271';
const METHOD_LINK_TEXT = 'EcoLogits method';

const ExternalLink: React.FC<{ href: string; children: React.ReactNode }> = ({ href, children }) => (
  <a href={href} target="_blank" rel="noopener noreferrer">
    {children}
  </a>
);

const METHOD_NOTES: ReadonlyArray<{ title: string; text: string; links: [string, string][] }> = [
  {
    title: 'Energy',
    text:
      'EcoLogits estimates the electricity a call uses from the number of tokens the model ' +
      'generates and its active parameters (the part of the model used for each token). The ' +
      'relation is fitted to measurements of open models served on NVIDIA H100 GPUs, from the ' +
      'ML.ENERGY Leaderboard. It then adds the rest of the server and the data centre’s ' +
      'overhead (its PUE).',
    links: [
      [METHOD_LINK_TEXT, ECOLOGITS_METHOD],
      ['ML.ENERGY Leaderboard', ML_ENERGY],
    ],
  },
  {
    title: 'Closed models',
    text:
      'OpenAI, Anthropic and Google don’t publish their models’ sizes. EcoLogits estimates ' +
      'them from leaked data, benchmarks and prices, and assumes 10–30% of a ' +
      'mixture-of-experts model is active for each token. These size ranges, and ranges in ' +
      'data-centre efficiency, are why the figures are ranges.',
    links: [['How EcoLogits sizes closed models', ECOLOGITS_CLOSED_MODELS]],
  },
  {
    title: 'Emissions',
    text:
      'The electricity’s emissions, using the carbon intensity of the electricity mix where ' +
      'the model runs (from Our World in Data), plus a share of the emissions from making the ' +
      'server hardware, spread over a 3-year life.',
    links: [[METHOD_LINK_TEXT, ECOLOGITS_METHOD]],
  },
  {
    title: 'Water',
    text:
      'Water evaporated to cool the data centre (on site) and to generate its electricity ' +
      '(off site). Water used to make the hardware is not included.',
    links: [
      [METHOD_LINK_TEXT, ECOLOGITS_METHOD],
      ['Li et al. (2025)', WATER_PAPER],
    ],
  },
  {
    title: 'Not included',
    text:
      'Prompt tokens (EcoLogits counts only the tokens a model generates), networking, ' +
      'storage, and training the model.',
    links: [],
  },
];

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

const formatNumber = (n: number): string => n.toLocaleString(undefined, { maximumSignificantDigits: 3 });

const formatRange = (r: NumberRange): string =>
  r.min === r.max ? formatNumber(r.min) : `${formatNumber(r.min)}–${formatNumber(r.max)}`;

const sizeText = (m: EcoModelDetail): string => {
  if (m.architecture === 'moe') {
    return (
      `Mixture of experts: ${formatRange(m.total_parameters_billion)} billion parameters, ` +
      `${formatRange(m.active_parameters_billion)} billion active per token`
    );
  }
  return `${formatRange(m.active_parameters_billion)} billion parameters`;
};

// ---------------------------------------------------------------------------
// Parts
// ---------------------------------------------------------------------------

const CELL: React.CSSProperties = { padding: '0.35rem 0.5rem', verticalAlign: 'top', borderTop: '1px solid #e3e7ee' };

const ModelRow: React.FC<{ m: EcoModelDetail }> = ({ m }) => (
  <tr>
    <td style={CELL}>
      <code>{`${m.provider}/${m.model}`}</code>
    </td>
    <td style={CELL}>
      {sizeText(m)}
      <div className="text-muted" style={{ fontSize: '0.75rem' }}>
        {m.size_published ? 'Published' : 'Not published: EcoLogits’ estimate'}
        {m.model_card && (
          <>
            {' · '}
            <ExternalLink href={m.model_card}>model card</ExternalLink>
          </>
        )}
      </div>
    </td>
    <td style={CELL}>
      PUE {formatRange(m.pue)}
      <div className="text-muted" style={{ fontSize: '0.75rem' }}>
        {formatRange(m.onsite_water_l_per_kwh)} L water per kWh on site
      </div>
    </td>
    <td style={CELL}>
      {m.zone}
      <div className="text-muted" style={{ fontSize: '0.75rem' }}>
        {m.zone_from_config ? 'Set in config.json' : 'EcoLogits’ default for this provider'}
        {': '}
        {formatNumber(m.grid_gwp_kgco2eq_per_kwh)} kg CO{'₂'}e and {formatNumber(m.grid_water_l_per_kwh)} L
        water per kWh
      </div>
    </td>
  </tr>
);

const EcoModelTable: React.FC<{ models: EcoModelDetail[] }> = ({ models }) => (
  <>
    <h3 style={{ fontSize: '0.95rem', margin: '0.9rem 0 0.3rem' }}>
      Estimated as {models.length > 1 ? `${models.length} EcoLogits models` : 'an EcoLogits model'}
    </h3>
    {models.length > 1 && (
      <p style={{ margin: '0 0 0.3rem' }}>
        Each figure is the range from the lowest of these models’ estimates to the highest.
      </p>
    )}
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
        <thead>
          <tr style={{ textAlign: 'left' }}>
            <th style={CELL}>Model</th>
            <th style={CELL}>Size</th>
            <th style={CELL}>Data centre</th>
            <th style={CELL}>Electricity mix</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <ModelRow key={`${m.provider}/${m.model}`} m={m} />
          ))}
        </tbody>
      </table>
    </div>
  </>
);

const AssumptionBox: React.FC<{ source: FootprintSource }> = ({ source }) => (
  <div
    className="footprint-assumption"
    style={{ background: '#fff4e5', border: '1px solid #f0c27b', borderRadius: 6, padding: '0.6rem 0.75rem', margin: '0.75rem 0' }}
  >
    <strong>Assumption.</strong> {source.assumption}
    {source.citations.length > 0 && (
      <ol style={{ margin: '0.4rem 0 0', paddingLeft: '1.2rem' }}>
        {source.citations.map((c) => (
          <li key={c.url}>
            <ExternalLink href={c.url}>{c.label}</ExternalLink>
          </li>
        ))}
      </ol>
    )}
  </div>
);

const LineSummary: React.FC<{ entry: BasisEntry; line: BasisLine }> = ({ entry, line }) => (
  <p style={{ marginTop: 0 }}>
    <strong>{line.label}:</strong> {entry.output_tokens.toLocaleString()} output tokens from {entry.model}.
    {line.unestimatedTokens > 0 && (
      <>
        {' '}
        {line.unestimatedTokens.toLocaleString()} other output tokens here have no estimate: they came from
        models with no estimate, or from before estimates began.
      </>
    )}
  </p>
);

const MethodNotes: React.FC = () => (
  <ul style={{ paddingLeft: '1.2rem', margin: '0.25rem 0 0.75rem' }}>
    {METHOD_NOTES.map((note) => (
      <li key={note.title} style={{ marginBottom: '0.4rem' }}>
        <strong>{note.title}.</strong> {note.text}
        {note.links.map(([text, href], i) => (
          <React.Fragment key={href}>
            {i === 0 ? ' ' : ' · '}
            <ExternalLink href={href}>{text}</ExternalLink>
          </React.Fragment>
        ))}
      </li>
    ))}
  </ul>
);

const MethodFooter: React.FC<{ method: FootprintMethod }> = ({ method }) => (
  <p className="text-muted" style={{ fontSize: '0.78rem', marginBottom: 0 }}>
    Estimates by {method.name} {method.version}: <ExternalLink href={ECOLOGITS_SITE}>ecologits.ai</ExternalLink>
    {' · '}
    <ExternalLink href={ECOLOGITS_PAPER}>
      Rincé, S. and Banse, A. (2025). EcoLogits: Evaluating the Environmental Impacts of Generative AI. Journal
      of Open Source Software 10(111), 7471
    </ExternalLink>
    {' · '}
    <ExternalLink href={ECOLOGITS_CODE}>source code</ExternalLink>. See System Monitoring in the docs for how
    Evidence Lab uses it.
  </p>
);

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

interface FootprintBasisModalProps {
  entry: BasisEntry;
  line: BasisLine;
  source: FootprintSource;
  method: FootprintMethod;
  onClose: () => void;
}

const FootprintBasisModal: React.FC<FootprintBasisModalProps> = ({ entry, line, source, method, onClose }) => {
  const stopPropagation = useCallback((e: React.MouseEvent) => e.stopPropagation(), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="preview-overlay" onClick={onClose}>
      <div
        className="modal-panel footprint-basis-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="footprint-basis-title"
        onClick={stopPropagation}
      >
        <div className="modal-header">
          <h2 id="footprint-basis-title">
            How the footprint of {source.model} is estimated
            {source.assumed && <span className="footprint-badge-assumed"> · Assumed</span>}
          </h2>
          <div className="modal-header-actions">
            <button onClick={onClose} className="modal-close" aria-label="Close">
              &times;
            </button>
          </div>
        </div>
        <div className="modal-body" style={{ fontSize: '0.86rem', lineHeight: 1.5 }}>
          <LineSummary entry={entry} line={line} />
          {source.assumed && <AssumptionBox source={source} />}
          {source.models.length > 0 && <EcoModelTable models={source.models} />}
          <h3 style={{ fontSize: '0.95rem', margin: '0.9rem 0 0.3rem' }}>How EcoLogits estimates a call</h3>
          <MethodNotes />
          <MethodFooter method={method} />
        </div>
      </div>
    </div>
  );
};

export default FootprintBasisModal;
