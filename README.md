# mcp-mayhem

Tools that mediate and record what AI coding agents do in a git repository. Most are local
MCP servers; one is a standalone measurement tool. Python, standard library plus the `mcp`
package.

| folder | what it is |
|---|---|
| `gitRobot/` | mediated git: refuses work-destroying operations, gates and audits the rest |
| `verdictLedger/` | append-only record of check results, each bound to the exact file content it examined |
| `inventoryFidelity/` | compares an inventory of an AI system's components with what is deployed |
| `structuredJsonValidator/` | a schema-checked JSON registry |
| `mcpSupervisor/` | keeps the local servers running (Windows) |
| `mcpcommon/` | code shared by the servers |

Worked examples, each runnable in a few seconds:

- `verdictLedger/examples/evidence-currency/`
- `inventoryFidelity/examples/inventory-fidelity/`

`CLAUDE.md` holds the working notes for the AI sessions that develop this repository. It is
not user documentation.
