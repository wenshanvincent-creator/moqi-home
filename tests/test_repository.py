import unittest
from pathlib import Path
from tools.prepare_repository import ROOT, selection


class RepositoryBoundaryTests(unittest.TestCase):
    def test_release_selection_contains_interfaces_and_excludes_private_state(self):
        files = selection()
        self.assertIn('moqi/api.py',files)
        self.assertIn('moqi/playground.py',files)
        self.assertIn('examples/observation.json',files)
        for name in files:
            self.assertNotIn(Path(name).parts[0], {'data','transfer','.cache','.claude','.venv','review'})
            self.assertNotIn(Path(name).suffix, {'.sqlite3','.log','.tar','.mp4','.docx'})
            self.assertNotIn(name, {'config.local.json','safety-policy.local.json','.env'})


if __name__ == '__main__': unittest.main()
