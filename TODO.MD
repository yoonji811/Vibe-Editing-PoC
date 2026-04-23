# VibeEdit 프로젝트 지능형 고도화 로드맵 (Master TODO)

본 문서는 세션 영속성, VLM 기반 이미지 분석, 그리고 실시간 피드백 루프를 통한 지능형 편집 에이전트(Memory & Feedback Aware Agent)를 구현하기 위한 통합 계획입니다. 사용자가 직접 기획한 4단계(Phase 1~4)의 핵심 로직을 기반으로 인프라(Phase 5)를 더해 작성되었습니다.

---

## Phase 1: Event Log 및 피드백 수집 (Data Layer)

사용자의 만족도를 데이터화하여 학습 및 분석의 기초를 마련합니다.

- [ ] **1.1 명시적(Explicit) 피드백 수집 엔드포인트 및 UI 연동**
  - 클라이언트에서 좋아요/싫어요/Undo 버튼 클릭 시, 직전 `edit_applied`의 `event_id`를 `target_event_id`로 삼아 `user_feedback` 이벤트를 생성하는 API 구현
  - Payload 예시:
    ```json
    {"target_event_id": "", "feedback_type": "explicit", "action": "thumbs_up", "reward_score": 1.0}
    ```

- [ ] **1.2 암시적(Implicit) 피드백 수집 (다음 프롬프트 분석기)**
  - 새로운 `chat_input`이 들어왔을 때, 별도의 긍정 액션 없이 바로 텍스트가 입력되었다면, 작은 LLM/룰베이스를 통해 다음 프롬프트의 의도를 분석하여 `user_feedback` 자동 생성
  - 분석 로직 예시: 다음 프롬프트가 "아니, 더 어둡게 해줘", "너무 과해" 같은 교정(Correction) 요청이면 → 직전 결과에 대해 `reward_score: -0.5` 부여 및 `action: "re_prompt"` 지정

- [ ] **1.3 `edit_applied` 페이로드 스키마 업데이트 및 영속성**
  - 최종 기록되는 `edit_applied` 로그에 `source_image_context`(VLM 분석 결과) 필드를 추가
  - 저장 시점: Planner가 수립하고 Orchestrator가 실행을 완료한 후 로그를 DB에 적재할 때 포함됨
  - **영속성(Hydration)**: Orchestrator가 메모리에 없을 때 `trajectory_store.py`에서 전체 이력을 자동 로드하도록 구현

---

## Phase 2: VLM 기반 이미지 상태 추출 (Orchestrator Layer)

이미지의 기술적/감성적 상태를 수치화하여 Planner에게 전달합니다.

- [ ] **2.1 VLM 동기(Synchronous) 호출 파이프라인 구축**
  - 호출 시점: Orchestrator가 `chat_input`을 받고 Planner에게 태스크를 넘기기 직전
  - 현재 대상 이미지의 URL/바이트 데이터를 고급 VLM(GPT-4o, Claude 3.5 Sonnet 등)에 전달하여 상태 분석

- [ ] **2.2 고급 VLM 프롬프트 및 확장된 JSON 스키마 적용**
  - 3가지 Tool(Gen Edit, OpenCV, LUT)이 완벽히 라우팅될 수 있도록 깊이 있는 분석 정보 추출
  - 추출 스키마 세부화:
    - `semantic_understanding`: 피사체의 종류, 씬(Scene)의 전반적인 분위기 및 객체 구성 (프롬프트 기반 Gen Edit 참고용)
    - `physical_properties`: 노이즈 수준, 선명도, 왜곡, 해상도 상태 (OpenCV 참고용)
    - `colorimetry_and_lighting`: 색상 히스토그램 느낌(주 지배색), 광원 방향, 대비, 화이트밸런스 상태 (LUT, OpenCV 참고용)
    - `artistic_style`: 현재 적용된 아트 스타일 및 감성 (Gen Edit, LUT 참고용)

---

## Phase 3: 도구 선택 및 라우팅 지능 고도화 (Planner Layer)

VLM 분석 데이터를 바탕으로 최적의 도구를 선택하도록 Planner를 훈련합니다.

- [ ] **3.1 Planner 입력 Payload 수정**
  - Orchestrator가 Planner를 호출할 때 넘기는 정보에 `user_text`뿐만 아니라 앞서 뽑은 `source_image_context`(VLM JSON)를 함께 전달

