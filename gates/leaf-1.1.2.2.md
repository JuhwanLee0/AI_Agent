# Gates: Leaf 1.1.2.2 JinaVerifier & TavilyScout Fixes
Scope: Fix self.client bug and update model mappings in jina_verifier.py & tavily_scout.py.

- [x] G1: JinaVerifier initializes without error
  CHECK: PYTHONPATH=. python3 -c "from scripts.sns.jina_verifier import JinaVerifier; v = JinaVerifier(); print('JINA_OK: True')"
  EXPECT: JINA_OK: True
  EVIDENCE: JINA_OK: True
