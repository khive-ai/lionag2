"""NB10 — Recursive Depth (no API keys needed, shows prompt generation)."""
from lionag2.research.prompts import build_node_instruction

topic = "Does the magnetic resonance energy track Tc?"

for depth in range(4):
    instruction = build_node_instruction(topic, depth=depth, max_depth=3)
    lines = instruction.split("\n")
    for line in lines:
        if "Depth guidance" in line or "depth=" in line.lower():
            print(f"depth={depth}: {line.strip()}")
            break
