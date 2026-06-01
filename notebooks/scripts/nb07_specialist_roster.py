"""NB07 — Specialist Roster (no API keys needed)."""
from lionag2.research.prompts import CONNECTOR, build_node_instruction, build_roster

# build_roster adapts prompts based on available tools
roster = build_roster(has_khive=False, has_exa=True)

for spec in roster:
    print(f"\n{'='*60}")
    print(f"{spec['name'].upper()} — {spec['role']}")
    print(f"Tools: {spec['tools']}")
    print(f"Prompt: {spec['prompt'][:150]}...")

print(f"\n{'='*60}")
print(f"{CONNECTOR['name'].upper()} — {CONNECTOR['role']}")
print(f"Tools: {CONNECTOR['tools']}")
print("(Only added when KHIVE_API_KEY is set)")

# Depth-aware prompts
print("\n=== Depth-aware prompts ===")
for depth in range(3):
    instruction = build_node_instruction(
        "What causes high-Tc superconductivity?",
        depth=depth,
        max_depth=3,
    )
    print(f"\n--- Depth {depth} ---")
    print(instruction[:300])
    print("...")
