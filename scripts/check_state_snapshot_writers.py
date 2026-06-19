from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / 'docs' / 'state_snapshot_writer_inventory.md'
SCAN_ROOTS = (REPO_ROOT / 'aidm_server', REPO_ROOT / 'scripts')
REQUIRED_COLUMNS = ('Path', 'Scope', 'Expected writes', 'Category', 'Coordinator boundary', 'Audit/evidence', 'Action')


@dataclass(frozen=True)
class SnapshotWriter:
    path: str
    scope: str
    line: int
    source: str


@dataclass(frozen=True)
class InventoryEntry:
    path: str
    scope: str
    expected_writes: int
    category: str
    coordinator_boundary: str
    audit_evidence: str
    action: str


@dataclass(frozen=True)
class InventoryCheck:
    writers: list[SnapshotWriter]
    inventory: dict[tuple[str, str], InventoryEntry]
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def _repo_relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _is_state_snapshot_target(target: ast.expr) -> bool:
    if isinstance(target, ast.Attribute):
        return target.attr == 'state_snapshot'
    if isinstance(target, ast.Starred):
        return _is_state_snapshot_target(target.value)
    if isinstance(target, ast.List | ast.Tuple):
        return any(_is_state_snapshot_target(child) for child in target.elts)
    return False


def _is_session_constructor_call(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Name):
        return node.func.id == 'Session'
    if isinstance(node.func, ast.Attribute):
        return node.func.attr == 'Session'
    return False


def _assignment_targets(node: ast.AST) -> list[ast.expr]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, ast.AnnAssign):
        return [node.target]
    if isinstance(node, ast.AugAssign):
        return [node.target]
    return []


def _scope_for(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            return current.name
    return '<module>'


def _scan_file(path: Path) -> list[SnapshotWriter]:
    source_text = path.read_text(encoding='utf-8')
    tree = ast.parse(source_text, filename=str(path))
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    writers: list[SnapshotWriter] = []
    for node in ast.walk(tree):
        targets = _assignment_targets(node)
        if targets and any(_is_state_snapshot_target(target) for target in targets):
            source_segment = ast.get_source_segment(source_text, node) or ''
            first_line = source_segment.strip().splitlines()[0] if source_segment.strip() else '<unknown assignment>'
            writers.append(
                SnapshotWriter(
                    path=_repo_relative(path),
                    scope=_scope_for(node, parents),
                    line=node.lineno,
                    source=first_line,
                )
            )
            continue

        if not isinstance(node, ast.Call) or not _is_session_constructor_call(node):
            continue
        for keyword in node.keywords:
            if keyword.arg != 'state_snapshot':
                continue
            source_segment = ast.get_source_segment(source_text, keyword) or ast.get_source_segment(source_text, node) or ''
            first_line = source_segment.strip().splitlines()[0] if source_segment.strip() else '<unknown constructor>'
            writers.append(
                SnapshotWriter(
                    path=_repo_relative(path),
                    scope=_scope_for(node, parents),
                    line=getattr(keyword, 'lineno', node.lineno),
                    source=first_line,
                )
            )
    return writers


def scan_state_snapshot_writers() -> list[SnapshotWriter]:
    writers: list[SnapshotWriter] = []
    for root in SCAN_ROOTS:
        for path in sorted(root.rglob('*.py')):
            if '__pycache__' in path.parts:
                continue
            writers.extend(_scan_file(path))
    return sorted(writers, key=lambda writer: (writer.path, writer.line, writer.scope))


def _markdown_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip('|').split('|')]


def _strip_markdown_code(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value.startswith('`') and value.endswith('`'):
        return value[1:-1].strip()
    return value


def parse_inventory(path: Path = DEFAULT_INVENTORY) -> dict[tuple[str, str], InventoryEntry]:
    entries: dict[tuple[str, str], InventoryEntry] = {}
    header: list[str] | None = None
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line.startswith('|'):
            continue
        cells = _markdown_cells(line)
        if not cells:
            continue
        if cells[: len(REQUIRED_COLUMNS)] == list(REQUIRED_COLUMNS):
            header = cells
            continue
        if header is None:
            continue
        if all(re.fullmatch(r':?-{3,}:?', cell) for cell in cells):
            continue
        if len(cells) < len(header):
            continue
        row = dict(zip(header, cells, strict=False))
        path_value = _strip_markdown_code(row.get('Path', ''))
        scope = _strip_markdown_code(row.get('Scope', ''))
        expected_raw = row.get('Expected writes', '').strip()
        if not path_value or not scope:
            continue
        try:
            expected_writes = int(expected_raw)
        except ValueError as exc:
            raise ValueError(f'Invalid expected write count for {path_value}::{scope}: {expected_raw!r}') from exc
        key = (path_value, scope)
        if key in entries:
            raise ValueError(f'Duplicate inventory row for {path_value}::{scope}')
        entries[key] = InventoryEntry(
            path=path_value,
            scope=scope,
            expected_writes=expected_writes,
            category=_strip_markdown_code(row.get('Category', '')),
            coordinator_boundary=row.get('Coordinator boundary', '').strip(),
            audit_evidence=row.get('Audit/evidence', '').strip(),
            action=row.get('Action', '').strip(),
        )
    if header is None:
        raise ValueError(f'No state snapshot writer inventory table found in {path}')
    return entries


def check_inventory(path: Path = DEFAULT_INVENTORY) -> InventoryCheck:
    writers = scan_state_snapshot_writers()
    inventory = parse_inventory(path)
    actual_counts = Counter((writer.path, writer.scope) for writer in writers)
    errors: list[str] = []

    for key, count in sorted(actual_counts.items()):
        entry = inventory.get(key)
        if entry is None:
            locations = ', '.join(str(writer.line) for writer in writers if (writer.path, writer.scope) == key)
            errors.append(f'Uninventoried state_snapshot writer: {key[0]}::{key[1]} at line(s) {locations}')
            continue
        if entry.expected_writes != count:
            errors.append(
                f'Writer count mismatch for {key[0]}::{key[1]}: inventory expects {entry.expected_writes}, found {count}'
            )

    for key, entry in sorted(inventory.items()):
        if key not in actual_counts:
            errors.append(f'Inventory row has no matching writer: {entry.path}::{entry.scope}')

    return InventoryCheck(writers=writers, inventory=inventory, errors=errors)


def _print_current(writers: list[SnapshotWriter]) -> None:
    for writer in writers:
        print(f'{writer.path}:{writer.line}:{writer.scope}: {writer.source}')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Check documented Session.state_snapshot direct writers.')
    parser.add_argument(
        '--inventory',
        default=str(DEFAULT_INVENTORY),
        help='Inventory markdown file to validate against.',
    )
    parser.add_argument(
        '--print-current',
        action='store_true',
        help='Print the currently detected state_snapshot writer assignments.',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    inventory_path = Path(args.inventory)
    if not inventory_path.is_absolute():
        inventory_path = REPO_ROOT / inventory_path
    result = check_inventory(inventory_path)
    if args.print_current:
        _print_current(result.writers)
    if result.errors:
        for error in result.errors:
            print(f'[state-snapshot-writers][error] {error}', file=sys.stderr)
        return 1
    print(
        '[state-snapshot-writers] Inventory matches '
        f'{len(result.writers)} direct writes across {len(result.inventory)} documented scopes.'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
