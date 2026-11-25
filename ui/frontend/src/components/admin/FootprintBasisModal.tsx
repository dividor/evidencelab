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

// An estimate in kWh, kg CO2e and litres, each as a range.
interface EstimateRanges {
  energy_kwh: NumberRange;
  gwp_kgco2eq: NumberRange;
  water_l: NumberRange;
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
  // This model's estimate for the example call.
  example_estimate: EstimateRanges;
}

// Everything behind one model's figures.
export interface FootprintSource {
  model: string;
  assumed: boolean;
  assumption: string | null;
  citations: { label: string; url: string }[];
  models: EcoModelDetail[];
  // The example call the pop-up works through, and the estimate recorded for it.
  example_output_tokens: number;
  example_estimate: EstimateRanges | null;
}

export interface FootprintMethod {
  name: string;
  version: string;
}

// ---------------------------------------------------------------------------
// Links and method notes, from EcoLogits' documentation (checked 2026-11-25).
// ---------------------------------------------------------------------------

const ECOLOGITS_SITE = 'https://ecologits.ai/latest/';
const ECOLOGITS_METHOD = 'https://ecologits.ai/latest/methodology/llm_inference/';
const ECOLOGITS_CLOSED_MODELS = 'https://ecologits.ai/latest/methodology/proprietary_models/';
const ECOLOGITS_PAPER = 'https://doi.org/10.21105/joss.07471';
const ECOLOGITS_CODE = 'https://github.com/mlco2/ecologits';
const ML_ENERGY = 'https://ml.energy/leaderboard/';
const WATER_PAPER = 'https://arxiv.org/abs/2304.03271';
const METHOD_LINK_TEXT = 'EcoLogits method';
const SMALL_TEXT: React.CSSProperties = { fontSize: '0.75rem' };
const HEADING: React.CSSProperties = { fontSize: '0.95rem', margin: '1rem 0 0.3rem' };

const ExternalLink: React.FC<{ href: string; children: React.ReactNode }> = ({ href, children }) => (
  <a href={href} target="_blank" rel="noopener noreferrer">
    {children}
  </a>
);

const EcoLogitsLink: React.FC = () => <ExternalLink href={ECOLOGITS_SITE}>EcoLogits</ExternalLink>;

