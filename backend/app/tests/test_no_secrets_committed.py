from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN_PATTERNS = [
    re.compile(r"(?<![A-Za-z])s" + r"k-(?:proj-|or-v1-|[A-Za-z0-9_-]{12,})"),
    re.compile(r"tv" + r"ly-[A-Za-z0-9_-]{8,}"),
    re.compile(r"DEEPSEEK_API_KEY\s*=\s*s" + r"k"),
    re.compile(r"OPENAI_API_KEY\s*=\s*s" + r"k"),
    re.compile(r"TAVILY_API_KEY\s*=\s*tv" + r"ly"),
]
ALLOWED_PLACEHOLDERS = [
    "tv" + "ly-YOUR_API_KEY",
    "s" + "k-YOUR_API_KEY",
    "OPENAI_API_KEY=",
    "DEEPSEEK_API_KEY=",
]
SCAN_GLOBS = [
    "backend/**/*.py",
    "backend/**/*.md",
    "backend/**/*.toml",
    "backend/**/*.env*",
    "backend-node-legacy/**/*.env*",
    "README.md",
    "AGENTS.md",
]
IGNORED_PARTS = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}


def test_legacy_env_file_is_not_present() -> None:
    assert not (ROOT / "backend-node-legacy" / ".env").exists()


def test_committable_files_do_not_contain_real_secret_markers() -> None:
    findings: list[str] = []
    for path in _scan_paths():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if _line_is_allowed_placeholder(line):
                continue
            for pattern in FORBIDDEN_PATTERNS:
                if pattern.search(line):
                    findings.append(f"{path.relative_to(ROOT)}:{line_number}:{pattern.pattern}")
    assert findings == []


def test_test_scripts_are_executable() -> None:
    for relative in ("scripts/test.sh", "scripts/test_unit.sh"):
        path = ROOT / relative
        assert path.exists(), relative
        assert path.stat().st_mode & 0o111, f"{relative} must be executable"


def _scan_paths() -> list[Path]:
    paths: set[Path] = set()
    for pattern in SCAN_GLOBS:
        paths.update(ROOT.glob(pattern))
    return sorted(path for path in paths if path.is_file() and _should_scan(path))


def _should_scan(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in IGNORED_PARTS for part in relative.parts):
        return False
    if path.name == ".env" or path.suffix in {".local", ".prod", ".production"}:
        return False
    return True


def _line_is_allowed_placeholder(line: str) -> bool:
    return any(placeholder in line for placeholder in ALLOWED_PLACEHOLDERS)
