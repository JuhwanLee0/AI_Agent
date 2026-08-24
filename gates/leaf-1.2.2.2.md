# Gates: Leaf 1.2.2.2 Master main.py Daemon Defense
Scope: Ensure root main.py starts server, scheduler, and socket mode safely.

- [x] G1: Master main.py imports cleanly
  CHECK: PYTHONPATH=. python3 -c "import main; print('MAIN_OK: True')"
  EXPECT: MAIN_OK: True
  EVIDENCE: 2026-08-24 08:53:07,932 [INFO] Pinned ORT_DYLIB_PATH to bundled ONNX Runtime: /opt/homebrew/lib/python3.11/site-packages/onnxruntime/capi/libonnxruntime.1.26.0.dylib | 2026-08-24 08:53:07,944 [INFO] H