const METHOD_NOTES: ReadonlyArray<{ title: string; text: string; links: [string, string][] }> = [
  {
    title: 'Energy',
    text:
      'EcoLogits works out the electricity a call uses from two things: how many output tokens ' +
      'the model wrote, and how big the model is. Its formula comes from measurements of open ' +
      'models running on NVIDIA H100 GPUs, published as the ML.ENERGY Leaderboard. It then adds ' +
      'the power used by the rest of the server and by the data centre’s cooling and other ' +
      'overhead (PUE).',
    links: [
      [METHOD_LINK_TEXT, ECOLOGITS_METHOD],
      ['ML.ENERGY Leaderboard', ML_ENERGY],
    ],
  },
  {
    title: 'Model sizes',
    text:
      'OpenAI, Anthropic and Google don’t publish how big their models are. EcoLogits estimates ' +
      'their sizes from leaked information, benchmark results and prices, so each size is a ' +
      'range. Some models use only part of themselves for each token (a "mixture of experts"); ' +
      'for these, EcoLogits assumes 10–30% is used. These size ranges, and ranges in data-centre ' +
      'efficiency, are why every figure is a range.',
    links: [['How EcoLogits estimates model sizes', ECOLOGITS_CLOSED_MODELS]],
  },
  {
    title: 'Emissions',
    text:
      'The greenhouse gases from generating that electricity, using the carbon intensity of the ' +
      'electricity where the model runs (data from Our World in Data). Plus a share of the ' +
      'emissions from making the server hardware, spread over a 3-year life.',
    links: [[METHOD_LINK_TEXT, ECOLOGITS_METHOD]],
  },
  {
    title: 'Water',
    text:
      'The water evaporated to cool the data centre, and the water used to generate its ' +
      'electricity. Water used to make the hardware is not included.',
    links: [
      [METHOD_LINK_TEXT, ECOLOGITS_METHOD],
      ['Li et al. (2025)', WATER_PAPER],
    ],
  },
  {
    title: 'Not included',
    text:
      'The prompt (EcoLogits counts only the tokens a model writes), networking, storage, and ' +
      'training the model.',
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
      `${formatRange(m.total_parameters_billion)} billion parameters, of which ` +
      `${formatRange(m.active_parameters_billion)} billion are used for each token`
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
      <div className="text-muted" style={SMALL_TEXT}>
        {m.size_published ? 'Published by its maker' : 'Not published. This is EcoLogits’ estimate.'}
        {m.model_card && (
          <>
            {' '}
            <ExternalLink href={m.model_card}>Model card</ExternalLink>
          </>
        )}
      </div>
    </td>
    <td style={CELL}>
      PUE {formatRange(m.pue)}
      <div className="text-muted" style={SMALL_TEXT}>
        {formatRange(m.onsite_water_l_per_kwh)} litres of water per kWh to cool it
      </div>
    </td>
    <td style={CELL}>
      {m.zone}
      <div className="text-muted" style={SMALL_TEXT}>
        {m.zone_from_config
          ? 'Set in config.json.'
          : 'EcoLogits’ default for this maker, because config.json doesn’t say where it runs.'}{' '}
        Each kWh there emits {formatNumber(m.grid_gwp_kgco2eq_per_kwh)} kg CO{'₂'}e and uses{' '}
        {formatNumber(m.grid_water_l_per_kwh)} litres of water to generate.
      </div>
    </td>
  </tr>
);

const modelsIntro = (count: number, assumed: boolean): React.ReactNode => {
  if (count > 1) {
    return (
      <>
        <EcoLogitsLink /> works out the footprint {count} times, as if each of these models had written the
        same output tokens. The calculation below shows how the results are combined.
      </>
    );
  }
  if (assumed) {
    return (
      <>
        <EcoLogitsLink /> works out the footprint as if this model had written the same output tokens.
      </>
    );
  }
  return (
    <>
      <EcoLogitsLink /> works out the footprint from its own figures for this model.
    </>
  );
};

const EcoModelTable: React.FC<{ models: EcoModelDetail[]; assumed: boolean }> = ({ models, assumed }) => (
  <>
    <h3 style={HEADING}>{models.length > 1 ? `The ${models.length} models the estimate uses` : 'The model the estimate uses'}</h3>
    <p style={{ margin: '0 0 0.3rem' }}>{modelsIntro(models.length, assumed)}</p>
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
        <thead>
          <tr style={{ textAlign: 'left' }}>
            <th style={CELL}>Model</th>
            <th style={CELL}>Size</th>
            <th style={CELL}>Data centre</th>
            <th style={CELL}>Where it runs</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <ModelRow key={`${m.provider}/${m.model}`} m={m} />
          ))}
        </tbody>
      </table>
    </div>
    <p className="text-muted" style={{ ...SMALL_TEXT, margin: '0.4rem 0 0' }}>
      Parameters are the numbers a model learns; bigger models have more and use more energy for each token.
      PUE is the electricity the whole data centre uses for each kWh its servers use: 1.1 means 10% more for
      cooling and other overhead. The data-centre figures are EcoLogits’ figures for the model’s maker, not
      for your cloud provider.
    </p>
  </>
);

// The main table's units: Wh, g and mL, from the API's kWh, kg and litres.
const ESTIMATE_COLUMNS: ReadonlyArray<{ label: string; pick: (e: EstimateRanges) => NumberRange }> = [
  { label: 'Energy (Wh)', pick: (e) => e.energy_kwh },
  { label: 'Emissions (g CO\u2082e)', pick: (e) => e.gwp_kgco2eq },
  { label: 'Water (mL)', pick: (e) => e.water_l },
];

const formatEstimate = (n: number): string => (n * 1000).toLocaleString(undefined, { maximumSignificantDigits: 2 });

const EstimateCells: React.FC<{ estimate: EstimateRanges }> = ({ estimate }) => (
  <>
    {ESTIMATE_COLUMNS.map(({ label, pick }) => {
      const r = pick(estimate);
      return (
        <td key={label} style={{ ...CELL, textAlign: 'right', whiteSpace: 'nowrap' }}>
          {formatEstimate(r.min)}–{formatEstimate(r.max)}
        </td>
      );
    })}
  </>
);

