# VibeEdit 프로젝트 지능형 고도화 로드맵 (Master TODO)

본 문서는 세션 영속성, VLM 기반 이미지 분석, 그리고 실시간 피드백 루프를 통한 지능형 편집 에이전트(Memory & Feedback Aware Agent)를 구현하기 위한 통합 계획입니다. 사용자가 직접 기획한 4단계(Phase 1~4)의 핵심 로직을 기반으로 인프라(Phase 5)를 더해 작성되었습니다.

---

## Phase 1: Event Log 및 피드백 수집 (Data Layer)

사용자의 만족도를 데이터화하여 학습 및 분석의 기초를 마련합니다.

- [x] **1.1 명시적(Explicit) 피드백 수집 엔드포인트 및 UI 연동**
  - `POST /api/feedback/{session_id}` 구현 (`routers/feedback.py`)
  - `satisfaction_score` / `feedback_type` trajectory에 저장 및 ChromaDB 재인덱싱 트리거
  - Payload: `{"target_event_id": "", "feedback_type": "explicit", "action": "thumbs_up", "reward_score": 1.0}`

- [x] **1.2 암시적(Implicit) 피드백 수집 (다음 프롬프트 분석기)**
  - 룰베이스 대신 **LLM 기반**으로 구현 (`orchestrator.py:_detect_correction`)
  - 모델: `gemini-2.5-flash`, 이전 편집의 intent + tools를 컨텍스트로 전달해 교정 여부 판단
  - `is_correction=True` 시 → `previous_failed_attempts` 추출하여 Planner에 전달

- [x] **1.3 `edit_applied` 페이로드 스키마 업데이트 및 영속성**
  - `source_image_context` (VLM), `is_correction`, `timing_ms` 필드 추가
  - Hydration: `_hydrate_session()` 구현 — 서버 재시작 후 trajectory DB에서 edit tree 자동 복구

---

## Phase 2: VLM 기반 이미지 상태 추출 (Orchestrator Layer)

이미지의 기술적/감성적 상태를 수치화하여 Planner에게 전달합니다.

- [x] **2.1 VLM 동기(Synchronous) 호출 파이프라인 구축**
  - `agents/vlm_analyzer.py:VLMAnalyzerAgent.analyze()` 구현
  - 호출 시점: correction 감지 후, Memory Agent 검색 전 (임베딩 품질 향상용)
  - 모델: `gemini-2.5-flash` (vision), text/plain 모드로 JSON 추출
  - **설계 변경**: VLM 결과는 Planner에 직접 전달하지 않고 Memory Agent RAG 품질 향상 + trajectory 저장에만 사용 (`CLAUDE_override_v2.md` 참조)

- [x] **2.2 고급 VLM 프롬프트 및 확장된 JSON 스키마 적용**
  - 4가지 카테고리로 구조화된 분석:
    - `semantic_understanding`: subjects, scene_type, mood, objects
    - `physical_properties`: noise_level, sharpness, blur, resolution_quality
    - `colorimetry_and_lighting`: dominant_colors, color_temperature, contrast, brightness, lighting_direction
    - `artistic_style`: current_style, genre, mood_keywords

---

## Phase 3: 도구 선택 및 라우팅 지능 고도화 (Planner Layer)

VLM 분석 데이터를 바탕으로 최적의 도구를 선택하도록 Planner를 훈련합니다.

- [x] **3.1 Planner 입력 Payload 수정**
  - VLM 결과 직접 전달 대신 `retrieved_cases` (RAG)로 간접 전달 (설계 변경)
  - Planner 입력: `user_text` + `ancestor_chain` + `image_meta` + `retrieved_cases` + `previous_failed_attempts`

- [x] **3.2 Planner System Prompt 업데이트 (Tool Routing Guidelines)**
  - 색감/분위기 → `split_toning` / `color_grade` / `color_curves` / `hsl_selective`
  - 객체 제거/추가/스타일 → `gemini_*` generative 툴
  - 기하학/기술 조정 → OpenCV 툴
  - `hue_shift` 단독 사용 금지, 색감 요청에 `gemini` 사용 금지 명시

