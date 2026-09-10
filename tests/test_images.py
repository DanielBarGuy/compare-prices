import gzip
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sync_images


CODE = "7290004131074"
SECOND_CODE = "3017620422003"
IMAGE = (
    "https://images.openfoodfacts.org/images/products/729/000/413/1074/"
    "front_he.7.400.jpg"
)
SECOND_IMAGE = (
    "https://images.openfoodfacts.org/images/products/301/762/042/2003/"
    "front_en.4.400.jpg"
)


def off_payload(
    *,
    code=CODE,
    name="חלב תנובה 3 אחוז",
    brand="תנובה",
    image=IMAGE,
    last_image_t=1_700_000_000,
):
    product = {
        "code": code,
        "product_name_he": name,
        "brands": brand,
        "selected_images": {"front": {"display": {"he": image}}},
        "last_image_t": last_image_t,
    }
    return {"status": "success", "product": product}


class FakeResponse:
    def __init__(self, payload, url, content_type="application/json; charset=utf-8"):
        self.body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.url = url
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self):
        return self.url

    def read(self, amount=-1):
        return self.body if amount < 0 else self.body[:amount]


class FakeOpener:
    def __init__(self, payload, final_url=None, content_type="application/json; charset=utf-8"):
        self.payload = payload
        self.final_url = final_url
        self.content_type = content_type
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append((request, timeout))
        return FakeResponse(
            self.payload, self.final_url or request.full_url, self.content_type
        )


class SequenceOpener:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append((request, timeout))
        return FakeResponse(next(self.payloads), request.full_url)


def create_database(path, name="חלב תנובה 3 אחוז", brand="תנובה"):
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as database:
        database.executescript(
            """
            CREATE TABLE products (
              id TEXT PRIMARY KEY,
              barcode TEXT NOT NULL,
              name TEXT NOT NULL,
              brand TEXT,
              weighted INTEGER NOT NULL
            );
            CREATE TABLE product_images (
              barcode TEXT PRIMARY KEY,
              image_url TEXT,
              source_name TEXT NOT NULL,
              source_page_url TEXT,
              license_name TEXT,
              license_url TEXT,
              attribution TEXT,
              source_updated_at TEXT,
              checked_at TEXT NOT NULL,
              width INTEGER,
              height INTEGER,
              content_sha256 TEXT,
              match_method TEXT NOT NULL,
              status TEXT NOT NULL
            );
            """
        )
        database.execute(
            "INSERT INTO products(id,barcode,name,brand,weighted) VALUES (?,?,?,?,?)",
            (CODE, CODE, name, brand, 0),
        )


class ImageValidationTest(unittest.TestCase):
    def test_gtin_requires_exact_ascii_length_and_checksum(self):
        for valid in ("96385074", "036000291452", CODE, "10012345000017"):
            self.assertTrue(sync_images.is_valid_gtin(valid), valid)
        for invalid in (
            "96385075",
            "036000291453",
            CODE[:-1] + "5",
            " 7290004131074",
            "7290004131074\n",
            "٧٢٩٠٠٠٤١٣١٠٧٤",
            7290004131074,
        ):
            self.assertFalse(sync_images.is_valid_gtin(invalid), invalid)

    def test_selected_front_is_type_checked_and_bound_to_off_product_path(self):
        product = off_payload()["product"]
        selected = sync_images.select_front_image(product)
        self.assertEqual(selected["url"], IMAGE)
        self.assertEqual(selected["language"], "he")

        unsafe_urls = (
            IMAGE.replace("https://", "http://"),
            IMAGE.replace("images.openfoodfacts.org", "images.example"),
            IMAGE.replace("729/000/413/1074", "301/762/042/2003"),
            IMAGE + "?tracking=1",
        )
        for unsafe in unsafe_urls:
            changed = dict(product)
            changed["selected_images"] = {
                "front": {"display": {1: IMAGE, "he": unsafe}}
            }
            self.assertIsNone(sync_images.select_front_image(changed), unsafe)

        changed = dict(product)
        changed["selected_images"] = {"front": [IMAGE]}
        self.assertIsNone(sync_images.select_front_image(changed))

    def test_language_preference_is_applied_before_image_size(self):
        product = off_payload()["product"]
        product["lang"] = "fr"
        product["selected_images"] = {
            "front": {
                "display": {
                    "fr": IMAGE.replace("front_he", "front_fr"),
                    "en": IMAGE.replace("front_he", "front_en"),
                },
                "small": {"he": IMAGE.replace(".400.jpg", ".200.jpg")},
            }
        }
        selected = sync_images.select_front_image(product)
        self.assertEqual(selected["language"], "he")
        self.assertEqual(selected["size"], "small")

    def test_identity_evidence_controls_candidate_vs_verified(self):
        local = [{"name": "חלב תנובה 3 אחוז", "brand": "תנובה"}]
        row, reason = sync_images.build_image_row(
            off_payload(), CODE, local, checked_at="2026-09-10T20:00:00Z"
        )
        self.assertIsNone(reason)
        self.assertEqual(row["status"], "verified")
        self.assertEqual(row["match_method"], "exact-gtin+name+brand")
        self.assertEqual(row["source_name"], "Open Food Facts")
        self.assertEqual(row["license_name"], "CC BY-SA")
        self.assertEqual(row["license_url"], sync_images.OFF_LICENSE_URL)
        self.assertIn(row["source_page_url"], row["attribution"])
        self.assertEqual(row["source_updated_at"], "2023-11-14T22:13:20Z")
        self.assertIsNone(row["content_sha256"])

        candidate, reason = sync_images.build_image_row(
            off_payload(name="משקה אחר", brand="מותג אחר"),
            CODE,
            local,
            checked_at="2026-09-10T20:00:00Z",
        )
        self.assertIsNone(reason)
        self.assertEqual(candidate["status"], "candidate")
        self.assertNotIn("current", candidate["match_method"])

    def test_response_code_must_exactly_confirm_requested_gtin(self):
        row, reason = sync_images.build_image_row(
            off_payload(code="3017620422003"),
            CODE,
            [{"name": "חלב תנובה 3 אחוז", "brand": "תנובה"}],
        )
        self.assertIsNone(row)
        self.assertEqual(reason, "code-mismatch")