const calculationIntro = (count: number): string =>
  count > 1
    ? 'EcoLogits gives a range for each model, because their sizes and data centres are ranges. ' +
      'We record the lowest of the low figures and the highest of the high figures.'
    : 'EcoLogits gives a range, because the model’s size and data centre are ranges. We record that range.';

const Calculation: React.FC<{ source: FootprintSource; recorded: EstimateRanges }> = ({ source, recorded }) => (
  <>
    <h3 style={HEADING}>
      The calculation, for a call that writes {source.example_output_tokens.toLocaleString()} output tokens
    </h3>
    <p style={{ margin: '0 0 0.3rem' }}>
      {calculationIntro(source.models.length)} Every call is worked out this way with its own number of output
      tokens, and each line of the table adds up its calls.
    </p>
    <div style={{ overflowX: 'auto' }}>
      <table className="footprint-calculation" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
        <thead>
          <tr style={{ textAlign: 'left' }}>
            <th style={CELL}>Model</th>
            {ESTIMATE_COLUMNS.map(({ label }) => (
              <th key={label} style={{ ...CELL, textAlign: 'right' }}>
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {source.models.length > 1 &&
            source.models.map((m) => (
              <tr key={`${m.provider}/${m.model}`}>
                <td style={CELL}>
                  <code>{`${m.provider}/${m.model}`}</code>
                </td>
                <EstimateCells estimate={m.example_estimate} />
              </tr>
            ))}
          <tr style={{ fontWeight: 600, background: '#f8f9fa' }}>
            <td style={CELL}>Recorded for {source.model}</td>
            <EstimateCells estimate={recorded} />
          </tr>
        </tbody>
      </table>
    </div>
  </>
);

const AssumptionBox: React.FC<{ source: FootprintSource }> = ({ source }) => (
  <div
    className="footprint-assumption"
    style={{ background: '#fff4e5', border: '1px solid #f0c27b', borderRadius: 6, padding: '0.6rem 0.75rem', margin: '0.25rem 0 0.75rem' }}
  >
    <strong>Assumption</strong>
    <p style={{ margin: '0.25rem 0 0' }}>{source.assumption}</p>
    {source.citations.length > 0 && (
      <>
        <strong style={{ display: 'block', marginTop: '0.5rem' }}>Sources</strong>
        <ol style={{ margin: '0.2rem 0 0', paddingLeft: '1.2rem' }}>
          {source.citations.map((c) => (
            <li key={c.url}>
              <ExternalLink href={c.url}>{c.label}</ExternalLink>
            </li>
          ))}
        </ol>
      </>
    )}
  </div>
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
    These estimates use <EcoLogitsLink /> version {method.version}. Paper:{' '}
    <ExternalLink href={ECOLOGITS_PAPER}>
      Rincé, S. and Banse, A. (2025). EcoLogits: Evaluating the Environmental Impacts of Generative AI. Journal
      of Open Source Software 10(111), 7471
    </ExternalLink>
    . <ExternalLink href={ECOLOGITS_CODE}>Source code</ExternalLink>. For how Evidence Lab uses it, see System
    Monitoring in the docs.
  </p>
);

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

interface FootprintBasisModalProps {
  source: FootprintSource;
  method: FootprintMethod;
  onClose: () => void;
}

const FootprintBasisModal: React.FC<FootprintBasisModalProps> = ({ source, method, onClose }) => {
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
            How we estimate the footprint of {source.model}
            {source.assumed && <span className="footprint-badge-assumed"> · Assumed</span>}
          </h2>
          <div className="modal-header-actions">
            <button onClick={onClose} className="modal-close" aria-label="Close">
              &times;
            </button>
          </div>
        </div>
        <div className="modal-body" style={{ fontSize: '0.86rem', lineHeight: 1.5 }}>
          {source.assumed && <AssumptionBox source={source} />}
          {source.models.length > 0 && <EcoModelTable models={source.models} assumed={source.assumed} />}
          {source.example_estimate && <Calculation source={source} recorded={source.example_estimate} />}
          <h3 style={HEADING}>
            How <EcoLogitsLink /> works
          </h3>
          <MethodNotes />
          <MethodFooter method={method} />
        </div>
      </div>
    </div>
  );
};

export default FootprintBasisModal;
