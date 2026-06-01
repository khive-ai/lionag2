"""NB08 — khive Integration (runs without KHIVE_API_KEY, shows what's available)."""
import inspect

from lionag2.tools import KhiveKnowledgeStore, KhiveToolkit, khive_available

print(f"khive SDK available: {khive_available()}")

# KhiveKnowledgeStore implements AG2's Storage protocol
print("\n=== KhiveKnowledgeStore ===")
print(inspect.getsource(KhiveKnowledgeStore.__init__))

# Toolkit tools
if khive_available():
    kt = KhiveToolkit(namespace="demo")
    print(f"\n=== KhiveToolkit: {len(kt.tools)} tools ===")
    for t in kt.tools:
        print(f"  {t.name}: {t.description[:60]}")
else:
    print("\nkhive not installed. Install with: uv add 'lionag2[khive]'")
