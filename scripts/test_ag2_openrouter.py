#!/usr/bin/env python3
"""Minimal test: AG2 GroupChat with OpenRouter Gemini + khive tools.

Usage:
  cd /Users/lion/projects/libs/opensrc/lionag2
  uv run python scripts/test_ag2_openrouter.py
"""
import os
import asyncio
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv("/Users/lion/projects/hackathon-fordham/.env")

KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENROUTER_API_KEY", "")
print(f"API key: {KEY[:15]}...")

# ---- Test 1: AG2 ConversableAgent direct ----
print("\n=== Test 1: AG2 ConversableAgent direct ===")
from autogen import ConversableAgent, register_function

config_list = [{
    "model": "google/gemini-2.5-pro-preview",
    "api_key": KEY,
    "base_url": "https://openrouter.ai/api/v1",
    "default_headers": {"HTTP-Referer": "https://khive.ai", "X-Title": "lionag2"},
}]

agent = ConversableAgent("Surveyor", llm_config={"config_list": config_list}, human_input_mode="NEVER",
                          system_message="You are a researcher. Say one sentence about LLM debate, then TERMINATE.")
user = ConversableAgent("User", human_input_mode="NEVER", llm_config=False)

# Register a khive tool
from khive import Khive
client = Khive(api_key=os.environ.get("KHIVE_API_KEY", ""), base_url=os.environ.get("KHIVE_BASE_URL", "https://khive-mcp.fly.dev"), namespace="test-ag2")

def memory_recall(query: str) -> str:
    """Recall findings from khive memory."""
    result = client.memory.recall(query=query, limit=3)
    items = getattr(result, "items", []) or []
    return "\n".join(getattr(i, "content", str(i)) for i in items) or "No prior findings."

def memory_remember(content: str) -> str:
    """Store a finding in khive memory."""
    client.memory.remember(content=content, memory_type="semantic")
    return f"Stored: {content}"

register_function(memory_recall, caller=agent, executor=user, description="Recall from khive memory")
register_function(memory_remember, caller=agent, executor=user, description="Store in khive memory")

reply = agent.generate_reply(messages=[{"role": "user", "content": "What do you know about multi-agent debate for LLMs?"}])
print(f"Reply: {reply}")

# ---- Test 2: AG2 GroupChat with 3 agents ----
print("\n=== Test 2: AG2 GroupChat with 3 agents ===")
from autogen.agentchat.group import AgentTarget, ContextVariables, OnCondition, StringLLMCondition, TerminateTarget
from autogen.agentchat.group.patterns import DefaultPattern
from autogen.agentchat.group.multi_agent_chat import a_run_group_chat_iter
from autogen.events.agent_events import TextEvent

surveyor = ConversableAgent("Surveyor", llm_config={"config_list": config_list}, human_input_mode="NEVER",
                             system_message="You are Surveyor. Research the topic briefly. Hand off to Analyst.")
analyst = ConversableAgent("Analyst", llm_config={"config_list": config_list}, human_input_mode="NEVER",
                            system_message="You are Analyst. Verify one claim quantitatively. Hand off to Critic.")
critic = ConversableAgent("Critic", llm_config={"config_list": config_list}, human_input_mode="NEVER",
                           system_message="You are Critic. Challenge one finding. Then TERMINATE.")

register_function(memory_recall, caller=surveyor, executor=user, description="Recall from khive memory")
register_function(memory_remember, caller=analyst, executor=user, description="Store in khive memory")
register_function(memory_recall, caller=critic, executor=user, description="Recall from khive memory")

surveyor.handoffs.add_llm_conditions([OnCondition(target=AgentTarget(analyst), condition=StringLLMCondition(prompt="When research is done"))])
analyst.handoffs.add_llm_conditions([OnCondition(target=AgentTarget(critic), condition=StringLLMCondition(prompt="When analysis is done"))])
critic.handoffs.set_after_work(TerminateTarget())

pattern = DefaultPattern(initial_agent=surveyor, agents=[surveyor, analyst, critic], user_agent=user,
                          context_variables=ContextVariables(data={}))

async def run_groupchat():
    print("Running GroupChat...")
    async for event in a_run_group_chat_iter(
        pattern=pattern,
        messages="Does multi-agent debate improve LLM factual accuracy?",
        max_rounds=10,
        yield_on=[TextEvent],
    ):
        inner = getattr(event, "content", None)
        if isinstance(event, TextEvent):
            text = getattr(inner, "content", str(event)) if inner else str(event)
            sender = getattr(inner, "sender", "?") if inner else "?"
            print(f"  [{sender}]: {text[:150]}")
    print("GroupChat done.")

asyncio.run(run_groupchat())

# ---- Test 3: Through lionagi iModel (the path that fails in server) ----
print("\n=== Test 3: lionagi iModel → AG2 endpoint ===")
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
import lionagi as li
from lionag2.agent_tools import make_tools

class SimpleKnowledge:
    def memory_recall(self, q): return client.memory.recall(query=q, limit=3).__repr__()[:200]
    def memory_remember(self, c): client.memory.remember(content=c, memory_type="semantic")

registry = make_tools(SimpleKnowledge())

model = li.iModel(
    provider="ag2", endpoint="group_chat",
    agent_configs=[
        {"name": "Surveyor", "role": "researcher", "system_message": "Research briefly. Hand off to Critic.", "tools": ["memory_recall"], "handoffs": [{"target": "Critic", "condition": "When done"}]},
        {"name": "Critic", "role": "critic", "system_message": "Challenge one point. TERMINATE.", "tools": ["memory_recall"], "handoffs": []},
    ],
    llm_config={"config_list": config_list},
)
model.endpoint._tool_registry = registry

branch = li.Branch(chat_model=model)

async def run_lionagi():
    result = await branch.operate(instruction="Does debate help LLM accuracy?", invoke_actions=False)
    print(f"lionagi result: {str(result)[:300]}")

asyncio.run(run_lionagi())

print("\n=== All tests done ===")
