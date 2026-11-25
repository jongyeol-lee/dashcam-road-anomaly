import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import publish_dashcam_gt as release


class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_modified_approval_cannot_start_publication(self):
        approval = self.root / release.APPROVAL
        approval.parent.mkdir(parents=True)
        approval.write_bytes(b"{}")
        with patch.object(release, "PROJECT", self.root), self.assertRaisesRegex(ValueError, "SHA-256"):
            release.approved_snapshot()

    def test_interrupted_publication_and_retry_preserve_existing_release(self):
        target = self.root / "release"
        snapshot = {"images": []}
        with patch.object(release, "RELEASE", target), patch.object(release, "approved_snapshot", return_value=snapshot):
            with patch.object(release, "verify", side_effect=ValueError("invalid")), self.assertRaises(ValueError):
                release.publish()
            self.assertEqual(list(self.root.iterdir()), [])
            release.publish()
            manifest = target / "release_manifest.json"
            before = manifest.read_bytes()
            with self.assertRaises(FileExistsError):
                release.publish()
            self.assertEqual(manifest.read_bytes(), before)

    def test_verification_rejects_extra_files_and_altered_hold_list(self):
        documents = {"release_manifest.json": {"images": []}, "uncertain_regions.json": [{"stored_class": "D40"}]}
        for name, data in documents.items():
            (self.root / name).write_text(json.dumps(data), encoding="utf-8")
        extra = self.root / "unapproved.txt"
        extra.touch()
        with self.assertRaisesRegex(ValueError, "목록"):
            release.verify(self.root, documents)
        extra.unlink()
        (self.root / "uncertain_regions.json").write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "승인 내용"):
            release.verify(self.root, documents)
