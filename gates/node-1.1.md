# Gates: Branch 1.1 LLM Cloud Engine & Quota Shield

Scope: Orchestrator LLM calls, Cerebras/Groq fallback, think tag stripping, and SNS pipeline modernization.

- [x] G1: Orchestrator client candidates resolution
  CHECK: PYTHONPATH=. python3 -c "from ai_company.agents.orchestrator import CompanyOrchestrator; orch = CompanyOrchestrator(); print('CANDS:', len(orch.get_client_candidates('CEO')) >= 2)"
  EXPECT: CANDS: True
  EVIDENCE: 2026-08-24 08:53:14,358 [INFO] Pinned ORT_DYLIB_PATH to bundled ONNX Runtime: /opt/homebrew/lib/python3.11/site-packages/onnxruntime/capi/libonnxruntime.1.26.0.dylib | 2026-08-24 08:53:14,382 [INFO] H

- [x] G2: SNS Config and Verifier modernization
  CHECK: PYTHONPATH=. python3 -c "from scripts.sns.config import KeyPoolManager; from scripts.sns.jina_verifier import JinaVerifier; print('SNS_CONFIG_VERIFIER: OK')"
  EXPECT: SNS_CONFIG_VERIFIER: OK
  EVIDENCE: SNS_CONFIG_VERIFIER: OK
