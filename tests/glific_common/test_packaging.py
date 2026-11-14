"""pyproject.toml installs every shared package, not only the top level."""
import tomllib
import unittest
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class PackagingTest(unittest.TestCase):
    def test_every_shared_package_is_installed(self):
        conf = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]
        listed = conf.get("packages")
        include = ((conf.get("packages") or {}) if isinstance(listed, dict) else {}).get("find", {}).get("include", [])
        for init in (ROOT / "glific_common").rglob("__init__.py"):
            pkg = ".".join(init.parent.relative_to(ROOT).parts)
            covered = (isinstance(listed, list) and pkg in listed) or any(fnmatch(pkg, pat) for pat in include)
            self.assertTrue(covered, f"{pkg} is not installed by pyproject.toml")


if __name__ == "__main__":
    unittest.main()
