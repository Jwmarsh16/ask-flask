# server/services/agents/simple_agent.py
# Path: server/services/agents/simple_agent.py
# Minimal planner → executor → validator. Tools are plain callables.

from typing import Any, Callable, Dict, List


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any]):
        self._tools[name] = fn  # register a callable tool

    def call(self, name: str, **kwargs):
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[name](**kwargs)


def plan(user_goal: str) -> List[Dict]:
    """Super simple planner: for factual questions, hit 'rag.search'."""
    return [{"tool": "rag.search", "args": {"query": user_goal}}]


def validate(response: Dict) -> Dict:
    """Placeholder validator: ensure we have at least one citation hit."""
    response["valid"] = bool(response.get("hits"))
    return response


def run_agent(user_goal: str, tools: ToolRegistry) -> Dict:
    steps = plan(user_goal)
    result = None
    for step in steps:
        out = tools.call(step["tool"], **step["args"])
        result = {"hits": out}
    return validate(result or {})