class RemoteLookupTest(unittest.TestCase):
    def test_remote_lookup_requires_explicit_user_agent(self):
        opener = FakeOpener(off_payload())
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "SALSAL_IMAGE_USER_AGENT"):
                sync_images.fetch_off_product(CODE, opener=opener)
        self.assertEqual(opener.calls, [])

        with self.assertRaisesRegex(ValueError, "AppName/Version"):
            sync_images.fetch_off_product(CODE, user_agent="generic-client", opener=opener)
        self.assertEqual(opener.calls, [])

    def test_remote_lookup_is_one_bounded_v3_json_request_only(self):
        opener = FakeOpener(off_payload())
        result = sync_images.fetch_off_product(
            CODE, user_agent="Salsal/1.0 (images@example.com)", opener=opener
        )
        self.assertEqual(result["product"]["code"], CODE)
        self.assertEqual(len(opener.calls), 1)
        request, timeout = opener.calls[0]
        self.assertEqual(timeout, 15)
        self.assertTrue(
            request.full_url.startswith(
                f"https://world.openfoodfacts.org/api/v3/product/{CODE}?"
            )
        )
        self.assertIn("selected_images", request.full_url)
        self.assertEqual(
            dict(request.header_items())["User-agent"],
            "Salsal/1.0 (images@example.com)",
        )
        self.assertNotIn("images.openfoodfacts.org", request.full_url)

    def test_redirect_and_exact_code_are_rejected(self):
        redirected = FakeOpener(
            off_payload(),
            final_url=f"https://evil.example/api/v3/product/{CODE}",
        )
        with self.assertRaisesRegex(ValueError, "unapproved"):
            sync_images.fetch_off_product(
                CODE, user_agent="Salsal/1.0 (images@example.com)", opener=redirected
            )

        mismatch = FakeOpener(off_payload(code="3017620422003"))
        with self.assertRaisesRegex(ValueError, "exact requested GTIN"):
            sync_images.fetch_off_product(
                CODE, user_agent="Salsal/1.0 (images@example.com)", opener=mismatch
            )

        wrong_media_type = FakeOpener(off_payload(), content_type="text/html")
        with self.assertRaisesRegex(ValueError, "not JSON"):
            sync_images.fetch_off_product(
                CODE,
                user_agent="Salsal/1.0 (images@example.com)",
                opener=wrong_media_type,
            )

    def test_remote_batch_has_a_hard_limit_before_network(self):
        opener = FakeOpener(off_payload())
        with self.assertRaisesRegex(ValueError, "limited"):
            sync_images.sync_remote(
                Path("unused.sqlite3"),
                [CODE] * (sync_images.MAX_REMOTE_LOOKUPS + 1),
                user_agent="Salsal/1.0 (images@example.com)",
                opener=opener,
            )
        self.assertEqual(opener.calls, [])

    def test_remote_batch_is_paced_without_sleeping_in_the_test(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "data" / "prices.sqlite3"
            create_database(database_path)
            with sqlite3.connect(database_path) as database:
                database.execute(
                    "INSERT INTO products(id,barcode,name,brand,weighted) VALUES (?,?,?,?,?)",
                    (SECOND_CODE, SECOND_CODE, "Nutella", "Ferrero", 0),
                )
            opener = SequenceOpener(
                [
                    off_payload(),
                    off_payload(
                        code=SECOND_CODE,
                        name="Nutella",
                        brand="Ferrero",
                        image=SECOND_IMAGE,
                    ),
                ]
            )
            now = [100.0]
            sleeps = []

            def monotonic():
                return now[0]

            def sleeper(seconds):
                sleeps.append(seconds)
                now[0] += seconds

            stats = sync_images.sync_remote(
                database_path,
                [CODE, SECOND_CODE],
                user_agent="Salsal/1.0 (images@example.com)",
                opener=opener,
                sleeper=sleeper,
                monotonic=monotonic,
            )
            self.assertEqual(stats["fetched"], 2)
            self.assertEqual(len(opener.calls), 2)
            self.assertEqual(len(sleeps), 1)
            self.assertGreaterEqual(sleeps[0], 4.1)

    def test_remote_lookup_excludes_weighted_and_retailer_internal_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "data" / "prices.sqlite3"
            create_database(database_path)
            with sqlite3.connect(database_path) as database:
                database.execute("UPDATE products SET weighted=1 WHERE barcode=?", (CODE,))
                database.execute(
                    "INSERT INTO products(id,barcode,name,brand,weighted) VALUES (?,?,?,?,?)",
                    ("7290000000000:" + SECOND_CODE, SECOND_CODE, "Nutella", "Ferrero", 0),
                )
            opener = FakeOpener(off_payload())
            stats = sync_images.sync_remote(
                database_path,
                [CODE, SECOND_CODE],
                user_agent="Salsal/1.0 (images@example.com)",
                opener=opener,
            )
            self.assertEqual(stats["fetched"], 0)
            self.assertEqual(stats["not_local"], 2)
            self.assertEqual(opener.calls, [])


class ImageDatabaseTest(unittest.TestCase):
    def test_verified_and_candidate_rows_are_transactional_and_locked(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "data" / "prices.sqlite3"
            create_database(database_path)
            stats = sync_images.ingest_off_records(
                database_path,
                [(CODE, off_payload())],
                checked_at="2026-09-10T20:00:00Z",
            )
            self.assertEqual(stats["verified"], 1)
            self.assertTrue((database_path.parent / ".database.lock").exists())
            with sqlite3.connect(database_path) as database:
                row = database.execute(
                    "SELECT image_url,status,content_sha256,license_name FROM product_images"
                ).fetchone()
            self.assertEqual(row, (IMAGE, "verified", None, "CC BY-SA"))

    def test_candidate_cannot_downgrade_an_existing_verified_image(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "data" / "prices.sqlite3"
            create_database(database_path)
            sync_images.ingest_off_records(database_path, [(CODE, off_payload())])
            candidate_payload = off_payload(name="מוצר לא קשור", brand="מותג אחר")
            stats = sync_images.ingest_off_records(
                database_path, [(CODE, candidate_payload)]
            )
            self.assertEqual(stats["preserved"], 1)
            with sqlite3.connect(database_path) as database:
                status, match_method = database.execute(
                    "SELECT status,match_method FROM product_images WHERE barcode=?", (CODE,)
                ).fetchone()
            self.assertEqual(status, "verified")
            self.assertEqual(match_method, "exact-gtin+name+brand")

    def test_changed_verified_revision_is_left_pending_for_manual_review(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "data" / "prices.sqlite3"
            create_database(database_path)
            first_checked = "2026-09-10T20:00:00Z"
            sync_images.ingest_off_records(
                database_path, [(CODE, off_payload())], checked_at=first_checked
            )
            revised = off_payload(
                image=IMAGE.replace(".7.400.jpg", ".8.400.jpg"),
                last_image_t=1_800_000_000,
            )
            stats = sync_images.ingest_off_records(
                database_path,
                [(CODE, revised)],
                checked_at="2026-09-10T21:00:00Z",
            )
            self.assertEqual(stats["revision_pending"], 1)
            self.assertEqual(stats["preserved"], 1)
            with sqlite3.connect(database_path) as database:
                image_url, checked_at = database.execute(
                    "SELECT image_url,checked_at FROM product_images WHERE barcode=?", (CODE,)
                ).fetchone()
            self.assertEqual(image_url, IMAGE)
            self.assertEqual(checked_at, first_checked)

    def test_local_jsonl_bulk_path_uses_same_policy_and_rolls_back_on_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "data" / "prices.sqlite3"
            create_database(database_path)
            source = root / "off-products.jsonl.gz"
            with gzip.open(source, "wb") as handle:
                handle.write(json.dumps(off_payload()["product"], ensure_ascii=False).encode())
                handle.write(b"\n{not valid json}\n")

            with self.assertRaisesRegex(ValueError, "line 2"):
                sync_images.sync_jsonl(database_path, source)
            with sqlite3.connect(database_path) as database:
                self.assertEqual(
                    database.execute("SELECT count(*) FROM product_images").fetchone()[0], 0
                )

    def test_local_jsonl_import_never_needs_a_user_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "data" / "prices.sqlite3"
            create_database(database_path)
            source = root / "off-products.jsonl"
            source.write_text(
                json.dumps(off_payload()["product"], ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                stats = sync_images.sync_jsonl(
                    database_path, source, checked_at="2026-09-10T20:00:00Z"
                )
            self.assertEqual(stats["written"], 1)


if __name__ == "__main__":
    unittest.main()
