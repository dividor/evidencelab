import { fireEvent } from '@testing-library/dom';
import {
  SLOW_PRESS_MS,
  describeElement,
  installClickDiagnostics,
} from '../clickDiagnostics';

describe('clickDiagnostics', () => {
  let clock = 0;
  let uninstall: () => void;
  let debugSpy: jest.SpyInstance;
  let warnSpy: jest.SpyInstance;
  let infoSpy: jest.SpyInstance;

  const press = (downOn: Element, upOn: Element, heldMs: number) => {
    fireEvent.mouseDown(downOn);
    clock += heldMs;
    fireEvent.mouseUp(upOn);
  };

  beforeEach(() => {
    clock = 0;
    document.body.innerHTML = `
      <div id="page">
        <button id="save" class="dropdown-item primary"><span id="save-label">Saved Research</span></button>
        <p id="para">Some body text</p>
      </div>`;
    debugSpy = jest.spyOn(console, 'debug').mockImplementation(() => {});
    warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});
    infoSpy = jest.spyOn(console, 'info').mockImplementation(() => {});
    uninstall = installClickDiagnostics({ now: () => clock });
  });

  afterEach(() => {
    uninstall();
    debugSpy.mockRestore();
    warnSpy.mockRestore();
    infoSpy.mockRestore();
    document.body.innerHTML = '';
  });

  const button = () => document.getElementById('save') as HTMLElement;
  const label = () => document.getElementById('save-label') as HTMLElement;

  it('announces itself once on install', () => {
    expect(infoSpy).toHaveBeenCalledTimes(1);
    expect(infoSpy.mock.calls[0][0]).toContain('diagnostics active');
  });

  it('logs a quick press released on the same control at debug level', () => {
    press(button(), button(), 80);
    expect(warnSpy).not.toHaveBeenCalled();
    expect(debugSpy).toHaveBeenCalledTimes(1);
    expect(debugSpy.mock.calls[0][0]).toBe(
      '[Evidence Lab click] held 80ms on button#save.dropdown-item "Saved Research"',
    );
  });

  it('treats a release on another part of the same control as a normal click', () => {
    press(label(), button(), 50);
    expect(warnSpy).not.toHaveBeenCalled();
    expect(debugSpy).toHaveBeenCalledTimes(1);
  });

  it('warns about a slow press', () => {
    press(button(), button(), SLOW_PRESS_MS + 1);
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy.mock.calls[0][0]).toContain(`held ${SLOW_PRESS_MS + 1}ms`);
    expect(warnSpy.mock.calls[0][0]).toContain('slow press');
  });

  it('warns when the pressed element was removed before release', () => {
    const target = button();
    fireEvent.mouseDown(target);
    target.remove();
    clock += 120;
    fireEvent.mouseUp(document.body);
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy.mock.calls[0][0]).toContain('removed from the page before the mouse was released');
    expect(warnSpy.mock.calls[0][0]).toContain('Released over body');
  });

  it('warns when the release lands outside the pressed control', () => {
    press(button(), document.getElementById('para') as HTMLElement, 60);
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy.mock.calls[0][0]).toContain('released over p#para "Some body text"');
    expect(warnSpy.mock.calls[0][0]).toContain('outside the pressed control');
  });

  it('does not warn for presses that did not start on a control', () => {
    press(document.getElementById('para') as HTMLElement, document.body, 60);
    expect(warnSpy).not.toHaveBeenCalled();
    expect(debugSpy).toHaveBeenCalledTimes(1);
  });

  it('ignores a release with no matching press', () => {
    fireEvent.mouseUp(button());
    expect(debugSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('stops logging once uninstalled', () => {
    uninstall();
    press(button(), button(), 500);
    expect(debugSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
    uninstall = () => {};
  });

  describe('describeElement', () => {
    it('shows tag, id, first class and trimmed text', () => {
      expect(describeElement(button())).toBe('button#save.dropdown-item "Saved Research"');
    });

    it('truncates long text', () => {
      const p = document.getElementById('para') as HTMLElement;
      p.textContent = 'x'.repeat(60);
      expect(describeElement(p)).toBe(`p#para "${'x'.repeat(40)}…"`);
    });

    it('describes non-elements and nothing', () => {
      expect(describeElement(document.createTextNode('hi'))).toBe('#text');
      expect(describeElement(null)).toBe('nothing');
    });

    it('does not quote the page body text', () => {
      expect(describeElement(document.body)).toBe('body');
    });
  });
});
