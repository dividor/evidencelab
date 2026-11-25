/**
 * The admin Token Usage tab shows each row's estimated footprint (EcoLogits)
 * as a range, "—" where nothing was estimated, and says how many output
 * tokens have no estimate.
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
const NOVA_ASSUMPTION =
  'Amazon publishes no size for Nova 2 Lite. Its range spans the small models EcoLogits covers.';
const HAIKU_BASIS = {
  model: 'haiku-4.5',
  ecologits_models: ['anthropic/claude-haiku-4-5'],
  assumed: false,
  assumption: null,
  output_tokens: 300,
};
const NOVA_BASIS = {
  model: 'nova-2-lite',
  ecologits_models: ['anthropic/claude-haiku-4-5', 'google_genai/gemini-2.5-flash'],
  assumed: true,
  assumption: NOVA_ASSUMPTION,
  output_tokens: 200,
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
    // Hover text gives the source, and the assumption where one was made.
    expect(badges[0].title).toBe('300 output tokens. EcoLogits: anthropic/claude-haiku-4-5');
    expect(badges[1].className).toContain('footprint-badge-assumed');
    expect(badges[1].title).toContain(`Assumed: ${NOVA_ASSUMPTION}`);
    expect(badges[1].title).toContain('google_genai/gemini-2.5-flash');
  });

  test('the note lists every assumption made in the period', async () => {
    render(<LlmUsageManager />);
    await screen.findByText(PRIYA);
    const note = document.querySelector('.llm-usage-footprint-note') as HTMLElement;
    const items = Array.from(note.querySelectorAll('li')).map((li) => li.textContent);
    expect(items).toEqual([`nova-2-lite (Assumed): ${NOVA_ASSUMPTION}`]);
  });
});
