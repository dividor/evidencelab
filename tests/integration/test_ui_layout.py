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

from scripts.ci.saved_brief import (
    BRIEF_TITLE,
    api_poster,
    build_saved_brief,
    local_storage_script,
)

pytestmark = pytest.mark.integration

UI_BASE_URL = os.getenv("UI_BASE_URL", "http://localhost:3000").rstrip("/")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")

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
    # A brief kept by the browser (scripts/ci/saved_brief.py), opened from the
    # Brief tab's list of saved briefs.
    "saved-brief": "/brief",
}

# Text the saved brief shows once it has loaded.
SAVED_BRIEF_LOADED = "Cost and sustainability"

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
  // WCAG 2.5.8's inline exception: a link in a sentence, sized by the line.
  const block = (el) => {
    let e = el.parentElement;
    while (e && getComputedStyle(e).display.startsWith('inline')) e = e.parentElement;
    return e;
  };
  const inSentence = (el) => el.tagName === 'A' && getComputedStyle(el).display === 'inline'
    && (block(el)?.textContent || '').trim().length > (el.textContent || '').trim().length;
  // The target of a checkbox or radio is its label too: clicking it ticks the box.
  const targetBox = (el) => {
    const label = el.closest('label') || (el.labels && el.labels[0]);
    return label && shown(label) ? label.getBoundingClientRect() : el.getBoundingClientRect();
  };
  const targets = [...document.querySelectorAll(selector)]
    .filter((el) => shown(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true')
    .map((el) => ({el, box: targetBox(el)}));
  const centre = (box) => [box.left + box.width / 2, box.top + box.height / 2];
  const distanceToBox = ([x, y], box) => Math.hypot(
    Math.max(box.left - x, 0, x - box.right), Math.max(box.top - y, 0, y - box.bottom));
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


@pytest.fixture(scope="module")
def saved_brief_script() -> str:
    """JavaScript that puts the saved brief, built through the API, in the browser."""
    poster = api_poster(API_BASE_URL, os.environ["API_SECRET_KEY"])
    return local_storage_script(build_saved_brief(poster))


def open_screen(
    browser: Browser, size: str, path: str, init_script: str | None = None
) -> Any:
    """A page showing PATH at SIZE, once it has loaded and its fonts are in.
    INIT_SCRIPT runs before the app's own scripts, on every load."""
    context = browser.new_context(**VIEWPORTS[size])
    if init_script:
        context.add_init_script(init_script)
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
    browser: Browser, screen: str, size: str, request: pytest.FixtureRequest
) -> None:
    init_script = (
        request.getfixturevalue("saved_brief_script")
        if screen == "saved-brief"
        else None
    )
    page = open_screen(browser, size, SCREENS[screen], init_script)
    try:
        if screen == "search-results":
            page.wait_for_selector(".result-card", timeout=30000)
        if screen == "saved-brief":
            page.get_by_text("Load a saved brief").click()
            page.get_by_text(BRIEF_TITLE).first.click()
            page.get_by_text(SAVED_BRIEF_LOADED).first.wait_for(timeout=30000)
            toolbar = page.get_by_role("group", name="Whole document actions")
            buttons = toolbar.get_by_role("button")
            assert buttons.count() > 0
            offsets = [
                (box["y"] + box["height"] / 2)
                for button in buttons.all()
                if (box := button.bounding_box()) is not None
            ]
            assert offsets and max(offsets) - min(offsets) <= 1, "Brief toolbar wraps"

        problems = layout_problems(page)
    finally:
        page.context.close()
    assert not problems, f"{screen} at {size} size:\n- " + "\n- ".join(problems)


@pytest.mark.parametrize("width,height", [(907, 600), (844, 390)])
def test_feedback_tab_when_search_is_compact_then_leaves_the_search_button_clear(
    browser: Browser, width: int, height: int
) -> None:
    page = browser.new_page(viewport={"width": width, "height": height})
    try:
        page.goto(UI_BASE_URL + "/search", wait_until="networkidle", timeout=60000)
        page.evaluate("document.fonts.ready.then(() => true)")
        search = page.locator("button.search-button:visible").first.bounding_box()
        feedback = page.get_by_role(
            "button", name="Feedback", exact=True
        ).bounding_box()
        assert search and feedback, "Search and Feedback must both be visible"
        assert (
            search["x"] + search["width"] <= feedback["x"]
            or search["y"] + search["height"] <= feedback["y"]
        ), f"Feedback overlaps Search at {width}×{height}"
        assert feedback["y"] + feedback["height"] / 2 == pytest.approx(
            height * 0.75, abs=1
        )
    finally:
        page.context.close()


@pytest.mark.parametrize("width", [320, 847])
def test_search_examples_fit_and_are_readable_on_small_screens(
    browser: Browser, width: int
):
    page = browser.new_page(viewport={"width": width, "height": 850})
    try:
        query = urllib.parse.urlencode({"dataset": RESULTS_QUERY["dataset"]})
        page.goto(f"{UI_BASE_URL}/search?{query}", wait_until="networkidle")
        examples = page.locator(".search-example-chip")
        examples.first.wait_for()
        settle(page)
        for example in examples.all():
            size = example.evaluate(
                """button => ({
                    font: parseFloat(getComputedStyle(button).fontSize),
                    height: button.offsetHeight,
                    fits: button.scrollWidth <= button.clientWidth + 1 &&
                        button.offsetWidth <= button.parentElement.clientWidth
                })"""
            )
            assert size["font"] >= 16 and size["height"] >= 44 and size["fits"], size
    finally:
        page.context.close()
