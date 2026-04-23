# Memory Agent 상세 개발 계획 (05_memory_agent_TODO.md)

이 문서는 사용자의 "감성적인 요청"을 "기술적인 플랜"으로 연결하기 위해 과거의 성공 경험을 활용하는 **RAG(Retrieval-Augmented Generation)** 에이전트 개발 계획입니다.

## 아키텍처 개요

1. **단기 메모리(Session History)**: 현재 세션 내에서의 성공/실패 흐름 (Trajectory 기반)
2. **장기 메모리(Success Vector DB)**: 전 세계 사용자의 "트렌디한 편집", "성공적인 피드백 대응" 사례 (Embedding 기반)

---

## 단계별 구현 상세

### Phase 1: 성공 사례 데이터 색인 (Indexing Module)

단순한 텍스트가 아니라, *[요청 + 사진 상태(VLM) + 성공한 결과]*를 하나의 지식 단위로 묶어 저장합니다.

- [ ] **1.1 성공 사례 추출 (Success Extraction)**
  - `TrajectoryEvent` 중 `satisfaction_score >= 0.8`인 이벤트를 수집
  - 입력 데이터 정규화: `[Prompt: "필름 느낌"] + [ImageMeta: "저채도, 인물 사진"]`

- [ ] **1.2 벡터 임베딩 생성 (Embedding)**
  - `text-embedding-3-small` (OpenAI/Gemini) 등을 활용
  - 메타데이터 필수 항목:
    - `intent`: 사용자의 의도 요약
    - `tools_used`: 사용된 툴 리스트 및 파라미터 (JSON)
    - `rationale`: Planner의 성공적인 추론 내용

- [ ] **1.3 벡터 DB 적재**
  - `ChromaDB` (로컬/PoC) 또는 `Pinecone` (클라우드) 활용

---

### Phase 2: 검색 및 컨텍스트 주입 (Retrieval Module)

사용자의 현재 요청과 가장 유사한 "과거의 성공적인 대응"을 찾아 Planner에게 전달합니다.

- [ ] **2.1 유사 사례 검색 API (Memory Retrieval)**
  - Orchestrator에서 사용자의 입력을 받으면 Memory Agent를 호출
  - `Current Prompt + Current VLM Image Meta`를 쿼리로 사용
  - Top-K (최적 2~3개) 검색 결과 반환

- [ ] **2.2 피드백 보정 검색 (Feedback Correction Retrieval)**
  - 만약 현재 요청이 "수정 요청(Correction)"인 경우, **"잘못된 플랜을 어떻게 수정해서 성공했는지"**에 대한 사례를 우선 검색
  - 예: "너무 밝아" → "밝기 조절 실패 후 CLAHE로 수정 성공한 사례" 검색

---

### Phase 3: Planner(LLM) 프롬프트 연동

- [ ] **3.1 Planner 시스템 프롬프트 업데이트**
  - `planner.py` 내 `_SYSTEM` 프롬프트에 `## Reference Success Cases` 섹션 추가

- [ ] **3.2 Few-Shot 동적 주입**
  - 검색된 사례를 아래 형식으로 주입하여 Planner가 학습하도록 함:
    ```text
    [Reference 1]
    Current Problem: 사진이 너무 어둡고 푸른 톤임
    User Asked: "따뜻하게 밝혀줘"
    Successful Plan: split_toning(highlights_hue=35, ..) -> brightness(value=15)
    ```

---

## 개발 핵심 팁

- **데이터 오염 방지**: `negative` 피드백이 담긴 사례는 임베딩 저장소에서 제외하거나, 명확히 `unsuccessful_case`로 표시하여 Planner가 피하도록 해야 함

- **이미지 분석(VLM)의 중요성**: 사용자는 똑같이 "예쁘게"라고 말해도, 원본 사진 상태(어두움 vs 밝음)에 따라 성공 사례가 달라집니다. 따라서 임베딩 시 사진 분석 데이터(VLM Context)를 반드시 포함해야 합니다.
