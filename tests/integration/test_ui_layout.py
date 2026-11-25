"""Measured layout checks: the web app on a phone and on a desktop.

Opens the main screens at 390×844 (a phone) and 1440×900 (a desktop) and fails
on what can be measured rather than judged:

- the page is wider than the screen, so it scrolls sideways, or content is
  pushed past the left edge, where no one can scroll to it ("bleeding");
- visible text smaller than 12 px;
- accessibility violations that axe-core rates serious or critical, such as
  contrast below WCAG AA or a control with no name;
- controls smaller than 24×24 px (WCAG 2.2 AA, success criterion 2.5.8),
  allowing its spacing exception and links inside a sentence;
- controls that another element covers even when scrolled to the middle of the
  screen, so a tap lands on something else.

Judgement calls (layout, wording, empty and error states) are for the UX review
in .github/review/ux-review.md. This module runs after test_pipeline_ui.py,
which leaves its test document indexed, so the search results screen has
results.
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Any, Iterator

import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Browser, sync_playwright

pytestmark = pytest.mark.integration

UI_BASE_URL = os.getenv("UI_BASE_URL", "http://localhost:3000").rstrip("/")

# The smallest text and controls allowed, in CSS pixels.
MIN_TEXT_PX = 12
MIN_TARGET_PX = 24
# axe-core impacts that fail the test.
FAILING_IMPACTS = ("serious", "critical")

VIEWPORTS: dict[str, dict[str, Any]] = {
    "phone": {
        "viewport": {"width": 390, "height": 844},
        "device_scale_factor": 3,
        "is_mobile": True,
        "has_touch": True,
    },
    "desktop": {"viewport": {"width": 1440, "height": 900}},
}

# The search test_pipeline_ui.py runs on its indexed document.
RESULTS_QUERY = {
    "q": "increasing government capacity",
    "dataset": "UN Humanitarian Evaluation Reports",
    "model_combo": "Azure Foundry",
    "rerank": "false",
}

SCREENS = {
    "search": "/search",
    "search-results": "/?" + urllib.parse.urlencode(RESULTS_QUERY),
    "research-assistant": "/assistant",
    "brief": "/brief",
    "heatmapper": "/heatmap",
    "documents": "/documents",
    "help": "/info",
}

# Measures the page as the browser lays it out. Returns sideways overflow, small
# text and small targets, each a list of {element, measured value} records.
MEASURE_JS = """
([minText, minTarget]) => {
  const root = document.documentElement;
  const width = root.clientWidth;
  const pageWidth = root.scrollWidth;

  const shown = (el) => {
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    if (parseFloat(style.opacity) === 0) return false;
    const box = el.getBoundingClientRect();
    // Visually hidden text (1 px clip boxes) is for screen readers, not eyes.
    return box.width > 1 && box.height > 1 && box.right > 0 && box.left < pageWidth;
  };
  const describe = (el) => {
    const parts = [];
    for (let e = el; e && e.nodeType === 1 && parts.length < 4; e = e.parentElement) {
      let part = e.tagName.toLowerCase();
      if (e.id) { parts.unshift(part + '#' + e.id); break; }
      const classes = [...e.classList].slice(0, 2).join('.');
      if (classes) part += '.' + classes;
      parts.unshift(part);
    }
    return parts.join(' > ');
  };
  const label = (el) => (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 40);
  const clippedSideways = (el) => {
    for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) {
      if (getComputedStyle(e).overflowX !== 'visible') return true;
    }
    return false;
  };

  const overflow = [];
  if (pageWidth > width + 1) {
    for (const el of document.body.querySelectorAll('*')) {
      if (!shown(el) || clippedSideways(el)) continue;
      const right = el.getBoundingClientRect().right;
      if (right > width + 1) overflow.push({element: describe(el), right: Math.round(right)});
    }
    overflow.sort((a, b) => b.right - a.right);
  }

  // Content pushed past the left edge can't be scrolled to at all.
  const offLeft = [];
  for (const el of document.body.querySelectorAll('*')) {
    if (!shown(el) || clippedSideways(el)) continue;
    const left = el.getBoundingClientRect().left + window.scrollX;
    if (left < -1) offLeft.push({element: describe(el), left: Math.round(left)});
  }
  offLeft.sort((a, b) => a.left - b.left);

  const smallText = new Map();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.textContent.trim();
    const el = node.parentElement;
    if (!text || !el || !shown(el)) continue;
    const px = parseFloat(getComputedStyle(el).fontSize);
    const key = describe(el);
    if (px < minText && !smallText.has(key)) {
      smallText.set(key, {element: key, px, text: text.slice(0, 40)});
    }
  }

  const selector = [
    'a[href]', 'button', 'input:not([type=hidden])', 'select', 'textarea', 'summary',
    '[role=button]', '[role=link]', '[role=tab]', '[role=checkbox]', '[role=radio]',
    '[role=switch]', '[role=menuitem]', '[role=option]',
  ].join(',');
  const targets = [...document.querySelectorAll(selector)]
    .filter((el) => shown(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true')
    .map((el) => ({el, box: el.getBoundingClientRect()}));
  const centre = (box) => [box.left + box.width / 2, box.top + box.height / 2];
  const distanceToBox = ([x, y], box) => Math.hypot(
    Math.max(box.left - x, 0, x - box.right), Math.max(box.top - y, 0, y - box.bottom));
  const inSentence = (el) => el.tagName === 'A' && getComputedStyle(el).display === 'inline'
    && (el.parentElement?.textContent || '').trim().length > (el.textContent || '').trim().length;
  const undersized = targets.filter(({el, box}) =>
    (box.width < minTarget || box.height < minTarget) && !inSentence(el));
  const smallTargets = [];
  for (const target of undersized) {
    // WCAG 2.5.8's spacing exception: a 24 px circle centred on the target
    // touches no other target, nor another small target's circle.
    const c = centre(target.box);
    const crowded = targets.some((other) => other !== target && (
      undersized.includes(other)
        ? Math.hypot(c[0] - centre(other.box)[0], c[1] - centre(other.box)[1]) < minTarget
        : distanceToBox(c, other.box) < minTarget / 2));
    if (crowded) {
      smallTargets.push({
        element: describe(target.el),
        size: Math.round(target.box.width) + '×' + Math.round(target.box.height),
        text: label(target.el),
      });
    }
  }
  return {width, pageWidth, overflow: overflow.slice(0, 8), offLeft: offLeft.slice(0, 8),
          smallText: [...smallText.values()], smallTargets};
}
"""

# Controls whose centre another element covers even when they are scrolled to
# the middle of the screen, so a tap or click there lands on something else: a
# floating button over a footer link, say. A control that merely scrolled under
# a sticky header is not reported, because scrolling brings it back.
COVERED_JS = """
() => {
  const selector = 'a[href],button,input:not([type=hidden]),select,textarea,summary,'
    + '[role=button],[role=link],[role=tab],[role=checkbox],[role=menuitem]';
  const describe = (el) => {
    const parts = [];
    for (let e = el; e && e.nodeType === 1 && parts.length < 3; e = e.parentElement) {
      let part = e.tagName.toLowerCase();
      if (e.id) { parts.unshift(part + '#' + e.id); break; }
      const classes = [...e.classList].slice(0, 2).join('.');
      if (classes) part += '.' + classes;
      parts.unshift(part);
    }
    return parts.join(' > ');
  };
  const label = (el) => (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 40);
  const covered = [];
  for (const el of document.querySelectorAll(selector)) {
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.pointerEvents === 'none' || el.disabled) continue;
    const before = el.getBoundingClientRect();
    if (before.width <= 1 || before.height <= 1) continue;
    el.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
    const box = el.getBoundingClientRect();
    if (box.top < 0 || box.left < 0 || box.bottom > innerHeight || box.right > innerWidth) continue;
    const x = box.left + box.width / 2;
    const y = box.top + box.height / 2;
    const hit = document.elementFromPoint(x, y);
    if (!hit || el.contains(hit) || hit.contains(el)) continue;
    if (el.labels && [...el.labels].some((label) => label.contains(hit))) continue;
    covered.push({element: describe(el), by: describe(hit),
                  text: label(el)});
  }
  return covered;
}
"""


# True once no finite CSS animation or transition has run for half a second,
# so the page is measured as people see it: not half-way through a fade-in, nor
# through a button's change of colour when it turns on after data has loaded.
# Spinners and other endless animations are left running. False if the page is
# still animating after 10 seconds.
SETTLED_JS = """
async () => {
  const running = () => document.getAnimations().filter((a) => a.effect
    && a.effect.getComputedTiming().iterations !== Infinity && a.playState !== 'finished');
  const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    const now = running();
    if (now.length) {
      await Promise.all(now.map((a) => a.finished.catch(() => null)));
      continue;
    }
    await pause(500);
    if (!running().length) return true;
  }
  return false;
}
"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        launched = playwright.chromium.launch(headless=True)
        yield launched
        launched.close()


