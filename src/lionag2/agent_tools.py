"""Agent tool functions for AG2 GroupChat.

NO `from __future__ import annotations` here — AG2 and lionagi's
function_to_schema need real type objects, not string literals.
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def tavily_search_sync(query: str) -> str:
    """Search the web for academic papers, datasets, and research sources. Returns titles, snippets, and URLs."""
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=os.environ.get("TAVILY_API_KEY", ""))
        results = client.search(query, max_results=8, search_depth="advanced", include_raw_content=False)
        formatted = []
        for r in results.get("results", []):
            formatted.append(
                f"- {r.get('title','')}: {r.get('content','')} ({r.get('url','')})"
            )
        return "\n".join(formatted) if formatted else "No results found."
    except Exception as exc:
        return f"Search failed: {exc}"


def fetch_url_sync(url: str) -> str:
    """Fetch a URL and extract the main text content (≤8000 chars).
    Used so agents can read paper abstracts, dataset cards, blog posts in full
    rather than relying on tavily's 200-char snippets.
    """
    try:
        import httpx
        import re

        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(url, headers={"User-Agent": "lionag2-research/0.1"})
            r.raise_for_status()
            html = r.text

        # Strip scripts, styles, comments
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
        # Collapse tags to spaces
        text = re.sub(r"<[^>]+>", " ", html)
        # Decode common entities
        text = (
            text.replace("&amp;", "&")
            .replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&#39;", "'")
            .replace("&nbsp;", " ")
        )
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 8000:
            text = text[:8000] + "\n\n[truncated to 8000 chars]"
        return f"URL: {url}\n\n{text}"
    except Exception as exc:
        return f"fetch_url failed for {url}: {exc}"


def run_python_sandbox(code: str) -> str:
    """Execute Python code with numpy, scipy, pandas, sklearn available. 30 second timeout. Returns stdout + stderr."""
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            path = f.name
        try:
            result = subprocess.run(
                ["uv", "run", "--with", "numpy,scipy,pandas,scikit-learn,matplotlib", "python", path],
                capture_output=True, text=True, timeout=30,
                cwd=os.path.dirname(path),
            )
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"
            output += f"\nEXIT: {result.returncode}"
            return output
        finally:
            try:
                Path(path).unlink()
            except Exception:
                pass
    except subprocess.TimeoutExpired:
        return "TIMEOUT after 30 seconds"
    except Exception as exc:
        return f"Sandbox error: {exc}"


def make_tools(knowledge):
    """Create the full tool registry for AG2 GroupChat.

    Returns a dict mapping tool_name → callable. Agents reference tools by name
    in their AgentRole.tools list, and AG2's register_function attaches them.
    """
    client = knowledge._client  # khive SDK client

    # ---- Search ----
    def _tavily(query: str) -> str:
        """Search the web for academic papers, datasets, and research sources. Returns titles, short snippets, and URLs — call fetch_url to read the full content."""
        return tavily_search_sync(query)

    def _fetch_url(url: str) -> str:
        """Fetch a URL and extract its main text (~8000 chars). Use this AFTER tavily_search to read the actual paper / page rather than relying on snippets."""
        return fetch_url_sync(url)

    # ---- Code execution (real packages: numpy/scipy/pandas/sklearn) ----
    def _run_code(code: str) -> str:
        """Execute Python code in a sandbox with numpy, scipy, pandas, scikit-learn. 30s timeout."""
        return run_python_sandbox(code)

    # ---- Memory (semantic store) ----
    def _recall(query: str) -> str:
        """Recall prior findings from khive persistent memory via semantic search."""
        return knowledge.memory_recall(query)

    def _remember(content: str) -> str:
        """Store a finding in khive persistent memory so other agents and future explorations can access it."""
        knowledge.memory_remember(content)
        return f"Stored: {content}"

    # ---- Graph (entities + links — structured knowledge) ----
    def _graph_add_entity(name: str, entity_type: str, description: str) -> str:
        """Add a named entity (paper, person, concept, dataset, method) to the shared knowledge graph. Use for objects worth tracking."""
        try:
            result = client.graph.create(name=name, kind=entity_type, description=description)
            entity_id = getattr(result, "id", None) or getattr(result, "entity_id", None) or "unknown"
            return f"Created entity '{name}' (type={entity_type}, id={entity_id})"
        except Exception as exc:
            return f"graph.create failed: {exc}"

    def _graph_add_link(from_name: str, to_name: str, relationship: str) -> str:
        """Link two entities in the knowledge graph. relationship examples: 'cites', 'contradicts', 'extends', 'uses_method', 'authored_by'."""
        try:
            client.graph.link(from_name=from_name, to_name=to_name, kind=relationship)
            return f"Linked '{from_name}' --[{relationship}]--> '{to_name}'"
        except Exception as exc:
            return f"graph.link failed: {exc}"

    def _graph_search(query: str) -> str:
        """Search the knowledge graph by name or description. Use to find what other branches have already mapped."""
        try:
            result = client.graph.search(query=query, limit=10)
            items = getattr(result, "items", []) or []
            if not items:
                return "No matching entities."
            return "\n".join(
                f"- {getattr(e, 'name', '?')} ({getattr(e, 'kind', '?')}): {getattr(e, 'description', '')}"
                for e in items
            )
        except Exception as exc:
            return f"graph.search failed: {exc}"

    def _graph_neighbors(name: str) -> str:
        """List entities connected to a given entity in the knowledge graph."""
        try:
            result = client.graph.neighbors(name=name)
            items = getattr(result, "items", []) or getattr(result, "neighbors", []) or []
            if not items:
                return f"No neighbors of '{name}'."
            return "\n".join(
                f"- {getattr(e, 'name', '?')} via {getattr(e, 'kind', '?')}"
                for e in items
            )
        except Exception as exc:
            return f"graph.neighbors failed: {exc}"

    # ---- Communication (cross-team messaging) ----
    def _send_message(to_team: str, subject: str, content: str) -> str:
        """Send a message to another exploration branch / team. Use to flag contradictions, share findings, or request help."""
        try:
            client.communication.send(
                from_lambda=knowledge._tree_id,
                to_lambda=to_team,
                subject=subject,
                content=content,
            )
            return f"Sent message to '{to_team}': {subject}"
        except Exception as exc:
            return f"communication.send failed: {exc}"

    def _list_messages() -> str:
        """List inbound messages from other teams."""
        try:
            result = client.communication.list(lambda_id=knowledge._tree_id, status="unread", limit=10)
            items = getattr(result, "items", []) or getattr(result, "messages", []) or []
            if not items:
                return "No unread messages."
            return "\n".join(
                f"[from {getattr(m, 'from_lambda', '?')}] {getattr(m, 'subject', '')}: {getattr(m, 'content', '')}"
                for m in items
            )
        except Exception as exc:
            return f"communication.list failed: {exc}"

    return {
        # search
        "tavily_search": _tavily,
        "fetch_url": _fetch_url,
        # code
        "run_code": _run_code,
        # memory
        "memory_recall": _recall,
        "memory_remember": _remember,
        # graph
        "graph_add_entity": _graph_add_entity,
        "graph_add_link": _graph_add_link,
        "graph_search": _graph_search,
        "graph_neighbors": _graph_neighbors,
        # communication
        "send_message": _send_message,
        "list_messages": _list_messages,
    }
