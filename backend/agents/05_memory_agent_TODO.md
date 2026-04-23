# Memory Agent 상세 개발 계획 (05_memory_agent_TODO.md)

이 문서는 사용자의 "감성적인 요청"을 "기술적인 플랜"으로 연결하기 위해 과거의 성공 경험을 활용하는 **RAG(Retrieval-Augmented Generation)** 에이전트 개발 계획입니다.

## 아키텍처 개요

1. **단기 메모리(Session History)**: 현재 세션 내에서의 성공/실패 흐름 (Trajectory 기반)
2. **장기 메모리(Success Vector DB)**: 전 세계 사용자의 "트렌디한 편집", "성공적인 피드백 대응" 사례 (Embedding 기반)

---

## 단계별 구현 상세

### Phase 1: 성공 사례 데이터 색인 (Indexing Module)

단순한 텍스트가 아니라, *[요청 + 사진 상태(VLM) + 성공한 결과]*를 하나의 지식 단위로 묶어 저장합니다.

- [x] **1.1 사례 추출 (Extraction)** — 설계 변경: score 필터 없이 모든 편집 인덱싱
  - 편집 완료 시 자동 인덱싱 (score=0.5 neutral), 피드백 수신 시 score 업데이트
  - good/bad 모두 저장 → Planner가 실패 패턴도 학습 가능

- [x] **1.2 벡터 임베딩 생성 (Embedding)**
  - ChromaDB 내장 `all-MiniLM-L6-v2` 사용 (로컬 PoC)
  - 임베딩 텍스트: `"User Request: {text} | Scene: {scene} | Mood: {mood} | ..."`
  - 메타데이터: `session_id`, `satisfaction_score`, `is_correction_case`, `user_text`, `plan_json`

- [x] **1.3 벡터 DB 적재**
  - ChromaDB PersistentClient (`./data/chromadb`) 구현 완료
  - upsert 방식 — 동일 `event_id`로 재호출 시 score 업데이트

---

### Phase 2: 검색 및 컨텍스트 주입 (Retrieval Module)

사용자의 현재 요청과 가장 유사한 "과거의 성공적인 대응"을 찾아 Planner에게 전달합니다.

- [x] **2.1 유사 사례 검색 API (Memory Retrieval)**
  - `MemoryAgent.search_similar(user_text, vlm_context, is_correction, top_k=3)` 구현
  - `user_text + VLM context` 결합 텍스트로 쿼리, 코사인 유사도 0.25 이상만 반환
  - Orchestrator에서 VLM 분석 직후 동기 호출

- [x] **2.2 피드백 보정 검색 (Feedback Correction Retrieval)**
  - `is_correction=True` 시 `where={"is_correction_case": "true"}` 필터 우선 적용
  - 교정 사례 없으면 전체 검색으로 폴백

---

### Phase 3: Planner(LLM) 프롬프트 연동

- [x] **3.1 Planner 시스템 프롬프트 업데이트**
  - `planner.py` 내 `## Reference Success Cases from Memory (RAG)` 섹션 추가

- [x] **3.2 Few-Shot 동적 주입**
  - `_render_retrieved_cases()` 함수로 포맷팅하여 Planner 프롬프트에 주입:
    ```text
    [Case 1: similarity 82%]
    User Asked: "따뜻한 분위기로"
    Applied Plan: split_toning({highlights_hue: 35, shadows_hue: 25, ...})
    Satisfaction: 1.00
    ```
  - Planner rationale에 "RAG cases 1, 2, 3 참조" 명시 지시 확인됨

---

## 개발 핵심 팁

- **데이터 오염 방지**: ~~`negative` 피드백 사례는 제외~~ → **설계 변경**: good/bad 모두 저장.
  `satisfaction_score`를 메타데이터로 저장하므로, 향후 검색 시 score 기반 필터링 가능.
  현재는 Planner가 `previous_failed_attempts`로 직접 회피하는 방식을 병행 운용 중.

- **이미지 분석(VLM)의 중요성**: 사용자는 똑같이 "예쁘게"라고 말해도, 원본 사진 상태(어두움 vs 밝음)에 따라 성공 사례가 달라집니다. VLM Context를 임베딩에 포함하여 유사도 정확도 향상 — 구현 완료.

---

## 구현 현황 (2026-04-23 기준)

| 기능 | 상태 | 파일 |
|------|------|------|
| ChromaDB 연결 및 컬렉션 관리 | ✅ | `agents/memory_agent.py` |
| 자동 인덱싱 (편집마다) | ✅ | `routers/edit.py` |
| 피드백 score 업데이트 + 재인덱싱 | ✅ | `routers/feedback.py` |
| 배치 인덱싱 (`batch_index_from_trajectory`) | ✅ | `agents/memory_agent.py` |
| 교정 사례 우선 검색 | ✅ | `agents/memory_agent.py` |
| Planner RAG 주입 | ✅ | `agents/planner.py` |
| 외부 임베딩 모델 전환 | ❌ | 현재 내장 모델 사용 |
