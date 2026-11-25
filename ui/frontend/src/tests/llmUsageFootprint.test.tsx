/**
 * The admin Token Usage tab shows each row's estimated footprint (EcoLogits)
 * as a range, "—" where nothing was estimated, and says how many output
 * tokens have no estimate. Each Basis badge opens a pop-up with the figure's
 * sources, assumptions and method.
 */
import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import axios from 'axios';
import LlmUsageManager from '../components/admin/LlmUsageManager';

jest.mock('axios');
jest.mock('../config', () => ({ __esModule: true, default: '/api' }));

const mockedAxios = axios as jest.Mocked<typeof axios>;

const PRIYA = 'Priya Raman';
const PIPELINE = '(pipeline)';
const HAIKU = 'haiku-4.5';
const NOVA = 'nova-2-lite';
const CLAUDE_HAIKU = 'claude-haiku-4-5';
const ECO_HAIKU = `anthropic/${CLAUDE_HAIKU}`;
const NOVA_ASSUMPTION =
  "Amazon doesn't publish how big Nova 2 Lite is. For each call, we run EcoLogits as each of two small models.";
const HAIKU_BASIS = {
  model: HAIKU,
  ecologits_models: [ECO_HAIKU],
  assumed: false,
  assumption: null,
  output_tokens: 300,
};
const NOVA_BASIS = {
  model: NOVA,
  ecologits_models: [ECO_HAIKU, 'google_genai/gemini-2.5-flash'],
  assumed: true,
  assumption: NOVA_ASSUMPTION,
  output_tokens: 200,
};

const SAEF_PAPER_URL = 'https://doi.org/10.1016/j.spc.2026.11.003';

const ecoModel = (provider: string, model: string, overrides: Record<string, unknown> = {}) => ({
  provider,
  model,
  architecture: 'dense',
  active_parameters_billion: { min: 10, max: 35 },
  total_parameters_billion: { min: 10, max: 35 },
  size_published: false,
  model_card: null,
  pue: { min: 1.09, max: 1.14 },
  onsite_water_l_per_kwh: { min: 0.13, max: 0.999 },
  zone: 'USA',
  zone_from_config: false,
  grid_gwp_kgco2eq_per_kwh: 0.3844,
  grid_water_l_per_kwh: 3.1321,
  ...overrides,
});

const HAIKU_SOURCE = {
  model: HAIKU,
  ecologits_models: [ECO_HAIKU],
  assumed: false,
  assumption: null,
  citations: [],
  models: [ecoModel('anthropic', CLAUDE_HAIKU)],
};
const NOVA_SOURCE = {
  model: NOVA,
  ecologits_models: NOVA_BASIS.ecologits_models,
  assumed: true,
  assumption: NOVA_ASSUMPTION,
  citations: [{ label: 'Llopis-Garcia, G. (2026)', url: SAEF_PAPER_URL }],
  models: [
    ecoModel('anthropic', CLAUDE_HAIKU, { zone: 'IRL', zone_from_config: true }),
    ecoModel('google_genai', 'gemini-2.5-flash', {
      architecture: 'moe',
      total_parameters_billion: { min: 440, max: 440 },
      active_parameters_billion: { min: 44, max: 132 },
      zone: 'IRL',
      zone_from_config: true,
    }),
  ],
};

const EMPTY_FOOTPRINT = {
  energy_kwh_min: null,
  energy_kwh_max: null,
  gwp_kgco2eq_min: null,
  gwp_kgco2eq_max: null,
  water_l_min: null,
  water_l_max: null,
};

const usageRow = (overrides: Record<string, unknown>) => ({
  bucket_start: '2026-11-23',
  group_key: 'k',
  group_label: 'label',
  request_count: 1,
  prompt_tokens: 100,
  completion_tokens: 500,
  total_tokens: 600,
  cost_usd: '0.001000',
  ...EMPTY_FOOTPRINT,
  footprint_unestimated_tokens: 0,
  footprint_basis: [],
  ...overrides,
});

