"""Exercise the packaged view inside an MCP Apps message host."""

import base64
import json
import re
from html import escape

import pytest
from playwright.sync_api import Page, expect

from mcp_server.resources.heatmap import load_heatmap_html

pytestmark = pytest.mark.integration

HOST_SCRIPT = """
const frame = document.querySelector('iframe');
const grid = __GRID__;
const seen = [];
window.addEventListener('message', ({source, data}) => {
  if (source !== frame.contentWindow || data?.jsonrpc !== '2.0') return;
  const reply = result => source.postMessage({jsonrpc: '2.0', id: data.id, result}, '*');
  switch (data.method) {
    case 'ui/initialize':
      reply({
        protocolVersion: data.params.protocolVersion,
        hostInfo: {name: 'Test host', version: '1.0'},
        hostCapabilities: {serverTools: {}, message: {text: {}}, openLinks: {}},
        hostContext: {displayMode: 'inline', availableDisplayModes: ['inline']}
      });
      break;
    case 'ui/notifications/initialized':
      source.postMessage({
        jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: {structuredContent: grid}
      }, '*');
      break;
    case 'tools/call':
      seen.push(data.params);
      if (data.params.name === 'heatmap_cell') {
        reply({content: [], structuredContent: {
          count: 2, total_documents: 2, next_offset: null,
          documents: [
            {doc_id: 'one', title: '<img src=x onerror=alert(1)>', paragraph_count: null},
            {doc_id: 'two', title: 'Education evaluation', paragraph_count: null,
             organization: 'UNICEF', year: '2024'},
          ],
        }});
      } else {
        reply({content: [], structuredContent: {
          ...grid,
          request: data.params.arguments.request,
          rows: {dimension: 'document_type', label: 'Document type', omitted: 0,
                 values: [{value: 'Evaluation', label: 'Evaluation'}]},
        }});
      }
      break;
    case 'ui/message':
    case 'ui/open-link':
      seen.push({method: data.method, params: data.params});
      reply({});
      break;
  }
  document.querySelector('output').textContent = JSON.stringify(seen);
});
"""


def app_host(html: str) -> str:
    grid = {
        "request": {
            "data_source": "uneg",
            "row_dimension": "organization",
            "column_dimension": "published_year",
            "row_values": ["UNICEF"],
            "column_values": ["2024"],
            "filters": {},
            "metric": "documents",
        },
        "rows": {
            "dimension": "organization",
            "label": "Organization",
            "omitted": 0,
            "values": [{"value": "UNICEF", "label": "UNICEF"}],
        },
        "columns": {
            "dimension": "published_year",
            "label": "Published year",
            "omitted": 0,
            "values": [{"value": "2024", "label": "2024"}],
        },
        "row_dimensions": {
            "organization": "Organization",
            "document_type": "Document type",
        },
        "column_dimensions": {"published_year": "Published year"},
        "candidate_limit": 50000,
        "cutoff": None,
        "counts": [[2]],
        "capped_cells": [[False]],
        "fingerprints": [["a" * 32]],
        "web_url": "https://example.org/?tab=heatmap",
    }
    script = HOST_SCRIPT.replace("__GRID__", json.dumps(grid))
    csp = (
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; script-src 'unsafe-inline'; "
        "style-src 'unsafe-inline'; img-src data:\">"
    )
    html = html.replace("<head>", f"<head>{csp}", 1)
    return (
        "<!doctype html><title>Heatmapper test host</title>"
        "<style>body{margin:0}iframe{width:100%;height:44rem;border:0}</style>"
        '<iframe id="heatmapper" sandbox="allow-scripts" '
        f'srcdoc="{escape(html, quote=True)}"></iframe>'
        "<output hidden></output>"
        f"<script>{script}</script>"
    )


def set_custom_branding(tmp_path, monkeypatch, title):
    stock = re.search(
        r'<script type="application/json" id="stock-fonts">(.*?)</script>',
        load_heatmap_html(),
    )
    assert stock is not None
    face = json.loads(stock[1])[0]
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    (fonts / "Library.woff2").write_bytes(base64.b64decode(face["data"]))
    (tmp_path / "manifest.json").write_text(
        json.dumps({"name": title}), encoding="utf-8"
    )
    (tmp_path / "theme.css").write_text(
        ":root { --brand-primary-light: #85c1fd; --font-body: 'Library'; }"
        "@font-face { font-family: 'Library'; src: url('./fonts/Library.woff2'); }",
        encoding="utf-8",
    )
    monkeypatch.setenv("MCP_BRANDING_DIR", str(tmp_path))


@pytest.mark.parametrize("title", ["Evidence Lab", "Evaluation Library"])
def test_heatmap_view_renders_and_forwards_actions(
    page: Page, title, tmp_path, monkeypatch
):
    custom = title == "Evaluation Library"
    monkeypatch.delenv("MCP_BRANDING_DIR", raising=False)
    if custom:
        set_custom_branding(tmp_path, monkeypatch, title)
        page.emulate_media(color_scheme="dark")
    page.set_viewport_size({"width": 380, "height": 760})
    requests = []
    page.on("request", lambda request: requests.append(request.url))
    page.set_content(app_host(load_heatmap_html()))
    frame = page.frame_locator("#heatmapper")
    expect(frame.get_by_role("heading", name=f"{title} Heatmapper")).to_be_visible()
    assert frame.locator("header img").evaluate("(logo) => logo.naturalWidth") > 0
    if custom:
        assert (
            frame.locator("html").evaluate(
                "(root) => getComputedStyle(root).getPropertyValue('--brand-primary-light').trim()"
            )
            == "#85c1fd"
        )
    assert frame.locator("html").evaluate(
        "(root) => root.scrollWidth === root.clientWidth"
    )
    loaded = frame.locator("html").evaluate(
        """async () => {
            await document.fonts.ready;
            return [...document.fonts]
                .filter(face => face.status === "loaded")
                .map(face => face.family);
        }"""
    )
    assert "Poppins" in loaded
    body_font = "Library" if custom else "Open Sans"
    assert body_font in loaded
    assert body_font in frame.locator("body").evaluate(
        "(body) => getComputedStyle(body).fontFamily"
    )
    cell = frame.get_by_role("button", name="UNICEF, 2024, 2 documents")
    expect(cell).to_be_visible()
    cell.focus()
    page.keyboard.press("Enter")
    expect(
        frame.get_by_role("heading", name="UNICEF × 2024 · 2 documents")
    ).to_be_visible()
    expect(frame.get_by_text("Education evaluation")).to_be_visible()
    expect(frame.locator(".doc-meta").get_by_text("UNICEF · 2024")).to_be_visible()
    expect(frame.get_by_text("<img src=x onerror=alert(1)>")).to_be_visible()
    assert frame.locator("#documents img").count() == 0
    frame.get_by_role("button", name="Ask Claude about this cell").click()
    frame.get_by_role("link", name=f"Open in {title}").click()
    frame.get_by_label("Rows").select_option("document_type")
    frame.get_by_role("button", name="Generate").click()
    expect(
        frame.get_by_role("button", name="Evaluation, 2024, 2 documents")
    ).to_be_visible()

    actions = json.loads(page.locator("output").text_content())
    assert actions[0]["name"] == "heatmap_cell"
    assert actions[0]["arguments"]["request"]["fingerprint"] == "a" * 32
    assert actions[1]["method"] == "ui/message"
    assert actions[2] == {
        "method": "ui/open-link",
        "params": {"url": "https://example.org/?tab=heatmap"},
    }
    assert actions[3]["arguments"]["request"]["row_dimension"] == "document_type"
    assert requests == []
