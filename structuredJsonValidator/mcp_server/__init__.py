"""Thin MCP transport over the handler library (spec §11).

Named ``mcp_server`` (not ``mcp``) so it never shadows the installed ``mcp``
package. This layer performs NO enforcement of its own — every tool calls the
library, which enforces the schema, the §7 rules, and the integrity chain. If
this server is down, the file and its rules still hold (spec §4 principle 4).
"""
