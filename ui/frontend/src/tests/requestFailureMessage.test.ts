import { requestFailureMessage } from '../utils/assistantStream';

const response = (status: number, statusText: string, body: unknown) =>
  ({ status, statusText, json: async () => body }) as unknown as Response;

describe('requestFailureMessage', () => {
  test('shows the API reason', async () => {
    const r = response(403, 'Forbidden', { detail: 'You don\'t have access to this data source.' });
    expect(await requestFailureMessage(r)).toBe(
      'Request failed: 403: You don\'t have access to this data source.',
    );
  });

  test('names each field a 422 rejected', async () => {
    const r = response(422, 'Unprocessable Entity', {
      detail: [
        {
          loc: ['body', 'brief_section', 'instructions'],
          msg: 'String should have at most 5000 characters',
        },
      ],
    });
    expect(await requestFailureMessage(r)).toBe(
      'Request failed: 422: brief_section.instructions: String should have at most 5000 characters',
    );
  });

  test('shows a 429 reason as it is', async () => {
    const message =
      "Today's AI allowance for this site has been used. Search still works; AI features return at 00:00 UTC.";
    const r = response(429, 'Too Many Requests', { detail: message });
    expect(await requestFailureMessage(r)).toBe(message);
  });

  test('keeps the status for a 429 without a reason', async () => {
    const r = response(429, 'Too Many Requests', { error: 'Rate limit exceeded: 10 per 1 minute' });
    expect(await requestFailureMessage(r)).toBe('Request failed: 429 Too Many Requests');
  });

  test('keeps the status when the body is not JSON', async () => {
    const r = {
      status: 502,
      statusText: 'Bad Gateway',
      json: async () => {
        throw new Error('not json');
      },
    } as unknown as Response;
    expect(await requestFailureMessage(r)).toBe('Request failed: 502 Bad Gateway');
  });
});
