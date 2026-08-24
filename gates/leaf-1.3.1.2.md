# Gates: Leaf 1.3.1.2 5-Layer Intelligence Compliance
Scope: Verify prompt generation for all departments.

- [x] G1: System prompts for dev, marketing, media departments
  CHECK: PYTHONPATH=. python3 -c "from ai_company.agents.orchestrator import CompanyOrchestrator; orch = CompanyOrchestrator(); print('PROMPTS_OK:', all(len(orch.load_system_prompt(a)) > 100 for a in ['CEO', '개발팀장', '마케팅팀장', '미디어팀장']))"
  EXPECT: PROMPTS_OK: True
  EVIDENCE: 2026-08-24 08:53:10,106 [INFO] [router] route_counts={'ratio_too_high': 1, 'cache_miss': 1} compressed=0 frozen=0 msgs=1 | 2026-08-24 08:53:10,106 [INFO] Transform content_router: 1352 -> 1352 tokens 
