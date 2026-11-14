import ast
import os
import subprocess
import sys
import unittest

ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestSeedFiltersImports(unittest.TestCase):
    def _import(self, first, second):
        code = "import categories.{}; import categories.{}".format(first, second)
        result = subprocess.run([sys.executable, "-c", code], cwd=ENGINE_ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_programme_core_then_hub_seeds(self):
        self._import("programme_core", "hub_seeds")

    def test_hub_seeds_then_programme_core(self):
        self._import("hub_seeds", "programme_core")

    def test_core_module_has_no_category_import(self):
        with open(os.path.join(ENGINE_ROOT, "core", "seed_filters.py"), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                self.assertNotEqual(module.split(".")[0], "categories", module)

    def test_hub_seeds_reexports_filter(self):
        from categories import hub_seeds
        from core import seed_filters
        self.assertIs(hub_seeds._merge_seed_filter_reason, seed_filters._merge_seed_filter_reason)


if __name__ == "__main__":
    unittest.main()
