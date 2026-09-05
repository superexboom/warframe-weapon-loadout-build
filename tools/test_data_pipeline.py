from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import data_pipeline as pipeline
from data_sources import dataset_root, load_source_lock, validate_build
from generate_game_data import _rabbit_rows


class PipelineTest(unittest.TestCase):
    def test_snapshot_cache_identity(self):
        import app
        with patch.dict(app.SOURCE_LOCK, {"snapshotId": "first"}):
            first = app._analysis_inputs_fingerprint()
        with patch.dict(app.SOURCE_LOCK, {"snapshotId": "second"}):
            second = app._analysis_inputs_fingerprint()
        self.assertTrue(first)
        self.assertNotEqual(first, second)

    def test_invalid_input_contract(self):
        for value in ("../other", "a/b", "C:\\data", "", "a..b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_build(value)
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "inputs.json"
            pipeline.write_json(config, {"schemaVersion": 1, "build": "test", "inputs": {}})
            with self.assertRaisesRegex(ValueError, "missing"):
                pipeline.load_config(config)
            records = [{"UniqueName": "/Lotus/Test", "NameEn": "Test", "nested": {"NameEn": "Child"}}]
            for indent in (None, 2, "\t"):
                config.write_text(json.dumps(records, indent=indent), encoding="utf-8-sig")
                self.assertEqual(_rabbit_rows(config), records)

    def test_snapshot_activation_failure_and_rollback(self):
        temp_root = pipeline.ROOT / ".local" / "pipeline-tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as directory:
            root = Path(directory) / "runtime"
            candidate = Path(directory) / "candidate"
            pipeline.copy_runtime(pipeline.ROOT, root)
            pipeline.copy_runtime(pipeline.ROOT, candidate)
            (candidate / "frontend/assets/pipeline-probe.txt").write_text("snapshot asset", encoding="utf-8")
            for name in ("app.py", "data_sources.py"):
                shutil.copy2(pipeline.ROOT / name, root / name)
            shutil.copytree(pipeline.ROOT / "vendor", root / "vendor", ignore=shutil.ignore_patterns("__pycache__"))
            candidate_lock = load_source_lock(candidate)
            candidate_lock["snapshotId"] = "test-snapshot"
            pipeline.write_json(candidate / "data/source-lock.json", candidate_lock)
            pipeline.write_json(candidate / "snapshot.json", {
                "schemaVersion": 1, "status": "ready", "build": candidate_lock["activeBuild"],
                "files": pipeline.payload_hashes(candidate),
            })
            lock_path = root / "data/source-lock.json"
            original = lock_path.read_bytes()
            # A failed final replace must leave the old snapshot selected.
            replace = pipeline.os.replace

            def fail_pointer(source, destination):
                if Path(destination) == lock_path:
                    raise OSError("injected pointer write failure")
                return replace(source, destination)

            with patch.object(pipeline.os, "replace", side_effect=fail_pointer):
                with self.assertRaisesRegex(OSError, "injected"):
                    pipeline.activate(root, candidate)
            self.assertEqual(lock_path.read_bytes(), original)
            backup = pipeline.activate(root, candidate)
            selected = dataset_root(root)
            self.assertNotEqual(selected, root)
            self.assertEqual(load_source_lock(root)["activeBuild"], candidate_lock["activeBuild"])
            probe = (
                "import sys,threading; from pathlib import Path; from urllib.request import urlopen; "
                "sys.path.insert(0,sys.argv[1]); import app; assert app.DATASET_ROOT==Path(sys.argv[2]); "
                "assert app.WARFRAME_DATA_PATH.is_relative_to(app.DATASET_ROOT); "
                "server=app.create_server('127.0.0.1',0); thread=threading.Thread(target=server.serve_forever,daemon=True); "
                "thread.start(); data=urlopen(f'http://127.0.0.1:{server.server_port}/assets/pipeline-probe.txt',timeout=5).read(); "
                "server.shutdown(); server.server_close(); assert data==b'snapshot asset'"
            )
            subprocess.run([sys.executable, "-I", "-c", probe, str(root), str(selected)], check=True, timeout=20)
            bundle = Path(directory) / "bundle"
            pipeline.copy_runtime(root, bundle)
            self.assertNotIn("snapshotRoot", load_source_lock(bundle))
            self.assertFalse((bundle / "data/snapshots").exists())
            self.assertEqual(pipeline.payload_hashes(bundle), pipeline.payload_hashes(candidate))
            pipeline.rollback(root, backup)
            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8")), json.loads(original))
            self.assertTrue(selected.is_dir())
            (candidate / "frontend/assets/tampered.txt").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed after validation"):
                pipeline.activate(root, candidate)
            self.assertEqual(lock_path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