- [x] **3.3 세션 맥락 전달 강화**
  - `ancestor_chain`: 이전 편집 히스토리 (prompt / intent / tools / params / satisfaction)
  - `previous_failed_attempts`: 교정 감지 시 직전 plan의 tool+params 전달
  - `retrieved_cases`: Memory Agent RAG Top-3 성공 사례

---

## Phase 4: 세션 내 단기 보정 (Undo & Correction Handling)

실패를 반복하지 않고 사용자의 피드백을 즉각 반영하는 로직을 구축합니다.

- [x] **4.1 Request Payload에 실패 이력(Negative Constraints) 주입**
  - `_detect_correction()` → `is_correction=True` 시 `_build_failed_attempts()`로 직전 plan steps 추출
  - `previous_failed_attempts` 배열을 Planner에 전달 (최대 3개 step)
  - 테스트 확인: 교정 감지 시 이전 툴 회피 및 다른 툴 선택 동작 검증됨

- [x] **4.2 Planner System Prompt 업데이트 (회피 로직)**
  - `## Previous Failed Attempts (NEVER repeat these)` 섹션으로 주입
  - Planner가 rationale에 실패 이력 회피 명시하도록 지시

---

## Phase 5: Memory Agent (RAG) 파이프라인 통합 (Global Memory Layer)

과거의 성공 사례를 벡터화하고 검색하여, 개별 세션을 넘어선 글로벌 지능을 확보합니다.

- [x] **5.1 경험 축적 파이프라인 구축 (Async Indexing)**
  - `agents/memory_agent.py:MemoryAgent` 구현 (ChromaDB, `./data/chromadb`)
  - **설계 변경**: score 필터 없이 모든 편집 자동 인덱싱 (good/bad 모두 저장)
  - 편집 완료 시 `threading.Thread`로 비동기 인덱싱 (`routers/edit.py:_schedule_memory_index`)
  - 피드백 수신 시 score 업데이트 + 재인덱싱 (ChromaDB upsert)
  - 임베딩: ChromaDB 내장 `all-MiniLM-L6-v2` (로컬 PoC용)

- [x] **5.2 RAG 검색 엔진 파이프라인 연동 (Orchestrator Layer)**
  - VLM 분석 직후 `MemoryAgent.search_similar(user_text, vlm_context, is_correction)` 동기 호출
  - 교정 요청 시 `is_correction_case=true` 필터 우선 적용
  - 유사도 0.25 미만 결과 제외, Top-3 반환

- [x] **5.3 RAG 기반 성공 사례 주입 (Planner Layer)**
  - `retrieved_cases` Planner에 전달
  - `## Reference Success Cases from Memory (RAG)` 섹션으로 프롬프트 주입
  - Planner rationale에 RAG case 참조 명시 지시

---

## Phase 6: 인프라 및 확장성 (Infrastructure)

- [ ] **Stateless 세션 관리**: `_edit_trees`와 `image_store`를 Redis 또는 외부 DB로 이전하여 분산 환경 지원 (현재 서버 메모리 의존)
- [ ] **이력 요약(Summarization)**: 세션이 길어질 경우 오래된 이력을 요약하여 LLM 토큰 한도 관리

---

## 추가 발견 이슈 (미완료)

- [ ] **`color_curves` null 파라미터 버그**: Planner가 `red/green/blue=null`로 생성 시 `'NoneType' object is not iterable` 에러. 툴 내부에서 null 파라미터 방어 처리 필요
- [ ] **empty plan 시 `edit_applied` 미저장**: 현재 빈 plan도 trajectory에 저장됨. 실제 편집 없는 경우(unmet_requirements만 있는 경우)는 저장 제외 처리 필요
- [ ] **`--reload` 제거로 인한 개발 불편**: 현재 코드 변경 시 수동 서버 재시작 필요 (OneDrive 경로 + asyncio 조합 문제)