- [ ] **3.2 Planner System Prompt 업데이트 (Tool Routing Guidelines)**
  - Planner가 VLM 정보를 바탕으로 명확하게 도구를 선택할 수 있도록 가이드라인 추가
  - Prompt 예시: *"VLM 데이터에서 `physical_properties.noise_level`이 'High'라면 화질 개선을 위해 OpenCV(Denoise)를 우선 고려하라. `semantic_understanding` 상 자연스러운 객체 추가/제거나 배경 전체 변경이 필요하다면 OpenCV 대신 프롬프트 기반의 Gen Edit 도구를 사용하라."*

- [ ] **3.3 전체 세션 맥락(Session Context) 및 상세 이력 전달 강화**
  - 현재 Planner는 `prompt`, `intent`, `plan_summary` 등 단순 정보만 받고 있음
  - 이전 단계들에서 실제 사용된 **상세 파라미터(Params)**, **사용자의 명시적/암시적 피드백 결과**, 그리고 **이전 편집들의 성공/실패 여부**를 모두 포함한 상세한 세션 컨텍스트(Session History)를 Planner에 전달하도록 수정

---

## Phase 4: 세션 내 단기 보정 (Undo & Correction Handling)

실패를 반복하지 않고 사용자의 피드백을 즉각 반영하는 로직을 구축합니다.

- [ ] **4.1 Request Payload에 실패 이력(Negative Constraints) 주입**
  - 사용자가 이전 편집을 Undo 하거나 "아니, 다르게 해줘"라고 했을 때 Orchestrator가 Planner를 호출하는 Request 객체에 `previous_failed_attempts` 배열을 추가
  - 구체적 방안 (Request Payload 예시):
    ```json
    {
      "user_text": "아니, 너무 인위적이잖아. 자연스럽게 해줘",
      "source_image_context": {"...": "..."},
      "previous_failed_attempts": [
        {
          "tool_used": "gemini_generative_edit",
          "params": {"instruction": "Make it trendy"},
          "reason_for_failure": "User requested correction/undo."
        }
      ]
    }
    ```

- [ ] **4.2 Planner System Prompt 업데이트 (회피 로직)**
  - Planner에게 전달하는 지시문에 다음 내용 추가:
  - *"사용자가 이전 편집에 불만을 표시했습니다. `previous_failed_attempts`에 있는 도구(Tool)와 파라미터(Params) 조합을 절대 반복하지 마십시오. 왜 실패했는지 추론(rationale)하고 전혀 다른 도구(예: Gen Edit이 실패했다면 LUT나 OpenCV 필터로 우회)를 Plan에 포함시키십시오."*

---

## Phase 5: Memory Agent (RAG) 파이프라인 통합 (Global Memory Layer)

과거의 성공 사례를 벡터화하고 검색하여, 개별 세션을 넘어선 글로벌 지능을 확보합니다.

- [ ] **5.1 경험 축적 파이프라인 구축 (Async Indexing)**
  - `edit_applied` 이벤트 저장 시(또는 배치 작업으로), `satisfaction_score`가 높은 이벤트를 필터링
  - `User Request` + `VLM Context`를 하나의 텍스트로 결합하여 벡터 임베딩 생성 (예: OpenAI/Gemini 임베딩)
  - 성공한 `plan`(도구, 파라미터, 추론)을 메타데이터로 묶어 Vector DB(ChromaDB 등)에 저장

- [ ] **5.2 RAG 검색 엔진 파이프라인 연동 (Orchestrator Layer)**
  - `OrchestratorAgent.process_edit` 내부에서 *Phase 2.1의 VLM 분석이 완료된 직후*, `MemoryAgent`를 동기적으로 호출
  - 현재의 `user_text`와 방금 추출한 `VLM JSON`을 조합해 Vector DB에서 가장 유사한 과거 성공 사례(Top-3) 검색

- [ ] **5.3 RAG 기반 성공 사례 주입 (Planner Layer)**
  - 검색된 과거 성공 사례(`retrieved_cases`) 배열을 Planner 호출 페이로드에 추가
  - `planner.py`의 프롬프트에 `## Reference Success Cases` 섹션을 추가하여, 유사 상황에서 검증된 도구와 파라미터 조합을 적극적으로 모방하도록 지시

---

## Phase 6: 인프라 및 확장성 (Infrastructure)

- [ ] **Stateless 세션 관리**: `_edit_trees`와 `image_store`를 Redis 또는 외부 DB로 이전하여 분산 환경 지원
- [ ] **이력 요약(Summarization)**: 세션이 길어질 경우 오래된 이력을 요약하여 LLM 토큰 한도 관리
