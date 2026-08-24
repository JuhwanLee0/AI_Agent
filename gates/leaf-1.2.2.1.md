# Gates: Leaf 1.2.2.1 run_pipeline Error Isolation
Scope: Isolate agent pipeline errors and avoid infinite loops.

- [x] G1: run_pipeline and AUTO_RELAY_CHAINS verification
  CHECK: PYTHONPATH=. python3 -c "from ai_company.main import AUTO_RELAY_CHAINS; print('RELAYS:', len(AUTO_RELAY_CHAINS) >= 10)"
  EXPECT: RELAYS: True
  EVIDENCE: 2026-08-24 08:53:06,973 [INFO] Pinned ORT_DYLIB_PATH to bundled ONNX Runtime: /opt/homebrew/lib/python3.11/site-packages/onnxruntime/capi/libonnxruntime.1.26.0.dylib | 2026-08-24 08:53:06,987 [INFO] H
