"""Import cautiously matched Open Food Facts image references into SQLite.

Remote use is deliberately limited to explicitly requested GTINs.  Bulk users must
provide a local Open Food Facts JSONL export; this module never crawls the API and
never downloads or caches image bytes.
"""
import argparse
import gzip
import json
import os
import re
import sqlite3
import time
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, unquote, urlsplit
from urllib.request import Request, urlopen

from db_lock import database_lock


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = ROOT / "data" / "prices.sqlite3"
MAX_REMOTE_LOOKUPS = 15
MIN_REMOTE_INTERVAL_SECONDS = 4.1
MAX_API_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_JSONL_LINE_BYTES = 8 * 1024 * 1024

OFF_API_ORIGIN = "https://world.openfoodfacts.org"
OFF_IMAGE_HOST = "images.openfoodfacts.org"
OFF_SOURCE_NAME = "Open Food Facts"
OFF_LICENSE_NAME = "CC BY-SA"
OFF_LICENSE_URL = (
    "https://openfoodfacts.github.io/documentation/docs/Product-Opener/api/"
    "tutorials/license-be-on-the-legal-side/"
)
OFF_FIELDS = (
    "code",
    "product_name",
    "product_name_he",
    "product_name_en",
    "brands",
    "brands_tags",
    "lang",
    "selected_images",
    "images",
    "last_image_t",
)

IMAGE_COLUMNS = (
    "barcode",
    "image_url",
    "source_name",
    "source_page_url",
    "license_name",
    "license_url",
    "attribution",
    "source_updated_at",
    "checked_at",
    "width",
    "height",
    "content_sha256",
    "match_method",
    "status",
)


