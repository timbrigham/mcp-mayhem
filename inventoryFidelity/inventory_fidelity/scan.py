"""The scanner: what the deployed artifact ACTUALLY contains.

It reads a toy agent repository laid out as:

    prompts/*.md            prompt templates          (text form)
    tools/*.json            tool definitions          (json form)
    guardrails/*.yaml|.yml  guardrail/policy configs  (text form)
    models.json             model and dataset references, each with a content digest

A file component is named by its path relative to the artifact root, with forward slashes, so
the same file has the same name on every platform. A reference is named by its declared
'name'. Only the top level of each directory is read.

models.json format:

    {"references": [{"name": "chat-model", "ref": "llama3@sha256:<64 hex>"}, ...]}

Items that cannot be classified are reported as errors and their names are WITHHELD from
classification on both sides (see measure.py). Errors: a duplicate name, an unnamed reference,
a reference with no content digest, a file that cannot be read or put in canonical form.
"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Optional

from .canonical import CanonicalFormError, component_sha256, parse_json, reference_digest
from .inventory import CannotMeasure

# (directory, suffixes) per location. Suffixes are compared exactly, not through glob: on
# Windows a glob for "*.md" also matches "X.MD" and on Linux it does not, so the same artifact
# would scan differently by platform.
FILE_LOCATIONS = (
    ("prompts", (".md",)),
    ("tools", (".json",)),
    ("guardrails", (".yaml", ".yml")),
)
REFERENCE_FILE = "models.json"


@dataclass(frozen=True)
class ScanError:
    kind: str                 # duplicate-name | unnamed | no-digest | unreadable | not-canonical | not-scannable
    name: Optional[str]       # None when the item has no name
    location: str
    detail: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "name": self.name, "location": self.location, "detail": self.detail}


@dataclass(frozen=True)
class Item:
    name: Optional[str]
    location: str
    sha256: Optional[str] = None
    error: Optional[ScanError] = None


@dataclass(frozen=True)
class Scan:
    present: Mapping[str, str] = field(default_factory=dict)
    errors: tuple = ()
    locations: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "present", MappingProxyType(dict(self.present)))
        object.__setattr__(self, "errors", tuple(self.errors))
        object.__setattr__(self, "locations", tuple(self.locations))


def _location_label(directory: str, suffixes: tuple) -> str:
    return ", ".join(f"{directory}/*{s}" for s in suffixes)


def file_item(root: Path, relpath: str) -> Item:
    """One file component, hashed by THE routine. Used by both the scanner and 'register'."""
    try:
        raw = (root / relpath).read_bytes()
    except OSError as exc:
        return Item(relpath, relpath, error=ScanError("unreadable", relpath, relpath, f"could not read: {exc.strerror}"))
    try:
        return Item(relpath, relpath, sha256=component_sha256(relpath, raw))
    except CanonicalFormError as exc:
        return Item(relpath, relpath, error=ScanError("not-canonical", relpath, relpath, str(exc)))


def reference_items(raw: bytes) -> list:
    """Items from a reference file. Used by both the scanner and 'register'.

    A reference file that cannot be parsed raises CannotMeasure: its entries are then unknown,
    and measuring anyway would report every registered reference as vanished when nobody
    knows whether it is deployed."""
    loc = REFERENCE_FILE
    try:
        doc = parse_json(raw)
    except CanonicalFormError as exc:
        raise CannotMeasure(f"{loc} could not be read: {exc}",
                            f'{loc} is JSON of the form {{"references": [{{"name": ..., "ref": ...}}]}}') from None
    if not isinstance(doc, dict) or not isinstance(doc.get("references"), list):
        raise CannotMeasure(f"{loc} has no 'references' list",
                            f'{loc} is JSON of the form {{"references": [{{"name": ..., "ref": ...}}]}}')
    items = []
    for i, entry in enumerate(doc["references"]):
        where = f"{loc} references[{i}]"
        if not isinstance(entry, dict):
            items.append(Item(None, where, error=ScanError("unnamed", None, where, "entry is not an object")))
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            items.append(Item(None, where, error=ScanError("unnamed", None, where, "reference has no name")))
            continue
        try:
            items.append(Item(name, where, sha256=reference_digest(entry.get("ref"))))
        except CanonicalFormError as exc:
            items.append(Item(name, where, error=ScanError("no-digest", name, where, str(exc))))
    return items


def _settle(items: list) -> tuple:
    """Turn items into (present, errors). A name seen twice is an error and is never present:
    picking one of the two hashes would be a guess about which one is deployed."""
    counts = Counter(it.name for it in items if it.name is not None)
    errors = [it.error for it in items if it.error is not None]
    for name in sorted(n for n, c in counts.items() if c > 1):
        where = [it.location for it in items if it.name == name]
        errors.append(ScanError("duplicate-name", name, "; ".join(where),
                                f"name appears {len(where)} times"))
    present = {it.name: it.sha256 for it in items
               if it.error is None and it.name is not None and counts[it.name] == 1}
    return present, errors


def scan_artifact(root) -> Scan:
    root = Path(root)
    if not root.is_dir():
        what = "does not exist" if not root.exists() else "is not a directory"
        raise CannotMeasure(f"artifact {str(root)!r} {what}", "--artifact names the deployed artifact's directory")

    items: list = []
    locations: list = []
    for directory, suffixes in FILE_LOCATIONS:
        label = _location_label(directory, suffixes)
        d = root / directory
        if not d.exists():
            # Reported as "absent", distinct from "scanned, 0 items", so a reader can tell a
            # missing directory from an empty one.
            locations.append({"location": label, "status": "absent", "items": 0, "not_scanned": []})
            continue
        if not d.is_dir():
            raise CannotMeasure(f"{directory!r} in the artifact is not a directory",
                                f"{directory}/ is a directory, or is absent")
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name)
        except OSError as exc:
            raise CannotMeasure(f"{directory}/ could not be listed ({exc.strerror})",
                                f"{directory}/ is readable") from None
        found = [p for p in entries if p.is_file() and p.name.endswith(suffixes)]
        # Anything else in a scanned directory is listed, so an unscanned component (a
        # "system.MD", a subdirectory) is visible in the report instead of silently absent.
        skipped = [f"{directory}/{p.name}" for p in entries if p not in found]
        for p in found:
            items.append(file_item(root, f"{directory}/{p.name}"))
        locations.append({"location": label, "status": "scanned", "items": len(found), "not_scanned": skipped})

    ref = root / REFERENCE_FILE
    if not ref.exists():
        locations.append({"location": REFERENCE_FILE, "status": "absent", "items": 0, "not_scanned": []})
    else:
        try:
            raw = ref.read_bytes()
        except OSError as exc:
            raise CannotMeasure(f"{REFERENCE_FILE} could not be read ({exc.strerror})",
                                f"{REFERENCE_FILE} is readable, or is absent") from None
        refs = reference_items(raw)
        items.extend(refs)
        locations.append({"location": REFERENCE_FILE, "status": "scanned", "items": len(refs), "not_scanned": []})

    present, errors = _settle(items)
    return Scan(present=present, errors=tuple(errors), locations=tuple(locations))


def register_items(root, paths) -> tuple:
    """Inventory entries for the named files, through the SAME item functions the scanner uses.

    A path the scanner would never read is an error, not an entry: registering it would put a
    name in the inventory that can only ever be reported as vanished."""
    root = Path(root)
    if not root.is_dir():
        raise CannotMeasure(f"--root {str(root)!r} is not a directory", "--root names the artifact directory")
    items: list = []
    for given in paths:
        try:
            rel = (root / given).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            items.append(Item(None, str(given), error=ScanError("not-scannable", None, str(given), "path is outside --root")))
            continue
        if rel == REFERENCE_FILE:
            try:
                raw = (root / rel).read_bytes()
            except OSError as exc:
                raise CannotMeasure(f"{rel} could not be read ({exc.strerror})", f"{rel} exists and is readable") from None
            items.extend(reference_items(raw))
            continue
        directory, _, filename = rel.rpartition("/")
        suffixes = dict(FILE_LOCATIONS).get(directory)
        if suffixes is None or not filename.endswith(suffixes):
            scanned = "; ".join(_location_label(d, s) for d, s in FILE_LOCATIONS) + "; " + REFERENCE_FILE
            items.append(Item(rel, rel, error=ScanError(
                "not-scannable", rel, rel, f"the scanner reads only {scanned}")))
            continue
        items.append(file_item(root, rel))
    present, errors = _settle(items)
    return present, errors
