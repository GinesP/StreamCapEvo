# ruff: noqa: PT009  # unittest-style assertions are intentional here
import io
import unittest
import warnings
from unittest.mock import patch

from app.utils import warning_capture
from app.utils.logger import logger


class WarningCaptureTests(unittest.TestCase):
    def setUp(self):
        warning_capture.install_warning_capture(max_entries=4)
        self._records = []
        self._sink_id = logger.add(self._records.append, level="DEBUG", format="{message}")

    def tearDown(self):
        logger.remove(self._sink_id)
        warning_capture.uninstall_warning_capture()

    def _logged_messages(self):
        return [str(rec).rstrip("\n") for rec in self._records]

    def test_warning_is_logged_with_category_and_source(self):
        warnings.warn("boom", RuntimeWarning, stacklevel=1)
        messages = self._logged_messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("Python warning: RuntimeWarning: boom", messages[0])
        self.assertIn("test_warning_capture.py", messages[0])

    def test_repeated_warning_at_same_location_is_deduplicated(self):
        with warnings.catch_warnings(), patch("sys.stderr", io.StringIO()):
            warnings.simplefilter("always")
            for _ in range(5):
                warnings.warn("boom", RuntimeWarning, stacklevel=1)
        self.assertEqual(len(self._logged_messages()), 1)

    def test_warning_still_written_to_stderr(self):
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            warnings.warn("boom", RuntimeWarning, stacklevel=1)
        self.assertIn("RuntimeWarning: boom", stderr.getvalue())

    def test_cache_eviction_reports_repeat_count(self):
        with warnings.catch_warnings(), patch("sys.stderr", io.StringIO()):
            warnings.simplefilter("always")
            for _ in range(3):
                warnings.warn("repeated-warning", UserWarning, stacklevel=1)
            warnings.warn("first-distinct", UserWarning, stacklevel=1)
            warnings.warn("second-distinct", UserWarning, stacklevel=1)
            warnings.warn("third-distinct", UserWarning, stacklevel=1)
            warnings.warn("fourth-distinct", UserWarning, stacklevel=1)

        debug_records = [rec for rec in self._records if rec.record["level"].name == "DEBUG"]
        self.assertEqual(len(debug_records), 1)
        self.assertIn("repeated 3x", str(debug_records[0]))
        self.assertIn("UserWarning", str(debug_records[0]))

    def test_install_is_idempotent(self):
        # setUp already installed the hook; reinstalling must not swap the
        # recorded original (which would break uninstall) nor replace the handler.
        original = warning_capture._original_showwarning
        handler = warnings.showwarning
        warning_capture.install_warning_capture()
        self.assertIs(warnings.showwarning, handler)
        self.assertIs(warning_capture._original_showwarning, original)

    def test_uninstall_restores_original_hook(self):
        warning_capture.uninstall_warning_capture()
        original = warnings.showwarning
        warning_capture.install_warning_capture()
        self.assertIsNot(warnings.showwarning, original)
        warning_capture.uninstall_warning_capture()
        self.assertIs(warnings.showwarning, original)


if __name__ == "__main__":
    unittest.main()
