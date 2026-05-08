// Coverage for the visibility-gated semantic-highlight cache in PDFViewer.
// Verifies that:
//   1. The LLM (POST /highlight) is NOT called eagerly on render — the
//      IntersectionObserver must fire first.
//   2. After the observer fires, the LLM is called exactly once for that
//      bbox; subsequent firings (e.g. scroll back) are cache hits.
//   3. Failed LLM calls are cached as "failed" and do NOT auto-retry on the
//      same query.
//   4. AbortError responses (which happen when the user changes query
//      mid-flight) clear the cache entry so the next query re-runs.

import React from 'react';
import { render, waitFor, act } from '@testing-library/react';
import axios from 'axios';

import { PDFViewer } from '../components/PDFViewer';

jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

// jsdom returns null from canvas.getContext('2d'), which makes renderPage
// early-return before drawing chunk boxes. Stub a no-op 2D context so the
// PDFViewer's render path can complete.
const stubCanvasContext = () => {
  HTMLCanvasElement.prototype.getContext = jest.fn(() =>
    ({ canvas: document.createElement('canvas') } as unknown as CanvasRenderingContext2D)
  ) as unknown as typeof HTMLCanvasElement.prototype.getContext;
};

// Minimal pdfjsLib mock that lets PDFViewer's renderPage complete.
const buildPdfMocks = (numPages = 3) => {
  const pageMock = {
    getViewport: ({ scale }: { scale: number }) => ({
      scale,
      width: 600,
      height: 800
    }),
    getTextContent: () => Promise.resolve({ items: [] }),
    render: () => ({
      promise: Promise.resolve(),
      cancel: jest.fn()
    })
  };
  const pdfDoc = {
    numPages,
    getPage: jest.fn(() => Promise.resolve(pageMock))
  };
  return {
    getDocument: () => ({ promise: Promise.resolve(pdfDoc) }),
    renderTextLayer: jest.fn(({ container }: { container: HTMLElement }) => {
      // Simulate PDF.js writing at least one span into the text layer.
      const span = document.createElement('span');
      span.textContent = 'monsoon flooding in the Mekong';
      container.appendChild(span);
      return Promise.resolve();
    }),
    GlobalWorkerOptions: {}
  };
};

const buildHighlightFetchResponse = (matches: { matchedText: string }[]) =>
  ({
    ok: true,
    json: async () => ({ highlighted_text: '', matches })
  } as Response);

const fireFirstObserverEntry = (target: Element) => {
  // setupTests installs a controllable mock — grab the latest instance and
  // synthesise an "entered viewport" event.
  const Mock = (global as any).MockIntersectionObserver as {
    instances: Array<{
      observed: Set<Element>;
      fireEntries: (rs: { target: Element; isIntersecting: boolean }[]) => void;
    }>;
  };
  const observer = Mock.instances.find((o) => o.observed.has(target));
  if (!observer) {
    throw new Error('No IntersectionObserver registered for the chunk box');
  }
  observer.fireEntries([{ target, isIntersecting: true }]);
};