def is_valid_gtin(code):
    """Return True only for an exact GTIN-8/12/13/14 with a valid checksum."""
    if not isinstance(code, str) or not re.fullmatch(r"(?:[0-9]{8}|[0-9]{12,14})", code):
        return False
    weighted_sum = 0
    for position, digit in enumerate(reversed(code[:-1]), start=1):
        weighted_sum += int(digit) * (3 if position % 2 else 1)
    check_digit = (10 - weighted_sum % 10) % 10
    return check_digit == int(code[-1])


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _image_timestamp(value):
    """Render OFF's image upload/update timestamp without implying freshness."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        if not re.fullmatch(r"[0-9]+", value):
            return None
        value = int(value)
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
    except (OverflowError, OSError, ValueError):
        return None


def _off_image_directory(code):
    normalized = code.zfill(13) if len(code) < 13 else code
    return "/images/products/{}/{}/{}/{}/".format(
        normalized[:3], normalized[3:6], normalized[6:9], normalized[9:]
    )


def is_approved_off_image_url(value, code):
    """Accept only the documented HTTPS OFF selected-front URL for this code."""
    if not isinstance(value, str) or len(value) > 2048 or re.search(r"[\x00-\x20\x7f]", value):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or parsed.hostname != OFF_IMAGE_HOST
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    if unquote(parsed.path) != parsed.path:
        return False
    prefix = _off_image_directory(code)
    if not parsed.path.startswith(prefix):
        return False
    filename = parsed.path[len(prefix) :]
    return bool(
        re.fullmatch(
            r"front(?:_[a-z]{2,3})?\.[0-9]+\.(?:100|200|400|full)\.jpg", filename
        )
    )


def select_front_image(product, preferred_languages=("he", "en")):
    """Choose a validated selected_images.front URL; never use legacy/raw fields."""
    if not isinstance(product, dict):
        return None
    code = product.get("code")
    if not is_valid_gtin(code):
        return None
    selected = product.get("selected_images")
    front = selected.get("front") if isinstance(selected, dict) else None
    if not isinstance(front, dict):
        return None

    language_order = []
    for language in preferred_languages:
        if isinstance(language, str) and re.fullmatch(r"[a-z]{2,3}", language):
            language_order.append(language)
    product_language = product.get("lang")
    if isinstance(product_language, str) and re.fullmatch(r"[a-z]{2,3}", product_language):
        language_order.append(product_language)
    sizes = ("display", "small", "thumb")
    variants_by_size = {
        size: front[size] for size in sizes if isinstance(front.get(size), dict)
    }
    fallback_languages = sorted(
        {
            language
            for variants in variants_by_size.values()
            for language in variants
            if isinstance(language, str) and re.fullmatch(r"[a-z]{2,3}", language)
        }
    )
    language_order.extend(fallback_languages)

    for language in dict.fromkeys(language_order):
        for size in sizes:
            variants = variants_by_size.get(size)
            if variants is None:
                continue
            candidate = variants.get(language)
            if is_approved_off_image_url(candidate, code):
                return {"url": candidate, "language": language, "size": size}
    return None


def _normalized_text(value):
    if not isinstance(value, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(character for character in decomposed if not unicodedata.combining(character))
    return " ".join(re.findall(r"[^\W_]+", without_marks, flags=re.UNICODE))


def _strong_text_match(left, right):
    left = _normalized_text(left)
    right = _normalized_text(right)
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) >= 6 and re.search(r"(?:^| )" + re.escape(shorter) + r"(?: |$)", longer):
        return True
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    common = left_tokens & right_tokens
    coverage = len(common) / min(len(left_tokens), len(right_tokens))
    if len(common) >= 2 and coverage >= 0.67:
        return True
    return SequenceMatcher(None, left, right).ratio() >= 0.86


def _source_names(product):
    names = []
    for key, value in product.items():
        if key == "product_name" or re.fullmatch(r"product_name_[a-z]{2,3}", str(key)):
            if isinstance(value, str) and _normalized_text(value):
                names.append(value)
    return list(dict.fromkeys(names))


def _source_brands(product):
    brands = []
    value = product.get("brands")
    if isinstance(value, str):
        brands.extend(piece.strip() for piece in value.split(",") if piece.strip())
    tags = product.get("brands_tags")
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, str):
                continue
            brands.append(tag.split(":", 1)[-1].replace("-", " "))
    return list(dict.fromkeys(brand for brand in brands if _normalized_text(brand)))


def assess_identity(product, local_identities):
    """Return a display status and auditable method for a conservative match."""
    source_names = _source_names(product)
    source_brands = _source_brands(product)
    name_match_without_brand = False

    for identity in local_identities:
        local_name = identity.get("name") if isinstance(identity, dict) else None
        if not any(_strong_text_match(local_name, source_name) for source_name in source_names):
            continue
        local_brand = identity.get("brand") if isinstance(identity, dict) else None
        if not _normalized_text(local_brand):
            return "verified", "exact-gtin+name"
        if any(_strong_text_match(local_brand, source_brand) for source_brand in source_brands):
            return "verified", "exact-gtin+name+brand"
        if any(_strong_text_match(local_brand, source_name) for source_name in source_names):
            return "verified", "exact-gtin+name+brand-in-name"
        name_match_without_brand = True

    if name_match_without_brand:
        return "candidate", "exact-gtin+name;brand-unconfirmed"
    return "candidate", "exact-gtin-only;identity-unconfirmed"


def _extract_product(payload):
    if not isinstance(payload, dict):
        return None
    if "product" in payload:
        return payload["product"] if isinstance(payload["product"], dict) else None
    return payload


def build_image_row(payload, expected_code, local_identities, checked_at=None):
    """Convert one raw/API OFF record to a schema row or a rejection reason."""
    if not is_valid_gtin(expected_code):
        return None, "invalid-gtin"
    product = _extract_product(payload)
    if not product:
        return None, "not-found"
    # OFF normalizes some barcodes.  This pipeline intentionally requires the
    # returned/exported code to be byte-for-byte identical to the local GTIN.
    if product.get("code") != expected_code:
        return None, "code-mismatch"
    selected = select_front_image(product)
    if selected is None:
        return None, "no-approved-selected-front"

    status, match_method = assess_identity(product, local_identities)
    source_page = f"{OFF_API_ORIGIN}/product/{expected_code}"
    row = {
        "barcode": expected_code,
        "image_url": selected["url"],
        "source_name": OFF_SOURCE_NAME,
        "source_page_url": source_page,
        "license_name": OFF_LICENSE_NAME,
        "license_url": OFF_LICENSE_URL,
        "attribution": f"Open Food Facts contributors — {source_page}",
        # last_image_t is only an OFF image upload/update time.  It is not
        # evidence that the pictured package is the current retail package.
        "source_updated_at": _image_timestamp(product.get("last_image_t")),
        "checked_at": checked_at or _utc_now(),
        "width": None,
        "height": None,
        # Image bytes are never fetched, so a content digest cannot be claimed.
        "content_sha256": None,
        "match_method": match_method,
        "status": status,
    }
    return row, None


def _validate_user_agent(user_agent):
    if not isinstance(user_agent, str) or not user_agent.strip():
        raise ValueError(
            "SALSAL_IMAGE_USER_AGENT is required for OFF API access "
            "(for example: Salsal/1.0 (contact@example.com))"
        )
    user_agent = user_agent.strip()
    if len(user_agent) > 256 or re.search(r"[\r\n\x00]", user_agent):
        raise ValueError("SALSAL_IMAGE_USER_AGENT contains unsafe characters")
    if not re.fullmatch(r"[^\s()/]+/[^\s()]+ \([^()\r\n]{3,}\)", user_agent):
        raise ValueError(
            "SALSAL_IMAGE_USER_AGENT must use AppName/Version (contact) format"
        )
    return user_agent


def _is_approved_api_url(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "world.openfoodfacts.org"
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and parsed.path.startswith("/api/v3/product/")
    )


def fetch_off_product(code, user_agent=None, opener=None, timeout=15):
    """Fetch one bounded v3 product JSON document; never fetch its image URL."""
    if not is_valid_gtin(code):
        raise ValueError(f"not an exact valid GTIN: {code!r}")
    user_agent = _validate_user_agent(
        user_agent if user_agent is not None else os.environ.get("SALSAL_IMAGE_USER_AGENT")
    )
    query = urlencode(
        {"product_type": "food", "cc": "il", "lc": "he", "fields": ",".join(OFF_FIELDS)}
    )
    url = f"{OFF_API_ORIGIN}/api/v3/product/{code}?{query}"
    if not _is_approved_api_url(url):
        raise ValueError("refusing an unapproved OFF API URL")
    request = Request(url, headers={"Accept": "application/json", "User-Agent": user_agent})
    open_request = opener or urlopen
    try:
        response = open_request(request, timeout=timeout)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise
    with response:
        final_url = response.geturl() if hasattr(response, "geturl") else url
        if not _is_approved_api_url(final_url):
            raise ValueError("OFF API redirected to an unapproved host or path")
        headers = getattr(response, "headers", None)
        content_type = headers.get("Content-Type") if headers is not None else None
        if content_type:
            media_type = content_type.split(";", 1)[0].strip().lower()
            if media_type != "application/json" and not media_type.endswith("+json"):
                raise ValueError("OFF API response is not JSON")
        raw = response.read(MAX_API_RESPONSE_BYTES + 1)
    if len(raw) > MAX_API_RESPONSE_BYTES:
        raise ValueError("OFF API response exceeds the configured bound")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("OFF API returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("OFF API response must be a JSON object")
    product = _extract_product(payload)
    if product is not None and product.get("code") != code:
        raise ValueError("OFF response did not confirm the exact requested GTIN")
    return payload


def _load_local_identities(connection):
    identities = {}
    for barcode, name, brand in connection.execute(
        "SELECT barcode,name,brand FROM products "
        "WHERE id=barcode AND weighted=0 ORDER BY barcode,id"
    ):
        identities.setdefault(barcode, []).append({"name": name, "brand": brand})
    return identities


def _validate_database_schema(connection):
    tables = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if not {"products", "product_images"}.issubset(tables):
        raise ValueError("database is missing products or product_images")
    product_columns = {row[1] for row in connection.execute("PRAGMA table_info(products)")}
    missing_products = {"id", "barcode", "name", "brand", "weighted"} - product_columns
    if missing_products:
        raise ValueError(
            "products is missing columns: " + ", ".join(sorted(missing_products))
        )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(product_images)")}
    missing = set(IMAGE_COLUMNS) - columns
    if missing:
        raise ValueError("product_images is missing columns: " + ", ".join(sorted(missing)))


UPSERT_IMAGE = """
INSERT INTO product_images (
 barcode,image_url,source_name,source_page_url,license_name,license_url,attribution,
 source_updated_at,checked_at,width,height,content_sha256,match_method,status
) VALUES (
 :barcode,:image_url,:source_name,:source_page_url,:license_name,:license_url,:attribution,
 :source_updated_at,:checked_at,:width,:height,:content_sha256,:match_method,:status
)
ON CONFLICT(barcode) DO UPDATE SET
 image_url=excluded.image_url,
 source_name=excluded.source_name,
 source_page_url=excluded.source_page_url,
 license_name=excluded.license_name,
 license_url=excluded.license_url,
 attribution=excluded.attribution,
 source_updated_at=excluded.source_updated_at,
 checked_at=excluded.checked_at,
 width=excluded.width,
 height=excluded.height,
 content_sha256=excluded.content_sha256,
 match_method=excluded.match_method,
 status=excluded.status
