# Global Skill: Graphify - Codebase Knowledge Graph & Architecture Relations

## 1. Graphify 개요 및 목적
Graphify는 코드베이스와 지식 베이스를 방향성 지식 그래프(Knowledge Graph)로 추상화하여, 파일 간 의존성, 데이터 및 호출 흐름(Data/Call Flow), 핵심 허브 노드(God Nodes), 커뮤니티 구조를 직관적으로 파악할 수 있게 해주는 프레임워크입니다.

## 2. Graphify 활용 원칙
1. **아키텍처 경계 추적**:
   - 다중 파일에 걸친 변경이나 시스템 설계 시, `Graphify` 지식 그래프를 우선 참조하여 의존성 충돌이나 순환 참조를 사전 차단합니다.
2. **핵심 허브 노드 보호**:
   - 연결 차수(Degree)가 높은 핵심 노드(`orchestrator.py`, `instruction.md`, `AGENTS`) 수정 시, 연결된 모든 자식/의존 모듈의 파급 효과를 검증합니다.
3. **지식 그래프 지속 업데이트**:
   - 새 모듈 추가, 인터페이스 변경, 마이그레이션 발생 시 `.planning/graphs/graph.json` 지식 그래프에 노드 및 엣지를 반영합니다.