const RESPONSE = {
  rows: [
    usageRow({
      group_key: 'priya@example.org',
      group_label: PRIYA,
      energy_kwh_min: 0.00005,
      energy_kwh_max: 0.00013,
      gwp_kgco2eq_min: 0.000014,
      gwp_kgco2eq_max: 0.000035,
      water_l_min: 0.000076,
      water_l_max: 0.00029,
      footprint_basis: [HAIKU_BASIS, NOVA_BASIS],
    }),
    usageRow({
      group_key: PIPELINE,
      group_label: PIPELINE,
      completion_tokens: 300,
      footprint_unestimated_tokens: 300,
    }),
  ],
  totals: {
    request_count: 2,
    prompt_tokens: 200,
    completion_tokens: 800,
    total_tokens: 1000,
    cost_usd: '0.002000',
    energy_kwh_min: 0.00005,
    energy_kwh_max: 0.00013,
    gwp_kgco2eq_min: 0.000014,
    gwp_kgco2eq_max: 0.000035,
    water_l_min: 0.000076,
    water_l_max: 0.00029,
    footprint_unestimated_tokens: 300,
    footprint_basis: [HAIKU_BASIS, NOVA_BASIS],
  },
  footprint_sources: [HAIKU_SOURCE, NOVA_SOURCE],
  footprint_method: { name: 'EcoLogits', version: '0.11.3' },
  bucket: 'week',
  group_by: 'user',
  from_date: '2026-10-26',
  to_date: '2026-11-25',
  activity_type: null,
};

const cellTexts = (row: HTMLElement): string[] =>
  within(row).getAllByRole('cell').map((cell) => cell.textContent ?? '');

describe('Token Usage footprint columns', () => {
  beforeEach(() => {
    mockedAxios.get.mockResolvedValue({ data: RESPONSE });
  });

  test('shows energy, emissions and water as ranges in Wh, g and mL', async () => {
    render(<LlmUsageManager />);
    const priya = (await screen.findByText(PRIYA)).closest('tr') as HTMLElement;
    expect(screen.getByText('Energy (Wh)')).toBeInTheDocument();
    expect(screen.getByText('Emissions (g CO₂e)')).toBeInTheDocument();
    expect(screen.getByText('Water (mL)')).toBeInTheDocument();
    const cells = cellTexts(priya);
    // kWh, kg and L from the API shown x 1000, to two significant digits.
    expect(cells.slice(-4, -1)).toEqual(['0.05–0.13', '0.014–0.035', '0.076–0.29']);
  });

  test('shows a dash where nothing was estimated, and pipeline has its own line', async () => {
    render(<LlmUsageManager />);
    const pipeline = (await screen.findByText(PIPELINE)).closest('tr') as HTMLElement;
    expect(cellTexts(pipeline).slice(-3)).toEqual(['—', '—', '—']);
  });

  test('the totals carry the footprint and the note counts unestimated tokens', async () => {
    render(<LlmUsageManager />);
    const total = (await screen.findByText('Total')).closest('tr') as HTMLElement;
    expect(cellTexts(total).slice(-4, -1)).toEqual(['0.05–0.13', '0.014–0.035', '0.076–0.29']);
    const note = document.querySelector('.llm-usage-footprint-note') as HTMLElement;
    expect(note.textContent).toContain('estimates from EcoLogits');
    expect(note.textContent).toContain('300 of 800 output tokens have no estimate');
    expect(note.textContent).toContain('from models with no estimate, or from before estimates began');
    expect(note.textContent).not.toContain('Amazon Nova');
  });

  test('the footprint columns sort by their high estimate', async () => {
    render(<LlmUsageManager />);
    await screen.findByText(PRIYA);
    fireEvent.click(screen.getByText('Emissions (g CO₂e)'));
    await waitFor(() => {
      const lastCall = mockedAxios.get.mock.calls[mockedAxios.get.mock.calls.length - 1];
      expect((lastCall[1] as { params: Record<string, string> }).params.sort_by).toBe(
        'gwp_kgco2eq_max',
      );
    });
    await screen.findByText(PRIYA);
  });

  test('each row names the models its figures rest on, and flags assumptions', async () => {
    render(<LlmUsageManager />);
    const priya = (await screen.findByText(PRIYA)).closest('tr') as HTMLElement;
    expect(screen.getByText('Basis')).toBeInTheDocument();
    const badges = Array.from(priya.querySelectorAll('.footprint-badge')) as HTMLElement[];
    expect(badges.map((b) => b.textContent)).toEqual(['haiku-4.5', 'nova-2-lite \u00b7 Assumed']);
    expect(badges.every((b) => b.tagName === 'BUTTON')).toBe(true);
    expect(badges[0].className).not.toContain('footprint-badge-assumed');
    expect(badges[1].className).toContain('footprint-badge-assumed');
  });

  test('the note lists every assumption made in the period', async () => {
    render(<LlmUsageManager />);
    await screen.findByText(PRIYA);
    const note = document.querySelector('.llm-usage-footprint-note') as HTMLElement;
    const items = Array.from(note.querySelectorAll('li')).map((li) => li.textContent);
    expect(items).toEqual([`nova-2-lite (Assumed): ${NOVA_ASSUMPTION}`]);
  });
});

