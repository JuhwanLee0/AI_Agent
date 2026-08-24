# Gates: Leaf 1.3.1.1 Instruction Path Normalization
Scope: Verify instruction.md format and handoff tags.

- [x] G1: instruction.md exists and is readable
  CHECK: PYTHONPATH=. python3 -c "from pathlib import Path; print('INST_EXISTS:', Path('ai_company/instructions/instruction.md').exists())"
  EXPECT: INST_EXISTS: True
  EVIDENCE: INST_EXISTS: True
