import os

import requests

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
DATA_SOURCE = "uneg"
API_KEY = os.getenv("API_SECRET_KEY")


def _get_api_headers():
    headers = {}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    return headers


def test_title_search_keyword_matches_existing_doc():
    """
    Integration: Title search matches on all keywords for known doc.
    """
    query = "liberia main report"
    expected_title = "Independent Country Programme Evaluation: Liberia - Main Report"
    response = requests.get(
        f"{API_BASE_URL}/search/titles",
        headers=_get_api_headers(),
        params={
            "q": query,
            "limit": 50,
            "data_source": DATA_SOURCE,
        },
    )
    assert (
        response.status_code == 200
    ), f"Title search API failed: {response.status_code} {response.text}"
    data = response.json()
    titles = [item.get("title") for item in data if item.get("title")]
    assert expected_title in titles, (
        f"Expected title not found for query '{query}'. " f"Found {len(titles)} titles."
    )
