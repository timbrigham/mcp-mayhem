"""A stand-in for `gh api`. Records every call, with the exact bytes of its --input file, to the
JSONL file named by FAKE_GH_LOG, and answers with canned GitHub-shaped JSON.

FAKE_GH_FAIL=<substring> makes any call whose endpoint or method contains it exit 1.
"""

import base64
import json
import os
import sys

args = sys.argv[1:]
assert args[0] == "api", args
method, endpoint, body = "GET", None, None
i = 1
while i < len(args):
    if args[i] == "-X":
        method = args[i + 1]
        i += 2
    elif args[i] == "--input":
        with open(args[i + 1], "rb") as fh:
            body = fh.read()
        i += 2
    else:
        endpoint = args[i]
        i += 1

with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"method": method, "endpoint": endpoint,
                          "body_b64": base64.b64encode(body).decode() if body else None}) + "\n")

fail = os.environ.get("FAKE_GH_FAIL")
if fail and (fail in endpoint or fail == method):
    sys.stderr.write("HTTP 422: fake failure\n")
    sys.exit(1)

req = json.loads(body) if body else {}
if endpoint == "graphql":
    q = req["query"]
    if "discussionCategories" in q:
        out = {"data": {"repository": {"id": "R1", "discussionCategories": {
            "nodes": [{"id": "C1", "name": "Errata"}, {"id": "C2", "name": "Q&A"}]}}}}
    elif "createDiscussion" in q:
        out = {"data": {"createDiscussion": {"discussion": {
            "number": 200, "url": "https://github.com/o/r/discussions/200"}}}}
    elif "addDiscussionComment" in q:
        out = {"data": {"addDiscussionComment": {"comment": {
            "url": "https://github.com/o/r/discussions/%d#discussioncomment-9"
                   % 142}}}}
    else:
        out = {"data": {"repository": {"discussion": {"id": "D1"}}}}
elif endpoint.endswith("/comments"):
    n = endpoint.split("/")[-2]
    out = {"html_url": "https://github.com/%s/issues/%s#issuecomment-1" % (
        "/".join(endpoint.split("/")[1:3]), n), "id": 1}
elif endpoint.endswith("/issues") and method == "POST":
    out = {"html_url": "https://github.com/%s/issues/101" % "/".join(endpoint.split("/")[1:3]),
           "number": 101}
elif method == "DELETE":
    out = None
else:
    out = {}
if out is not None:
    sys.stdout.write(json.dumps(out))
