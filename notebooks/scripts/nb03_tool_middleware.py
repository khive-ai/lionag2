"""NB03 — Tool Middleware (no API keys needed)."""
import inspect

from lionag2.research.middleware import MAX_RESULT_CHARS, _clean_html, clean_search_results

raw_html = """
<html><head><script>var x = 1;</script>
<style>.cls { color: red; }</style></head>
<body><h1>Paper Title</h1>
<p>We show that spin fluctuations &amp; pairing mechanisms...</p>
<div class="sidebar">Navigation links</div>
</body></html>
"""

cleaned = _clean_html(raw_html)
print(f"Raw:     {len(raw_html)} chars")
print(f"Cleaned: {len(cleaned)} chars")
print(f"Result:  {cleaned!r}")
print(f"Max result chars before truncation: {MAX_RESULT_CHARS:,}")

print("\n=== Middleware source ===")
print(inspect.getsource(clean_search_results))
