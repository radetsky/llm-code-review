"""
Golden cases: small git changes with known problems.

A case is a folder in evaluation/cases with these items:
  before/        the files before the change
  after/         the files after the change (the full tree)
  expected.json  the problems that a correct review reports

An expected problem names a file and a regular expression. The loader finds
the line of the first match in the file after the change, so a case does not
break when you edit the code in it. A case with an empty list is a clean
case: a correct review reports no critical issue and no warning.
"""

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

CASES_DIR = Path(__file__).parent / "cases"
BASE_BRANCH = "main"
HEAD_BRANCH = "feature"


@dataclass
class Expected:
    file: str
    line: int
    kind: str  # "critical" or "warning"
    note: str = ""


@dataclass
class Case:
    id: str
    description: str
    root: Path
    expected: list[Expected]
    extra_extensions: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.expected


def _resolve_line(root: Path, item: dict) -> int:
    text = (root / "after" / item["file"]).read_text(encoding="utf-8")
    pattern = re.compile(item["pattern"])
    for number, line in enumerate(text.split("\n"), 1):
        if pattern.search(line):
            return number
    raise ValueError(
        f"{root.name}: pattern {item['pattern']!r} not found in {item['file']}"
    )


def load_case(root: Path) -> Case:
    data = json.loads((root / "expected.json").read_text(encoding="utf-8"))
    expected = [
        Expected(
            file=item["file"],
            line=_resolve_line(root, item),
            kind=item.get("kind", "warning"),
            note=item.get("note", ""),
        )
        for item in data["expected"]
    ]
    return Case(
        id=root.name,
        description=data.get("description", ""),
        root=root,
        expected=expected,
        extra_extensions=data.get("extra_extensions", []),
    )


def load_cases(
    names: list[str] | None = None, cases_dir: Path = CASES_DIR
) -> list[Case]:
    """Load all cases, or only the named cases. Unknown names raise ValueError."""
    available = sorted(
        p for p in cases_dir.iterdir() if (p / "expected.json").is_file()
    )
    if names:
        known = {p.name for p in available}
        unknown = [n for n in names if n not in known]
        if unknown:
            raise ValueError(
                f"Unknown case(s): {', '.join(unknown)}. Known: {', '.join(sorted(known))}"
            )
        available = [p for p in available if p.name in names]
    return [load_case(p) for p in available]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=eval@example.com", "-c", "user.name=Eval", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _replace_tree(repo: Path, source: Path) -> None:
    """Make the working tree of repo equal to the tree in source."""
    for entry in repo.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    shutil.copytree(source, repo, dirs_exist_ok=True)


def build_repo(case: Case, destination: Path) -> Path:
    """Create a git repository with the base commit and the change commit.

    The base is on the branch main. The change is on the branch feature.
    """
    destination.mkdir(parents=True, exist_ok=True)
    _git(destination, "init", "-q", "-b", BASE_BRANCH)
    _replace_tree(destination, case.root / "before")
    _git(destination, "add", "-A")
    _git(destination, "commit", "-q", "--allow-empty", "-m", "base")
    _git(destination, "checkout", "-q", "-b", HEAD_BRANCH)
    _replace_tree(destination, case.root / "after")
    _git(destination, "add", "-A")
    _git(destination, "commit", "-q", "-m", "change")
    return destination
