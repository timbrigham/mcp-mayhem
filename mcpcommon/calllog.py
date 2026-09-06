"""HTTP call log for the MCP servers — request and response bodies, on disk, rotated.

⚠⚠ ONE IMPLEMENTATION, IMPORTED — NEVER COPIED INTO EACH SERVER. This file exists at
the repo root precisely because the alternative was four copies that drift. Measured
2026-09-05: `verdictLedger/client/record.py` (243 lines) and its installed twin in the
consumer repo (629 lines) had diverged in `emit()` and `_call()` with NOTHING comparing
them, because one file's docstring told you to copy it into the other tree. All four
servers live in THIS repo, so there is no fence to cross and no reason to copy.

WHY THIS EXISTS. The servers had no record of being called. gitRobot audits Tier 1/2
mutations to `.mcp-local/gitRobot/git_ops.jsonl` and deliberately skips Tier 3 reads
("the volume would bury the signal"); verdictLedger logs nothing at all — its
`records.jsonl` is the PRODUCT, the verdicts that PASSED validation. So a REFUSED
append left no trace anywhere, and `errors.py`'s stated fear — "a caller under pressure
retries its way past a validation rule" — was unfalsifiable. You cannot count retries
of an event nobody records.

⭐⭐ THIS IS THE SECOND MEASUREMENT, POINTED AT THE CONSUMER. The house rule is that a
value crossing between agents gets measured independently on both sides. Measured
2026-09-05: asked the peer session whether its client emits `failing`, and had to take
the answer on trust because the file is on their side of the hook fence. A call log
answers that question from OUR side, without asking anyone and without believing a
reply. Everything it records is a fact about bytes that actually arrived.

⚠ WHAT IT IS NOT. Not an audit log and not evidence for a gate. gitRobot's audit is
append-only and load-bearing; this rotates and DELETES its own oldest file by design.
Nothing may ever cite this log as proof a control ran — it is a fine-tuning instrument,
and a rotating file cannot carry a claim about the past.

⚠⚠ THE DATA IS THE CONSUMER'S, AND THIS REPO IS PUBLIC. Bodies carry ZeroParadox
content: `reason` prose, review findings, file paths. The default destination is the
gitignored `.mcp-local/`, which is a SEPARATE repo. Never point ZPLOG_DIR anywhere
tracked by mcp-mayhem.

⚠ TRUNCATION IS RECORDED, NEVER SILENT. A body over the cap is stored short and the row
says so — `body_truncated: true` with `body_bytes` naming the original length. A
silently shortened body read as a complete one is this codebase's defect class exactly:
a true value describing something other than what the field claims. `req_truncated` and
`resp_truncated` are separate flags because the two bodies are two claims.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import time
from pathlib import Path
from typing import Any, Optional

# ⚠ Defaults are Tim's, 2026-09-05: 5 files x 5 MB per server. Both are env-tunable
# because "scalable count" was the requirement — a server under a heavier consumer
# raises the count without a code change.
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUPS = 5

# ⚠⚠ THE STORED BODY CAP, WHICH IS NOT THE ROTATION CAP — AND 16 KB WAS WRONG. Raised to
# 64 KB on 2026-09-06 after the first real consumer traffic arrived and was MEASURED
# rather than guessed:
#
#     append request bodies, n=56:  min 4,810  median 35,216  max 50,886
#     over the old 16 KB cap:       54 of 56
#
# So the instrument was discarding 96% of the bodies it exists to capture, and the whole
# session retained 46% of the bytes on the wire. The 16 KB figure had been reasoned from
# gitRobot's 60,929-byte `status()` RESPONSE — a true measurement of the wrong object: the
# thing worth keeping is the consumer's REQUEST, and a coverage record naming 500 subjects
# is 35 KB of the payload the log was built to show.
#
# ⭐ 64 KB is chosen to sit ABOVE the observed maximum, not near it. A cap tuned to today's
# median silently starts truncating the moment the corpus grows, and a truncated body
# cannot show what differed between attempt one and attempt two of a retry — which is the
# single failure this log exists to catch.
#
# ⚠ THE COST IS WINDOW LENGTH AND IT IS REAL. Full bodies for this sample were 2.1 MB, so
# a 5 MB x 5 window holds roughly a dozen sessions. That is a rotation-size decision, not a
# cap decision — raise ZPLOG_MAX_BYTES if the history matters more than the disk.
DEFAULT_MAX_BODY = 64 * 1024

# ⚠ Accumulation ceiling, separate from the stored cap and the reason this middleware
# cannot be turned into a memory leak by a large stream. A streamable-HTTP response
# arrives as many `http.response.body` messages; without a ceiling a long SSE stream
# would be buffered in full just to throw most of it away at write time.
_ACCUM_CEILING = 256 * 1024


def _truthy(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no", "off", "")


def _clip(raw: bytes, cap: int) -> tuple[str, int, bool]:
    """Return (text, original_byte_length, truncated).

    ⚠ Decoded with `replace`, never `ignore`. A body that is not valid UTF-8 is a fact
    worth seeing as replacement characters; dropping the bytes silently would make a
    malformed request indistinguishable from a well-formed one, which is the whole
    failure mode this log exists to expose.
    """
    n = len(raw)
    if n <= cap:
        return raw.decode("utf-8", "replace"), n, False
    return raw[:cap].decode("utf-8", "replace"), n, True


def build_logger(server_name: str) -> tuple[logging.Logger, Path]:
    """A rotating JSONL logger for one server. Returns (logger, path).

    ⚠ `delay=True` so importing this module never creates a file for a server that is
    not actually serving — a zero-byte log is a claim that a server ran.
    """
    # ⚠⚠ ZPLOG_DIR IS A ROOT AND `server_name` IS ALWAYS APPENDED — never the final path.
    # Letting it BE the final path meant one exported ZPLOG_DIR pointed all four servers
    # at a single `http_calls.jsonl`. Four processes sharing one RotatingFileHandler do
    # not merely interleave: rollover RENAMES the open file, which fails on Windows while
    # another process holds it, so the log silently stops rotating and grows without
    # bound — an observability feature turning into a disk outage. Found 2026-09-05 by
    # the first live smoke test, which looked for the file where the shape SHOULD have
    # put it. Appending the name makes the collision unrepresentable rather than
    # documented.
    root = os.environ.get("ZPLOG_DIR")
    if root:
        directory = Path(root) / server_name
    else:
        # repo root = parents[1] of mcpcommon/calllog.py; .mcp-local is its sibling and
        # is gitignored. Resolved from __file__ so it does not depend on the cwd the
        # supervisor happens to start the server in.
        directory = Path(__file__).resolve().parents[1] / ".mcp-local" / server_name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "http_calls.jsonl"

    handler = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=int(os.environ.get("ZPLOG_MAX_BYTES", DEFAULT_MAX_BYTES)),
        backupCount=int(os.environ.get("ZPLOG_BACKUPS", DEFAULT_BACKUPS)),
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    # ⚠ A DEDICATED LOGGER WITH `propagate = False`. Sharing the root logger would put
    # these rows into uvicorn's stream and uvicorn's rows into this file; the resulting
    # JSONL would have lines that are not JSON, and a reader that assumes otherwise
    # crashes on the first one.
    logger = logging.getLogger(f"mcpcalllog.{server_name}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
    logger.addHandler(handler)
    return logger, path


class CallLogMiddleware:
    """Raw ASGI middleware recording every HTTP call with both bodies.

    ⚠⚠ RAW ASGI, NOT `BaseHTTPMiddleware`. Starlette's BaseHTTPMiddleware materialises
    the response before passing it on, which converts a streamable-HTTP/SSE response
    into a buffered one and breaks the transport this server runs on. Wrapping `receive`
    and `send` observes the same bytes without altering the flow — every message is
    forwarded onward unchanged, and the log is written after the response completes.

    ⚠ It sits BELOW tool dispatch on purpose. A call with a malformed envelope never
    reaches a tool function, so a log written inside a tool cannot see it — and those
    are exactly the calls worth seeing.
    """

    def __init__(self, app, logger: logging.Logger, *,
                 max_body: int = DEFAULT_MAX_BODY, server_name: str = "") -> None:
        self.app = app
        self.logger = logger
        self.max_body = max_body
        self.server_name = server_name

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        started = time.time()
        req_parts: list[bytes] = []
        resp_parts: list[bytes] = []
        req_bytes = 0
        resp_bytes = 0
        status: dict[str, Any] = {}

        async def recv():
            nonlocal req_bytes
            message = await receive()
            if message.get("type") == "http.request":
                chunk = message.get("body", b"") or b""
                req_bytes += len(chunk)
                if sum(len(p) for p in req_parts) < _ACCUM_CEILING:
                    req_parts.append(chunk)
            return message

        async def snd(message):
            nonlocal resp_bytes
            kind = message.get("type")
            if kind == "http.response.start":
                status["code"] = message.get("status")
            elif kind == "http.response.body":
                chunk = message.get("body", b"") or b""
                resp_bytes += len(chunk)
                if sum(len(p) for p in resp_parts) < _ACCUM_CEILING:
                    resp_parts.append(chunk)
            await send(message)

        error: Optional[str] = None
        try:
            await self.app(scope, recv, snd)
        except Exception as exc:               # noqa: BLE001 - re-raised below
            # ⚠ An exception is the most interesting row in the file and must not be
            # the one that goes unwritten. Recorded, then re-raised unchanged.
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            try:
                self._write(scope, status, req_parts, resp_parts,
                            req_bytes, resp_bytes, started, error)
            except Exception:                  # noqa: BLE001
                # ⚠⚠ LOGGING NEVER BREAKS SERVING. This server is a mandatory dependency
                # of every commit and push; a full disk must not become a failed push.
                # The cost of this swallow is that a broken log is silent — which is why
                # `selftest()` exists and is called at startup, where a failure is loud.
                pass

    def _write(self, scope, status, req_parts, resp_parts,
               req_bytes, resp_bytes, started, error) -> None:
        req_raw = b"".join(req_parts)
        req_text, _, req_trunc = _clip(req_raw, self.max_body)
        resp_text, _, resp_trunc = _clip(b"".join(resp_parts), self.max_body)

        # ⚠ NAME THE TOOL WHERE ONE IS NAMEABLE. The whole point is "which of our tools
        # does the consumer actually call", and digging that out of the body at read
        # time means every reader writes the same parser. Best-effort: a body that does
        # not parse leaves the field null rather than guessing.
        #
        # ⚠⚠ PARSED FROM `req_raw`, NOT FROM `req_text` — AND THE DIFFERENCE IS THE WHOLE
        # FIELD. `req_text` is CLIPPED to max_body; parsing that gives a tool name only
        # when the body happened to fit, so every call large enough to be interesting
        # would log `tool: null`. Caught by the middleware test 2026-09-05 with a 64-byte
        # cap: a well-formed `tools/call` for `append` recorded no tool at all. Same
        # defect this repo exists to remove — a true value read off the wrong object,
        # here the truncated COPY rather than the bytes that arrived.
        method = tool = rpc_id = None
        try:
            body = json.loads(req_raw.decode("utf-8", "replace")) if req_raw.strip() else None
            if isinstance(body, dict):
                method = body.get("method")
                # ⭐⭐ THE JOIN KEY FOR THE TWO-SIDED COMPARISON, AND IT IS A FIELD THAT
                # ALREADY EXISTS. The whole point of logging on both sides is that our
                # record of what ARRIVED and the consumer's record of what they SENT can
                # disagree — and a disagreement you cannot line up row-to-row is two piles,
                # not a check. Joining on (tool, timestamp, byte count) is not good enough:
                # same host means one clock, but a retry loop emits identical tool + size
                # within the same second, which is exactly the traffic worth inspecting.
                #
                # ⚠ NO NEW PROTOCOL SURFACE IS NEEDED. JSON-RPC already requires an `id`
                # on every request and the caller chooses it. A UUID there is unique by
                # construction, survives the MCP layer untouched, and needs no header
                # negotiation. Requested of the consumer 2026-09-06.
                rpc_id = body.get("id")
                params = body.get("params")
                if isinstance(params, dict):
                    tool = params.get("name")
        except Exception:                      # noqa: BLE001
            pass

        # ⚠ Second half of the key, and it disambiguates two clients calling concurrently.
        # A notification carries no `id` at all (`notifications/initialized`), so those rows
        # join on session alone — correct, since there is no response to compare either.
        session = None
        for raw_name, raw_value in (scope.get("headers") or []):
            if raw_name.lower() == b"mcp-session-id":
                session = raw_value.decode("latin-1", "replace")
                break

        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(started)),
            "server": self.server_name,
            "ms": round((time.time() - started) * 1000, 1),
            "client": (scope.get("client") or [None])[0],
            "path": scope.get("path"),
            "http_method": scope.get("method"),
            "status": status.get("code"),
            "rpc_method": method,
            "tool": tool,
            # ⚠ The join key. `rpc_id` is the caller's own JSON-RPC id — useless if they
            # reuse a constant (the stock client sends 1 and 2), unique if they send a
            # UUID. Logged either way: a repeated id is itself a finding about the caller.
            "rpc_id": rpc_id,
            "session": session,
            # ⚠ `_bytes` is the length ON THE WIRE, always — not the length of what is
            # stored above it. Two fields, two claims, which is why a truncated row is
            # still an honest measurement of size.
            "req_bytes": req_bytes,
            "req_truncated": req_trunc,
            "req": req_text,
            "resp_bytes": resp_bytes,
            "resp_truncated": resp_trunc,
            "resp": resp_text,
            "error": error,
        }
        self.logger.info(json.dumps(row, ensure_ascii=False, default=str))


def selftest(logger: logging.Logger, path: Path) -> None:
    """Write and read back one row, raising if the log is not actually working.

    ⭐ A GUARD AND ITS CLAIM LAND TOGETHER. The middleware swallows its own write errors
    so that logging can never fail a push — which means a silently broken log would look
    exactly like a quiet one. This runs once at startup, where raising is safe and
    visible, and turns "logging is enabled" from an assertion into a measurement.
    """
    logger.info(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "event": "logging_started", "path": str(path)}))
    for handler in logger.handlers:
        handler.flush()
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(
            f"call log at {path} is not writable — it wrote no bytes. "
            f"SATISFIED WHEN: the directory exists and is writable, or ZPLOG_ENABLED=0 "
            f"is set to run without a call log deliberately.")


def serve(mcp, server_name: str) -> None:
    """Run `mcp` over streamable HTTP with the call log installed.

    Replaces `mcp.run(transport="streamable-http")`. FastMCP's `run()` builds the
    Starlette app and starts uvicorn in one step with no seam to add middleware, so the
    app is built explicitly here instead.

    ⚠ ZPLOG_ENABLED=0 serves without the log rather than refusing to serve. This is an
    instrument, not a control: a server that will not start because its log is
    unavailable would make an observability feature into an outage.
    """
    import uvicorn

    app = mcp.streamable_http_app()
    if _truthy(os.environ.get("ZPLOG_ENABLED"), True):
        logger, path = build_logger(server_name)
        selftest(logger, path)
        app.add_middleware(
            CallLogMiddleware,
            logger=logger,
            max_body=int(os.environ.get("ZPLOG_MAX_BODY", DEFAULT_MAX_BODY)),
            server_name=server_name,
        )
    uvicorn.run(app, host=mcp.settings.host, port=mcp.settings.port,
                log_level=mcp.settings.log_level.lower())
