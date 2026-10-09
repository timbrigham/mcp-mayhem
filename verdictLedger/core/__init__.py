"""verdictLedger core.

`core` uses one module from the repository's shared `mcpcommon` package (the vocabularies in
`mcpcommon/vocabulary.py`, standard library only). It lives at the repository root, beside
`verdictLedger/`, so a checkout or an editable install (`pip install -e verdictLedger`) finds it
through the path added below. The MCP server already resolves it the same way.
"""

import sys
from pathlib import Path

try:
    import mcpcommon  # noqa: F401
except ImportError:
    _repo_root = Path(__file__).resolve().parents[2]
    if (_repo_root / "mcpcommon" / "vocabulary.py").is_file():
        sys.path.insert(0, str(_repo_root))
    else:
        raise ImportError(
            "verdictLedger needs the repository's `mcpcommon` package, which sits at the "
            "repository root beside `verdictLedger/`. Run from a full checkout of the repository "
            "(for example `pip install -e verdictLedger` inside it), or put the repository root "
            "on PYTHONPATH.") from None