"""


def ingest_off_records(database, records, checked_at=None):
    """Validate and transactionally upsert an iterable of (expected_code, JSON)."""
    database = Path(database)
    if not database.is_file():
        raise FileNotFoundError(database)
    stats = {
        "seen": 0,
        "written": 0,
        "verified": 0,
        "candidate": 0,
        "not_local": 0,
        "invalid_gtin": 0,
        "not_found": 0,
        "code_mismatch": 0,
        "no_approved_selected_front": 0,
        "preserved": 0,
        "refreshed": 0,
        "revision_pending": 0,
    }
    with database_lock(database.parent):
        connection = sqlite3.connect(database)
        try:
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("BEGIN IMMEDIATE")
            _validate_database_schema(connection)
            identities = _load_local_identities(connection)
            for expected_code, payload in records:
                stats["seen"] += 1
                if not is_valid_gtin(expected_code):
                    stats["invalid_gtin"] += 1
                    continue
                local_identities = identities.get(expected_code)
                if not local_identities:
                    stats["not_local"] += 1
                    continue
                row, reason = build_image_row(
                    payload, expected_code, local_identities, checked_at=checked_at
                )
                if row is None:
                    stats[reason.replace("-", "_")] += 1
                    continue
                existing = connection.execute(
                    "SELECT image_url,source_name,status FROM product_images WHERE barcode=?",
                    (expected_code,),
                ).fetchone()
                if existing and existing[2] in ("verified", "accepted"):
                    same_verified_off_reference = (
                        existing[2] == "verified"
                        and row["status"] == "verified"
                        and existing[1] == OFF_SOURCE_NAME
                        and existing[0] == row["image_url"]
                    )
                    if same_verified_off_reference:
                        connection.execute(
                            "UPDATE product_images SET checked_at=? WHERE barcode=?",
                            (row["checked_at"], expected_code),
                        )
                        stats["written"] += 1
                        stats["refreshed"] += 1
                    else:
                        if (
                            existing[2] == "verified"
                            and row["status"] == "verified"
                            and existing[1] == OFF_SOURCE_NAME
                            and existing[0] != row["image_url"]
                        ):
                            # The one-row schema has nowhere to retain both revisions.
                            # Report the change for manual review and keep the displayed
                            # verified reference unchanged.
                            stats["revision_pending"] += 1
                        stats["preserved"] += 1
                    continue
                cursor = connection.execute(UPSERT_IMAGE, row)
                if cursor.rowcount:
                    stats["written"] += 1
                    stats[row["status"]] += 1
                else:
                    stats["preserved"] += 1
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
    return stats


def _known_local_codes(database, codes):
    database = Path(database)
    if not database.exists():
        raise FileNotFoundError(database)
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        _validate_database_schema(connection)
        placeholders = ",".join("?" for _ in codes)
        if not placeholders:
            return set()
        return {
            row[0]
            for row in connection.execute(
                f"SELECT DISTINCT barcode FROM products "
                f"WHERE id=barcode AND weighted=0 AND barcode IN ({placeholders})",
                codes,
            )
        }


def sync_remote(
    database,
    codes,
    user_agent=None,
    opener=None,
    checked_at=None,
    sleeper=None,
    monotonic=None,
):
    """Look up at most MAX_REMOTE_LOOKUPS explicitly supplied local GTINs."""
    codes = list(codes)
    if not codes:
        raise ValueError("at least one GTIN is required")
    if len(codes) > MAX_REMOTE_LOOKUPS:
        raise ValueError(f"remote OFF lookup is limited to {MAX_REMOTE_LOOKUPS} GTINs per run")
    for code in codes:
        if not is_valid_gtin(code):
            raise ValueError(f"not an exact valid GTIN: {code!r}")
    if len(set(codes)) != len(codes):
        raise ValueError("duplicate GTINs are not allowed")
    user_agent = _validate_user_agent(
        user_agent if user_agent is not None else os.environ.get("SALSAL_IMAGE_USER_AGENT")
    )
    known = _known_local_codes(database, codes)
    records = []
    fetched = 0
    sleeper = sleeper or time.sleep
    monotonic = monotonic or time.monotonic
    previous_request_started = None
    for code in codes:
        if code not in known:
            records.append((code, None))
            continue
        now = monotonic()
        if previous_request_started is not None:
            remaining = MIN_REMOTE_INTERVAL_SECONDS - (now - previous_request_started)
            if remaining > 0:
                sleeper(remaining)
                now = monotonic()
        previous_request_started = now
        payload = fetch_off_product(code, user_agent=user_agent, opener=opener)
        fetched += 1
        records.append((code, payload))
    stats = ingest_off_records(database, records, checked_at=checked_at)
    stats["requested"] = len(codes)
    stats["fetched"] = fetched
    return stats


def iter_off_jsonl(path):
    """Yield raw OFF products from a local .jsonl or .jsonl.gz file."""
    path = Path(path)
    open_file = gzip.open if path.suffix == ".gz" else open
    with open_file(path, "rb") as handle:
        line_number = 0
        while True:
            raw = handle.readline(MAX_JSONL_LINE_BYTES + 1)
            if not raw:
                break
            line_number += 1
            if len(raw) > MAX_JSONL_LINE_BYTES:
                raise ValueError(f"OFF JSONL line {line_number} exceeds the configured bound")
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(f"invalid OFF JSONL at line {line_number}") from error
            product = _extract_product(payload)
            code = product.get("code") if isinstance(product, dict) else None
            yield code, payload


def sync_jsonl(database, jsonl_path, checked_at=None):
    """Stream a local OFF JSONL export through the same transactional policy."""
    return ingest_off_records(
        database, iter_off_jsonl(jsonl_path), checked_at=checked_at
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Import licensed OFF selected-front image references without downloading images."
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--barcode",
        action="append",
        metavar="GTIN",
        help=f"exact local GTIN to query (repeatable; maximum {MAX_REMOTE_LOOKUPS})",
    )
    source.add_argument(
        "--off-jsonl",
        type=Path,
        metavar="PATH",
        help="local Open Food Facts JSONL or JSONL.GZ export (no network)",
    )
    arguments = parser.parse_args(argv)
    try:
        if arguments.barcode:
            stats = sync_remote(arguments.database, arguments.barcode)
        else:
            stats = sync_jsonl(arguments.database, arguments.off_jsonl)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