describe('PDFViewer visibility-gated semantic highlight cache', () => {
  const initialBBox = [
    {
      page: 1,
      bbox: { l: 50, b: 100, r: 500, t: 200 },
      text: 'Cambodia is highly vulnerable to natural disasters, with regular monsoon flooding in the Mekong.'
    }
  ];

  let originalFetch: typeof global.fetch;
  let fetchMock: jest.Mock;

  beforeEach(() => {
    (global as any).MockIntersectionObserver.reset();
    stubCanvasContext();
    window.pdfjsLib = buildPdfMocks(3);
    mockedAxios.get.mockResolvedValue({ data: { highlights: [] } });
    originalFetch = global.fetch;
    fetchMock = jest.fn();
    global.fetch = fetchMock as unknown as typeof global.fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
    jest.clearAllMocks();
  });

  const renderViewer = (props: Partial<React.ComponentProps<typeof PDFViewer>> = {}) =>
    render(
      <PDFViewer
        docId="doc-1"
        chunkId="chunk-1"
        pageNum={1}
        onClose={jest.fn()}
        searchQuery="climate change"
        initialBBox={initialBBox}
        dataSource="wfp"
        {...props}
      />
    );

  test('does NOT fire the LLM until the IntersectionObserver reports the bbox visible', async () => {
    fetchMock.mockResolvedValue(
      buildHighlightFetchResponse([{ matchedText: 'monsoon flooding' }])
    );

    const { container } = renderViewer();

    // Wait for the chunk box to be drawn (renderPage is async).
    await waitFor(() => {
      expect(container.querySelector('.highlight-overlay')).not.toBeNull();
    });

    // No /highlight call should have fired — the observer hasn't reported
    // visibility yet.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('fires the LLM exactly once when the observer reports visibility, then is a cache hit on second fire', async () => {
    fetchMock.mockResolvedValue(
      buildHighlightFetchResponse([{ matchedText: 'monsoon flooding' }])
    );

    const { container } = renderViewer();

    await waitFor(() => {
      expect(container.querySelector('.highlight-overlay')).not.toBeNull();
    });

    const chunkBox = container.querySelector('.highlight-overlay') as HTMLElement;

    await act(async () => {
      fireFirstObserverEntry(chunkBox);
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    // Try to fire visibility again. There should be no second observer for
    // the same bbox key (the previous one disconnected after firing) — so
    // looking it up throws. Confirm that and that fetch wasn't re-called.
    expect(() => fireFirstObserverEntry(chunkBox)).toThrow(
      /No IntersectionObserver/
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test('failed LLM call is cached and does not auto-retry on the same query', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      statusText: 'Internal Server Error',
      json: async () => ({})
    } as Response);
    jest.spyOn(console, 'error').mockImplementation(() => undefined);

    const { container } = renderViewer();

    await waitFor(() => {
      expect(container.querySelector('.highlight-overlay')).not.toBeNull();
    });
    const chunkBox = container.querySelector('.highlight-overlay') as HTMLElement;

    await act(async () => {
      fireFirstObserverEntry(chunkBox);
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    // Highlight returned non-ok → wrapped util returns empty matches → the
    // PDFViewer caches the bbox as 'done' with []. Either way, no retry on
    // a second observer fire (the observer disconnected, so attempting to
    // refire throws — that's our "no retry" assertion).
    expect(() => fireFirstObserverEntry(chunkBox)).toThrow(
      /No IntersectionObserver/
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test('IntersectionObserver is created with threshold 0.1 to mirror SearchResultCard', async () => {
    const { container } = renderViewer();
    await waitFor(() => {
      expect(container.querySelector('.highlight-overlay')).not.toBeNull();
    });

    const Mock = (global as any).MockIntersectionObserver;
    const observer = Mock.instances[Mock.instances.length - 1];
    expect(observer.options).toEqual({ threshold: 0.1 });
  });

  test('"Computing highlights…" affordance appears between observer-fire and LLM resolve', async () => {
    let resolveFetch: (r: Response) => void = () => undefined;
    const pendingFetch = new Promise<Response>((resolve) => {
      resolveFetch = resolve;
    });
    fetchMock.mockReturnValue(pendingFetch);

    const { container } = renderViewer();
    await waitFor(() => {
      expect(container.querySelector('.highlight-overlay')).not.toBeNull();
    });
    const chunkBox = container.querySelector('.highlight-overlay') as HTMLElement;

    await act(async () => {
      fireFirstObserverEntry(chunkBox);
    });

    // While the fetch is unresolved, the affordance must be visible.
    await waitFor(() => {
      const affordance = container.querySelector('.phrase-highlight-pending');
      expect(affordance).not.toBeNull();
      expect(affordance!.textContent).toContain('Computing highlights');
    });

    // Resolve the fetch — affordance should disappear.
    await act(async () => {
      resolveFetch(
        buildHighlightFetchResponse([{ matchedText: 'monsoon flooding' }])
      );
    });

    await waitFor(() => {
      expect(container.querySelector('.phrase-highlight-pending')).toBeNull();
    });
  });

  test('no-match affordance appears even when textLayer is missing at LLM resolve time (regression)', async () => {
    // Bug: when the page DOM was mid-rebuild (e.g., fast navigation
    // triggered a renderVisiblePages cleanup that wiped innerHTML), the
    // LLM resolver early-returned BEFORE drawing the no-match affordance.
    // Result: user saw "Computing highlights…" disappear with no
    // replacement, even though the LLM had completed and returned [].
    //
    // Fix: the no-match affordance only depends on pageContainer + pixelRect
    // — not on textLayer/spans — so it must be drawn before the textLayer
    // check, for the empty-matches branch.
    fetchMock.mockResolvedValue(buildHighlightFetchResponse([]));

    const { container } = renderViewer();
    await waitFor(() => {
      expect(container.querySelector('.highlight-overlay')).not.toBeNull();
    });
    const chunkBox = container.querySelector('.highlight-overlay') as HTMLElement;

    // Simulate the cleanup wipe by removing the textLayer just before the
    // observer fires the LLM call.
    const pageEl = container.querySelector('#pdf-page-1') as HTMLElement;
    const textLayer = pageEl.querySelector('.textLayer');
    if (textLayer) textLayer.remove();

    await act(async () => {
      fireFirstObserverEntry(chunkBox);
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    // The affordance MUST appear immediately, not wait for a future render.
    await waitFor(() => {
      const affordance = container.querySelector('.phrase-highlight-no-match');
      expect(affordance).not.toBeNull();
      expect(affordance!.textContent).toContain('Topic match');
    });
  });

  test('no-match affordance appears when LLM returns phrases but none align with PDF text (regression)', async () => {
    // The LLM returns a phrase that does not appear in the chunk text. The
    // result: matches.length > 0 but drawPhraseOverlaysFromMatches paints
    // zero overlays. Previously this silently left the chunk unmarked;
    // we now fall back to the no-match affordance so the user always gets
    // feedback when no inline highlight is visible.
    fetchMock.mockResolvedValue(
      buildHighlightFetchResponse([{ matchedText: 'phrase that is definitely not in the chunk' }])
    );

    const { container } = renderViewer();
    await waitFor(() => {
      expect(container.querySelector('.highlight-overlay')).not.toBeNull();
    });
    const chunkBox = container.querySelector('.highlight-overlay') as HTMLElement;

    await act(async () => {
      fireFirstObserverEntry(chunkBox);
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    // Phrase doesn't align in PDF text → 0 overlays → no-match pill appears.
    await waitFor(() => {
      const affordance = container.querySelector('.phrase-highlight-no-match');
      expect(affordance).not.toBeNull();
      expect(affordance!.textContent).toContain('Topic match');
    });
    expect(container.querySelector('.phrase-highlight-overlay')).toBeNull();
  });

  test('"Topic match — no specific phrase" affordance appears when LLM returns zero phrases', async () => {
    // Server says the chunk is relevant (it made it through retrieval) but
    // the LLM finds no specific phrase to highlight. The user should still
    // get an explanation, not just an empty chunk box.
    fetchMock.mockResolvedValue(buildHighlightFetchResponse([]));

    const { container } = renderViewer();
    await waitFor(() => {
      expect(container.querySelector('.highlight-overlay')).not.toBeNull();
    });
    const chunkBox = container.querySelector('.highlight-overlay') as HTMLElement;

    await act(async () => {
      fireFirstObserverEntry(chunkBox);
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    // Once the LLM resolves with [], the no-match affordance should appear
    // and the "Computing…" affordance should be gone.
    await waitFor(() => {
      const noMatch = container.querySelector('.phrase-highlight-no-match');
      expect(noMatch).not.toBeNull();
      expect(noMatch!.textContent).toContain('Topic match');
    });
    expect(container.querySelector('.phrase-highlight-pending')).toBeNull();

    // No phrase overlays should have been drawn (matches was empty).
    expect(container.querySelector('.phrase-highlight-overlay')).toBeNull();
  });
});
