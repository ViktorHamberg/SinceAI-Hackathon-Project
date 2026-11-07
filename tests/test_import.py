"""Verify the installed package imports in isolation without challenge data."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


class ImportTests(unittest.TestCase):
    def test_installed_import_from_empty_unrelated_directory_has_no_work(self):
        script = textwrap.dedent('''
            import os
            import sys

            def audit(event, args):
                if event == "open":
                    path, mode, flags = args
                    if isinstance(path, (str, bytes)):
                        path = os.fsdecode(path)
                        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                            raise AssertionError("import attempted file writes")
                        if not path.endswith((".py", ".pyc")):
                            raise AssertionError("import attempted non-code file access: " + path)
                if event in {"subprocess.Popen", "os.system", "socket.connect", "os.mkdir"}:
                    raise AssertionError("import attempted external work: " + event)

            sys.addaudithook(audit)
            import forecast_engine
            import forecast_engine.data
            import forecast_engine.availability
            import forecast_engine.provenance
            import forecast_engine.models
            import forecast_engine.models.persistence
            import forecast_engine.engine
            import forecast_engine.submission
            assert "pandas" not in sys.modules
            assert "numpy" not in sys.modules
            assert len(forecast_engine.FORECAST_COLUMNS) == 13
            assert not os.listdir(".")
        ''')
        with tempfile.TemporaryDirectory() as workdir:
            env = {k: v for k, v in os.environ.items() if k not in {
                "PYTHONPATH", "PYTHONHOME", "SINCEAI_ORGANIZER"
            }}
            completed = subprocess.run(
                [sys.executable, "-I", "-B", "-c", script], cwd=workdir, env=env,
                text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout, "")
            self.assertEqual(completed.stderr, "")
            self.assertEqual(list(Path(workdir).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
