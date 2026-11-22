import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import updater


class StartupUpdate(unittest.TestCase):
    def test_failed_candidate_uses_last_working_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "1.0.23"
            previous.mkdir()
            (previous / updater.APP_EXE).touch()
            (root / "current").write_text("1.0.23", encoding="ascii")
            candidate = root / "1.0.24"
            with patch.object(updater, "stage_release", return_value=candidate), patch.object(
                updater, "start_and_wait", side_effect=[False, True]
            ) as start:
                self.assertTrue(updater.select_version(root, "1.0.22", []))
            self.assertEqual([call.args[0] for call in start.call_args_list], [candidate, previous])
            self.assertEqual((root / "current").read_text(encoding="ascii"), "1.0.23")

    def test_network_failure_runs_installed_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(updater, "stage_release", side_effect=TimeoutError):
                self.assertFalse(updater.select_version(root, "1.0.22", []))

    def test_only_a_newer_release_with_verifiable_asset_is_eligible(self):
        asset = {"name": updater.UPDATE_ASSET, "size": 100, "digest": "sha256:" + "a" * 64,
                 "browser_download_url": updater.RELEASE_DOWNLOAD + "v1.0.24/" + updater.UPDATE_ASSET}
        release = {"tag_name": "v1.0.24", "assets": [asset]}
        self.assertEqual(updater.select_asset(release, "1.0.23"), ("1.0.24", asset))
        self.assertIsNone(updater.select_asset(release, "1.0.24"))
        asset["digest"] = None
        self.assertIsNone(updater.select_asset(release, "1.0.23"))

    def test_verified_archive_is_staged_and_selected_after_start(self):
        archive = io.BytesIO()
        with ZipFile(archive, "w") as package:
            package.writestr(updater.APP_EXE, b"executable")
            package.writestr("_internal/runtime", b"runtime")
        contents = archive.getvalue()
        metadata = {
            "tag_name": "v1.0.23",
            "assets": [{
                "name": updater.UPDATE_ASSET,
                "size": len(contents),
                "digest": "sha256:" + hashlib.sha256(contents).hexdigest(),
                "browser_download_url": updater.RELEASE_DOWNLOAD + "v1.0.23/" + updater.UPDATE_ASSET,
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(updater, "fetch", side_effect=[
                io.BytesIO(json.dumps(metadata).encode()), io.BytesIO(b"x" * len(contents)),
            ]), patch.object(updater, "start_and_wait") as start:
                self.assertFalse(updater.select_version(root, "1.0.22", []))
                start.assert_not_called()
                self.assertFalse((root / "1.0.23").exists())
            with patch.object(updater, "fetch", side_effect=[
                io.BytesIO(json.dumps(metadata).encode()), io.BytesIO(contents),
            ]), patch.object(updater, "start_and_wait", return_value=True) as start:
                self.assertTrue(updater.select_version(root, "1.0.22", ["--no-open"]))
            start.assert_called_once_with(root / "1.0.23", ["--no-open"])
            self.assertEqual((root / "current").read_text(encoding="ascii"), "1.0.23")
            self.assertEqual((root / "1.0.23" / updater.APP_EXE).read_bytes(), b"executable")


if __name__ == "__main__":
    unittest.main()
