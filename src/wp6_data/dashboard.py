"""WP6 Dashboard - backwards compatibility shim.

This module re-exports from wp6_data.blue.dashboard for backwards compatibility.
New code should import from wp6_data.blue.dashboard directly.
"""

from wp6_data.blue.dashboard import app

# Re-export for backwards compatibility with existing deployments
__all__ = ["app"]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
