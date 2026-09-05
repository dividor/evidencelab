/**
 * Always-on click diagnostics.
 *
 * One user intermittently found that dropdown items did nothing when clicked,
 * with no console errors, and could read a console but not paste code into
 * it. This records what actually happened on every mouse press so that a
 * screenshot of the console is enough to diagnose the next such report:
 *
 *  - how long the button was held (mouse-down to mouse-up),
 *  - whether the pressed element was removed from the page before release,
 *  - whether the release landed outside the pressed control (an overlay, or
 *    a menu that closed under the pointer), in which case no click fires on
 *    that control.
 *
 * Unremarkable presses log at `console.debug`, which Chrome hides unless the
 * "Verbose" level is enabled. Anything that makes a click go missing logs at
 * `console.warn`, which shows at the default console level. One
 * `console.info` line at start-up confirms the diagnostics are running.
 */

export const SLOW_PRESS_MS = 200;
const PREFIX = '[Evidence Lab click]';
const TEXT_LIMIT = 40;
const CONTROL_SELECTOR = 'button, a, input, select, textarea, label, summary, [role="button"], [role="menuitem"]';

export interface ClickDiagnosticsOptions {
  /** Document to observe. Defaults to the global document. */
  target?: Document;
  /** Clock in milliseconds. Defaults to `performance.now`. */
  now?: () => number;
}

/** Short, screenshot-friendly description of an element: tag, id/class, text. */
export function describeElement(target: EventTarget | null): string {
  if (!(target instanceof Element)) {
    return target instanceof Node ? target.nodeName.toLowerCase() : 'nothing';
  }
  const tag = target.tagName.toLowerCase();
  const id = target.id ? `#${target.id}` : '';
  const firstClass = target.classList.length > 0 ? `.${target.classList[0]}` : '';
  // The page body's text is the whole page; quoting it says nothing useful.
  const text = tag === 'body' || tag === 'html'
    ? ''
    : (target.textContent ?? '').replace(/\s+/g, ' ').trim();
  const shortText = text.length > TEXT_LIMIT ? `${text.slice(0, TEXT_LIMIT)}…` : text;
  const quotedText = shortText ? ` "${shortText}"` : '';
  return `${tag}${id}${firstClass}${quotedText}`;
}

/** The nearest clickable control containing the pressed node, if any. */
function controlOf(node: Node): Element | null {
  const element = node instanceof Element ? node : node.parentElement;
  return element ? element.closest(CONTROL_SELECTOR) : null;
}

/**
 * Start observing mouse presses on `target`. Returns a function that stops
 * observing again.
 */
export function installClickDiagnostics(options: ClickDiagnosticsOptions = {}): () => void {
  const { target = document, now = () => performance.now() } = options;
  let pressed: Node | null = null;
  let pressedAt = 0;

  const onMouseDown = (event: MouseEvent) => {
    pressed = event.target instanceof Node ? event.target : null;
    pressedAt = now();
  };

  const onMouseUp = (event: MouseEvent) => {
    if (pressed === null) return;
    const heldMs = Math.round(now() - pressedAt);
    const released = event.target instanceof Node ? event.target : null;
    const control = controlOf(pressed);
    const summary = `${PREFIX} held ${heldMs}ms on ${describeElement(pressed)}`;

    if (!target.contains(pressed)) {
      console.warn(
        `${summary}; that element was removed from the page before the mouse was released, ` +
          `so the click was lost. Released over ${describeElement(released)}.`,
      );
    } else if (control !== null && (released === null || !control.contains(released))) {
      console.warn(
        `${summary}; released over ${describeElement(released)}, outside the pressed control, ` +
          'so no click fired on it.',
      );
    } else if (heldMs > SLOW_PRESS_MS) {
      console.warn(`${summary}; slow press (over ${SLOW_PRESS_MS}ms).`);
    } else {
      console.debug(summary);
    }
    pressed = null;
  };

  target.addEventListener('mousedown', onMouseDown, true);
  target.addEventListener('mouseup', onMouseUp, true);
  console.info(`${PREFIX} diagnostics active; presses that could lose a click are logged as warnings.`);

  return () => {
    target.removeEventListener('mousedown', onMouseDown, true);
    target.removeEventListener('mouseup', onMouseUp, true);
  };
}
