"""MCP transport for gitRobot. Deliberately NOT named mcp_server: the process
supervisor matches on a command-line substring, and the sibling registry already
occupies `mcp_server.server`."""