describe('Basis pop-up', () => {
  beforeEach(() => {
    mockedAxios.get.mockResolvedValue({ data: RESPONSE });
  });

  const openBadge = async (label: string, rowText: string): Promise<HTMLElement> => {
    render(<LlmUsageManager />);
    const row = (await screen.findByText(rowText)).closest('tr') as HTMLElement;
    fireEvent.click(within(row).getByRole('button', { name: (name: string) => name.startsWith(label) }));
    return screen.getByRole('dialog');
  };

  test('an assumed model shows its assumption, citations and the models it spans', async () => {
    const dialog = await openBadge(NOVA, PRIYA);
    expect(within(dialog).getByText(/How we estimate the footprint of nova-2-lite/)).toBeInTheDocument();
    expect(dialog.textContent).toContain(NOVA_ASSUMPTION);
    const paper = within(dialog).getByRole('link', { name: 'Llopis-Garcia, G. (2026)' });
    expect(paper).toHaveAttribute('href', SAEF_PAPER_URL);
    expect(paper).toHaveAttribute('target', '_blank');
    expect(dialog.textContent).toContain('The 2 models the estimate uses');
    expect(dialog.textContent).toContain(
      'EcoLogits works out the footprint 2 times, as if each of these models had written the same output tokens.',
    );
    expect(dialog.textContent).toContain(ECO_HAIKU);
    expect(dialog.textContent).toContain('10–35 billion parameters');
    expect(dialog.textContent).toContain('440 billion parameters, of which 44–132 billion are used for each token');
    expect(dialog.textContent).toContain('Not published. This is EcoLogits’ estimate.');
    expect(dialog.textContent).toContain(
      'Set in config.json. Each kWh there emits 0.384 kg CO₂e and uses 3.13 litres of water to generate.',
    );
  });

  test('a covered model has no assumption and shows its own figures', async () => {
    const dialog = await openBadge(HAIKU, PRIYA);
    expect(dialog.querySelector('.footprint-assumption')).toBeNull();
    expect(dialog.textContent).toContain('The model the estimate uses');
    expect(dialog.textContent).toContain('EcoLogits works out the footprint from its own figures for this model.');
    expect(dialog.textContent).toContain('EcoLogits’ default for this maker');
  });

  test('links to EcoLogits, its method and its paper, with the version used', async () => {
    const dialog = await openBadge(HAIKU, PRIYA);
    const hrefs = within(dialog)
      .getAllByRole('link')
      .map((a) => a.getAttribute('href'));
    expect(hrefs).toEqual(
      expect.arrayContaining([
        'https://ecologits.ai/latest/',
        'https://ecologits.ai/latest/methodology/llm_inference/',
        'https://ecologits.ai/latest/methodology/proprietary_models/',
        'https://doi.org/10.21105/joss.07471',
        'https://github.com/mlco2/ecologits',
      ]),
    );
    expect(dialog.textContent).toContain('These estimates use EcoLogits version 0.11.3.');
    // Every mention of EcoLogits in the pop-up's own text links to its site.
    const ecologits = within(dialog).getAllByRole('link', { name: 'EcoLogits' });
    expect(ecologits.length).toBeGreaterThan(1);
    ecologits.forEach((a) => expect(a).toHaveAttribute('href', 'https://ecologits.ai/latest/'));
  });

  test('a totals badge opens the same pop-up', async () => {
    render(<LlmUsageManager />);
    const total = (await screen.findByText('Total')).closest('tr') as HTMLElement;
    fireEvent.click(within(total).getByRole('button', { name: (name: string) => name.startsWith(HAIKU) }));
    expect(within(screen.getByRole('dialog')).getByText(/How we estimate the footprint of haiku-4.5/)).toBeInTheDocument();
  });

  test('closes with the close button and with Escape', async () => {
    await openBadge(HAIKU, PRIYA);
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(within(screen.getByText(PRIYA).closest('tr') as HTMLElement).getByRole('button', { name: /nova-2-lite/ }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