def open_screen(browser: Browser, size: str, path: str) -> Any:
    """A page showing PATH at SIZE, once it has loaded and its fonts are in."""
    context = browser.new_context(**VIEWPORTS[size])
    page = context.new_page()
    page.goto(UI_BASE_URL + path, wait_until="networkidle", timeout=60000)
    page.wait_for_selector(".nav-tabs", state="attached", timeout=30000)
    page.evaluate("document.fonts.ready.then(() => true)")
    return page


def settle(page: Any) -> None:
    """Wait until PAGE has stopped animating; fail if it never does."""
    assert page.evaluate(SETTLED_JS), "the page was still animating after 10 seconds"


def layout_problems(page: Any) -> list[str]:
    """Every measured problem on PAGE, one line each."""
    settle(page)
    measured = page.evaluate(MEASURE_JS, [MIN_TEXT_PX, MIN_TARGET_PX])
    problems = []
    if measured["pageWidth"] > measured["width"] + 1:
        problems.append(
            f"page is {measured['pageWidth']} px wide on a {measured['width']} px screen; "
            "widest: "
            + "; ".join(
                f"{o['element']} (right edge {o['right']} px)"
                for o in measured["overflow"]
            )
        )
    if measured["offLeft"]:
        problems.append(
            "content cut off past the left edge: "
            + "; ".join(
                f"{o['element']} (left edge {o['left']} px)"
                for o in measured["offLeft"]
            )
        )
    problems += [
        f"text {t['px']} px (under {MIN_TEXT_PX}): {t['element']} \"{t['text']}\""
        for t in measured["smallText"]
    ]
    problems += [
        f"control {t['size']} px (under {MIN_TARGET_PX}, too close to others): "
        f"{t['element']} \"{t['text']}\""
        for t in measured["smallTargets"]
    ]
    problems += [
        f"control covered by {c['by']}: {c['element']} \"{c['text']}\""
        for c in page.evaluate(COVERED_JS)
    ]
    page.evaluate("window.scrollTo(0, 0)")
    problems += [
        axe_problem(violation)
        for violation in Axe().run(page).response["violations"]
        if violation["impact"] in FAILING_IMPACTS
    ]
    return problems


