# Gates: Branch 1.3 17-Agent Instruction & 5-Layer Stack
Scope: Instructions, prompt loading, Claude-Mem, GSD, Graphify, and Ponytail context compliance.

- [x] G1: System prompts generate with 5-layer intelligence compliance
  CHECK: PYTHONPATH=. python3 -c "from ai_company.agents.orchestrator import CompanyOrchestrator; orch = CompanyOrchestrator(); p = orch.load_system_prompt('CEO'); print('5LAYER:', '5-LAYER' in p or 'GSD' in p)"
  EXPECT: 5LAYER: True
  EVIDENCE: 2026-08-24 08:53:17,838 [INFO] [router] route_counts={'ratio_too_high': 1, 'cache_miss': 1} compressed=0 frozen=0 msgs=1 | 2026-08-24 08:53:17,838 [INFO] Transform content_router: 1781 -> 1781 tokens 
