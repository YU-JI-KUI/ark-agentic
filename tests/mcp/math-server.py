from mcp.server.fastmcp import FastMCP

# Create an MCP server
mcp = FastMCP("MathServer")

@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b

@mcp.tool()
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b

if __name__ == "__main__":
    # Run the server using standard input/output
    mcp.run()
