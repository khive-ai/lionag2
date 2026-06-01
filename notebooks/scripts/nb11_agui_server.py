"""NB11 — ag-ui Server (no API keys needed, inspects routes)."""
from lionag2.research.server import app

print("=== Server Routes ===")
for route in app.routes:
    methods = getattr(route, "methods", ["*"])
    print(f"  {route.path} [{', '.join(methods)}]")
