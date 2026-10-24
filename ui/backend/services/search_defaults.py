"""System defaults for search and AI-summary settings.

The backend twin of ``SYSTEM_DEFAULTS`` in ``ui/frontend/src/utils/searchUrl.ts``:
the settings the search UI starts from before a user's group settings (and the
URL) are applied. The evaluation harness layers the same defaults under an
experiment's run config so a "run as group" experiment reproduces what that
group's members see in the app, rather than the raw ``/search`` route defaults.

Keys use the snake_case names consumed by ``test_runner._run_search`` /
``_run_summary`` (the ``_GROUP_SETTING_MAP`` output). A unit test parses the
frontend literal and fails when the two drift apart.
"""

from typing import Any, Dict

from pipeline.db.config import get_default_included_section_types

SYSTEM_SEARCH_DEFAULTS: Dict[str, Any] = {
    "dense_weight": 0.8,
    "rerank": True,
    "recency_boost": False,
    "recency_weight": 0.15,
    "recency_scale_days": 365,
    "keyword_boost_short_queries": True,
    "min_chunk_size": 100,
    "auto_min_score": False,
    "deduplicate": True,
    "field_boost": True,
    # Same encoding the UI sends on /search ("field:weight,...").
    "field_boost_fields": "country:1,organization:0.5",
    "wide_search": False,
    "wide_group_size": 5,
    "wide_limit": 20,
    "summary_limit_results": True,
    "max_results": 20,
    # The UI always sends its summary temperature (default 0); the combo's own
    # temperature is only a fallback the UI never reaches.
    "temperature": 0,
}


def default_section_types() -> str:
    """The section types Search includes by default, as the comma-separated
    string ``/search`` accepts (config-driven, shared with the UI)."""
    return ",".join(get_default_included_section_types())
