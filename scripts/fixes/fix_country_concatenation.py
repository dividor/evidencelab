#!/usr/bin/env python3
"""
Fix concatenated country values in Qdrant and PostgreSQL.

The UNEG scraper's BeautifulSoup get_text(strip=True) concatenated
multi-country values without a separator, producing entries like
"NepalIndia" instead of "Nepal; India".

This script:
  1. Collects all unique map_country values from Qdrant chunks
  2. Identifies single-country values to build a reference list
  3. Uses greedy longest-match to split concatenated strings
  4. Updates Qdrant chunks/docs and PostgreSQL docs/chunks

Usage:
    python scripts/fixes/fix_country_concatenation.py \\
        --data-source uneg --dry-run
    python scripts/fixes/fix_country_concatenation.py \\
        --data-source uneg

Connection settings are read from .env (QDRANT_HOST, POSTGRES_HOST, etc.)
with sensible localhost defaults. Inside Docker, POSTGRES_HOST is
automatically resolved to 'postgres'.
"""

import argparse
import logging
import os
import time

from dotenv import load_dotenv
from qdrant_client import QdrantClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Comprehensive reference list of country/territory names that appear
# in the UNEG dataset.  Built from the World Bank country list plus
# common variants found in the data.
KNOWN_COUNTRIES = sorted(
    [
        "Afghanistan",
        "Albania",
        "Algeria",
        "Andorra",
        "Angola",
        "Antigua and Barbuda",
        "Argentina",
        "Armenia",
        "Aruba",
        "Australia",
        "Austria",
        "Azerbaijan",
        "Bahamas, The",
        "Bahrain",
        "Bangladesh",
        "Barbados",
        "Belarus",
        "Belgium",
        "Belize",
        "Benin",
        "Bhutan",
        "Bolivia",
        "Bosnia and Herzegovina",
        "Botswana",
        "Brazil",
        "Brunei Darussalam",
        "Bulgaria",
        "Burkina Faso",
        "Burundi",
        "Cabo Verde",
        "Cambodia",
        "Cameroon",
        "Canada",
        "Cayman Islands",
        "Central African Republic",
        "Chad",
        "Chile",
        "China",
        "Colombia",
        "Comoros",
        "Congo, Dem. Rep.",
        "Congo, Rep.",
        "Costa Rica",
        "Cote d'Ivoire",
        "Croatia",
        "Cuba",
        "Curacao",
        "Cyprus",
        "Czechia",
        "Denmark",
        "Djibouti",
        "Dominica",
        "Dominican Republic",
        "Ecuador",
        "Egypt, Arab Rep.",
        "El Salvador",
        "Equatorial Guinea",
        "Eritrea",
        "Eswatini",
        "Estonia",
        "Ethiopia",
        "Fiji",
        "Finland",
        "France",
        "Gabon",
        "Gambia",
        "Gambia, The",
        "Georgia",
        "Germany",
        "Ghana",
        "Greece",
        "Grenada",
        "Guatemala",
        "Guinea",
        "Guinea-Bissau",
        "Guyana",
        "Haiti",
        "Honduras",
        "Hungary",
        "Iceland",
        "India",
        "Indonesia",
        "Iran, Islamic Rep.",
        "Iraq",
        "Ireland",
        "Israel",
        "Italy",
        "Jamaica",
        "Japan",
        "Jordan",
        "Kazakhstan",
        "Kenya",
        "Kiribati",
        "Korea, Dem. People's Rep.",
        "Korea, Rep.",
        "Kosovo",
        "Kuwait",
        "Kyrgyzstan",
        "Lao PDR",
        "Latvia",
        "Lebanon",
        "Lesotho",
        "Liberia",
        "Libya",
        "Liechtenstein",
        "Lithuania",
        "Luxembourg",
        "Madagascar",
        "Malawi",
        "Malaysia",
        "Maldives",
        "Mali",
        "Malta",
        "Marshall Islands",
        "Mauritania",
        "Mauritius",
        "Mexico",
        "Micronesia, Fed. Sts.",
        "Moldova",
        "Monaco",
        "Mongolia",
        "Montenegro",
        "Morocco",
        "Mozambique",
        "Myanmar",
        "Namibia",
        "Nauru",
        "Nepal",
        "Netherlands",
        "New Zealand",
        "Nicaragua",
        "Niger",
        "Nigeria",
        "North Macedonia",
        "Norway",
        "Oman",
        "Pakistan",
        "Palau",
        "Palestine",
        "Panama",
        "Papua New Guinea",
        "Paraguay",
        "Peru",
        "Philippines",
        "Poland",
        "Portugal",
        "Qatar",
        "Romania",
        "Russian Federation",
        "Rwanda",
        "Samoa",
        "San Marino",
        "Sao Tome and Principe",
        "Saudi Arabia",
        "Senegal",
        "Serbia",
        "Seychelles",
        "Sierra Leone",
        "Singapore",
        "Slovak Republic",
        "Slovenia",
        "Solomon Islands",
        "Somalia",
        "South Africa",
        "South Sudan",
        "Spain",
        "Sri Lanka",
        "St. Kitts and Nevis",
        "St. Lucia",
        "St. Vincent and the Grenadines",
        "Sudan",
        "Suriname",
        "Swaziland",
        "Sweden",
        "Switzerland",
        "Syrian Arab Republic",
        "Tajikistan",
        "Tanzania",
        "Thailand",
        "Timor-Leste",
        "Togo",
        "Tonga",
        "Trinidad and Tobago",
        "Tunisia",
        "Turkey",
        "Turkiye",
        "Turkmenistan",
        "Tuvalu",
        "Uganda",
        "Ukraine",
        "United Arab Emirates",
        "United Kingdom",
        "United States",
        "Uruguay",
        "Uzbekistan",
        "Vanuatu",
        "Venezuela, RB",
        "Viet Nam",
        "Virgin Islands (U.S.)",
        "West Bank and Gaza",
        "Yemen, Rep.",
        "Zambia",
        "Zimbabwe",
    ],
    key=lambda x: -len(x),  # longest first for greedy matching
)