def axe_problem(violation: dict[str, Any]) -> str:
    """One line for an axe-core VIOLATION, with the colours for a contrast failure."""
    examples = []
    for node in violation["nodes"][:4]:
        where = " ".join(node["target"])
        data = (node.get("any") or [{}])[0].get("data") or {}
        if violation["id"] == "color-contrast" and isinstance(data, dict):
            where += (
                f" ({data.get('fgColor')} on {data.get('bgColor')}, "
                f"{data.get('contrastRatio')}:1, needs {data.get('expectedContrastRatio')})"
            )
        examples.append(where)
    return (
        f"axe {violation['impact']} {violation['id']}: {violation['help']} "
        f"({len(violation['nodes'])} elements, e.g. {'; '.join(examples)})"
    )


@pytest.mark.parametrize("size", list(VIEWPORTS))
@pytest.mark.parametrize("screen", list(SCREENS))
def test_ui_layout_when_screen_opened_then_fits_and_is_readable(
    browser: Browser, screen: str, size: str
) -> None:
    page = open_screen(browser, size, SCREENS[screen])
    try:
        if screen == "search-results":
            page.wait_for_selector(".result-card", timeout=30000)
        problems = layout_problems(page)
    finally:
        page.context.close()
    assert not problems, f"{screen} at {size} size:\n- " + "\n- ".join(problems)
