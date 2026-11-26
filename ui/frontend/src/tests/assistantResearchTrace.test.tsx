import React from 'react';
import { render, screen } from '@testing-library/react';
import { TextDecoder, TextEncoder } from 'util';
import { ToolCallPanel } from '../components/assistant/ToolCallPanel';
import { AgentStatus } from '../components/assistant/AgentStatus';
import { streamAssistantChat } from '../utils/assistantStream';

jest.mock('../config', () => ({ __esModule: true, default: '/api', API_KEY: undefined }));

test('carries the stream and evidence gap from search progress into the search details', async () => {
  const originalFetch = global.fetch;
  const previousDecoder = global.TextDecoder;
  global.TextDecoder = TextDecoder as typeof global.TextDecoder;
  const packet = {
    type: 'search_status',
    queries: [{
      query: 'cost per cured individual in acute malnutrition treatment',
      result_count: 20,
      stream: 'Cost-efficiency',
      reason: 'The first results listed delivery costs without the cost per cure.',
    }],
  };
  const read = jest.fn()
    .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode(
      `data: ${JSON.stringify(packet)}\n\ndata: {"type":"done","messageId":"test"}\n\n`
    ) })
    .mockResolvedValueOnce({ done: true });
  global.fetch = jest.fn().mockResolvedValue({ ok: true, body: { getReader: () => ({ read }) } });
  const handlers = {
    onPhase: jest.fn(), onPlan: jest.fn(), onSearchStatus: jest.fn(), onToken: jest.fn(),
    onSources: jest.fn(), onDone: jest.fn(), onError: jest.fn(),
  };

  try {
    await streamAssistantChat({ apiBaseUrl: '/api', query: 'test', dataSource: 'wfp', handlers });
    const calls = handlers.onSearchStatus.mock.calls[0][0];
    expect(calls[0]).toMatchObject({ stream: packet.queries[0].stream, reason: packet.queries[0].reason });
    render(<ToolCallPanel toolCalls={calls} defaultExpanded />);
    expect(screen.getByText(packet.queries[0].stream)).toBeVisible();
    expect(screen.getByText(packet.queries[0].reason)).toBeVisible();
    expect(screen.getByText('Cost per cured individual in acute malnutrition treatment')).toBeVisible();
    render(<AgentStatus phase="searching" toolCalls={calls} searchQueries={['recovery rate by cohort']} />);
    expect(screen.getByText('Recovery rate by cohort')).toBeVisible();
    render(<AgentStatus phase="checking_citations" toolCalls={calls} />);
    expect(screen.getByText('Checking citations')).toBeVisible();
  } finally {
    global.fetch = originalFetch;
    global.TextDecoder = previousDecoder;
  }
});