def split_countries(concatenated: str) -> list:
    """Split a concatenated country string into individual countries.

    Uses greedy longest-match against KNOWN_COUNTRIES.
    Returns a list of country names found, or [concatenated] if
    no match is possible (i.e. the string is already clean or unknown).

    Values already containing "; " are considered pre-separated and
    returned as-is (single-element list) so they are not re-processed.
    """
    if not concatenated:
        return []

    # Already-separated values (from a previous fix run) should not be
    # re-parsed — they would fail the greedy matcher on the "; " prefix.
    if "; " in concatenated:
        return [concatenated]

    remaining = concatenated
    result = []
    while remaining:
        matched = False
        for country in KNOWN_COUNTRIES:
            if remaining.startswith(country):
                result.append(country)
                remaining = remaining[len(country) :]
                matched = True
                break
        if not matched:
            # Can't parse further — return original as-is
            logger.warning("Cannot split: %r (stuck at %r)", concatenated, remaining)
            return [concatenated]
    return result


def needs_splitting(value: str) -> bool:
    """Check if a country value is a concatenated multi-country string."""
    countries = split_countries(value)
    return len(countries) > 1


def fix_qdrant_collection(client, collection_name, dry_run):
    """Fix map_country in a Qdrant collection."""
    logger.info("Scanning Qdrant collection: %s", collection_name)

    # Collect all points with their country values
    fixes = {}  # point_id -> new_value
    offset = None
    scanned = 0
    while True:
        results = client.scroll(
            collection_name,
            limit=500,
            with_payload=["map_country"],
            offset=offset,
        )
        points, next_offset = results
        for point in points:
            country = point.payload.get("map_country", "")
            if country and needs_splitting(country):
                new_val = "; ".join(split_countries(country))
                fixes[point.id] = new_val
        scanned += len(points)
        if scanned % 10000 == 0:
            logger.info("  Scanned %d points, %d need fixing...", scanned, len(fixes))
        offset = next_offset
        if offset is None:
            break

    logger.info(
        "Collection %s: %d/%d points need fixing",
        collection_name,
        len(fixes),
        scanned,
    )

    if dry_run:
        for pid, new_val in list(fixes.items())[:10]:
            logger.info("  [DRY RUN] %s -> %s", pid, new_val)
        return len(fixes)

    # Apply fixes in batches
    point_ids = list(fixes.keys())
    batch_size = 50
    for i in range(0, len(point_ids), batch_size):
        batch = point_ids[i : i + batch_size]
        for pid in batch:
            for attempt in range(5):
                try:
                    client.set_payload(
                        collection_name,
                        payload={"map_country": fixes[pid]},
                        points=[pid],
                        wait=False,
                    )
                    break
                except Exception as e:
                    wait_time = 2**attempt
                    logger.warning(
                        "Retry %d for point %s: %s (wait %ds)",
                        attempt + 1,
                        pid,
                        e,
                        wait_time,
                    )
                    time.sleep(wait_time)
        done = min(i + batch_size, len(point_ids))
        if done % 500 == 0 or done == len(point_ids):
            logger.info("  Updated %d/%d points", done, len(point_ids))
        time.sleep(0.1)

    return len(fixes)


