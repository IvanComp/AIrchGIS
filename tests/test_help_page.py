import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "airchgis_app.py")


class HelpPageTests(unittest.TestCase):
    def test_help_opens_and_goes_back(self):
        at = AppTest.from_file(APP, default_timeout=120).run()
        at.button(key="as_nav_help").click().run()
        self.assertFalse(at.exception)
        headings = [m.value for m in at.markdown if m.value.startswith("##")]
        for h in ("## What is AIrchGIS?", "## How it works", "## What you can do", "## The map", "## Tips", "## Limits"):
            self.assertIn(h, headings)
        at.button(key="as_help_back").click().run()
        self.assertEqual(at.session_state["as_active_tool"], "RVT")
        self.assertFalse(at.exception)


if __name__ == "__main__":
    unittest.main()
