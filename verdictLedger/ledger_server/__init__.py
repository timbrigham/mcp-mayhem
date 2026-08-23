"""MCP transport for verdictLedger. Deliberately NOT `mcp_server` (sjv) and NOT
`gitrobot_server` (gitRobot): the supervisor matches processes on a command-line
substring only, so a shared module path makes two servers indistinguishable and a
repair on one kills the other."""