def fix_postgres_table(conn, table_name, dry_run):
    """Fix map_country in a PostgreSQL table."""
    logger.info("Scanning PostgreSQL table: %s", table_name)

    cursor = conn.cursor()

    # Check if column exists before querying
    cursor.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = 'map_country'",
        (table_name,),
    )
    if not cursor.fetchone():
        logger.info("Table %s has no map_country column, skipping", table_name)
        return 0

    # Find all distinct concatenated country values
    cursor.execute(
        f"SELECT DISTINCT map_country FROM {table_name} "
        f"WHERE map_country IS NOT NULL AND map_country != ''"
    )
    all_values = [row[0] for row in cursor.fetchall()]

    mapping = {}
    for val in all_values:
        countries = split_countries(val)
        if len(countries) > 1:
            mapping[val] = "; ".join(countries)

    logger.info(
        "Table %s: %d/%d distinct values need fixing",
        table_name,
        len(mapping),
        len(all_values),
    )

    if dry_run:
        for old, new in list(mapping.items())[:10]:
            logger.info("  [DRY RUN] %r -> %r", old, new)
        return len(mapping)

    # Apply fixes
    for old_val, new_val in mapping.items():
        cursor.execute(
            f"UPDATE {table_name} SET map_country = %s " f"WHERE map_country = %s",
            (new_val, old_val),
        )
        logger.info(
            "  Updated %d rows: %r -> %r",
            cursor.rowcount,
            old_val[:60],
            new_val[:60],
        )

    conn.commit()
    return len(mapping)


def main():
    parser = argparse.ArgumentParser(
        description="Fix concatenated country values in Qdrant and PostgreSQL"
    )
    parser.add_argument(
        "--data-source",
        default="uneg",
        help="Data source name (default: uneg)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be fixed without making changes",
    )
    parser.add_argument(
        "--collection",
        choices=["chunks", "docs", "all"],
        default="all",
        help="Which collection(s) to fix (default: all)",
    )
    parser.add_argument(
        "--skip-postgres",
        action="store_true",
        help="Skip PostgreSQL (useful when psycopg2 not available)",
    )
    args = parser.parse_args()

    # Load .env from repo root
    env_path = os.path.join(os.path.dirname(__file__), "../../.env")
    load_dotenv(env_path)

    ds = args.data_source
    qdrant_host = os.getenv("QDRANT_HOST", "http://localhost:6333")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    # Auto-convert Docker hostname to localhost for host execution
    qdrant_host = qdrant_host.replace("://qdrant:", "://localhost:")
    client = QdrantClient(url=qdrant_host, api_key=qdrant_api_key)

    # Qdrant
    chunks_collection = f"chunks_{ds}"
    docs_collection = f"documents_{ds}"

    if args.collection in ("chunks", "all"):
        fix_qdrant_collection(client, chunks_collection, args.dry_run)
    if args.collection in ("docs", "all"):
        fix_qdrant_collection(client, docs_collection, args.dry_run)

    # PostgreSQL
    if not args.skip_postgres:
        try:
            import psycopg2

            from pipeline.db.postgres_client_base import build_postgres_dsn

            dsn = build_postgres_dsn()
            conn = psycopg2.connect(dsn)
            docs_table = f"docs_{ds}"
            chunks_table = f"chunks_{ds}"
            if args.collection in ("docs", "all"):
                fix_postgres_table(conn, docs_table, args.dry_run)
            if args.collection in ("chunks", "all"):
                fix_postgres_table(conn, chunks_table, args.dry_run)
            conn.close()
        except ImportError:
            logger.info("psycopg2 not available, skipping PostgreSQL")

    logger.info("Done!")


if __name__ == "__main__":
    main()
