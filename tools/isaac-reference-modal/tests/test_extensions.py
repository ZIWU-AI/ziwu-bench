"""Exercise the source integrity boundary without network or Modal credentials."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("extensions", ROOT / "prepare_extensions.py")
extensions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extensions)


class ExtensionTests(unittest.TestCase):
    def test_manifest_identity(self):
        self.assertEqual(hashlib.sha256(extensions.MANIFEST.read_bytes()).hexdigest(), extensions.MANIFEST_SHA256)

    def test_extract_rejects_unregistered_files_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            archive = directory / "input.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("lib.so", b"engine")
            release = {"root": "extension", "bytes": archive.stat().st_size,
                       "sha256": extensions.digest(archive)}
            with self.assertRaises(ValueError):
                extensions.extract_verified(archive, directory / "cache", release, {})
            expected = {"extension/lib.so": hashlib.sha256(b"engine").hexdigest()}
            extensions.extract_verified(archive, directory / "cache", release, expected)
            self.assertEqual((directory / "cache/extension/lib.so").read_bytes(), b"engine")
            archive.write_bytes(b"corrupt")
            with self.assertRaises(ValueError):
                extensions.verify_archive(archive, release)

    def test_paths(self):
        for name in ("../escape", "/etc/passwd", "a/../../b", "a\\b"):
            self.assertFalse(extensions.safe_member(name))
        self.assertTrue(extensions.safe_member("lib/engine.so"))


if __name__ == "__main__":
    unittest.main()
