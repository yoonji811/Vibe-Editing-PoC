# Agentic AI Image Editor - Agents V2 (Memory & VLM)

6개 agent/모듈로 확장된 지능형 이미지 편집 시스템. 기존 V1의 단순 프롬프트-플랜 구조에서 VLM 상태 분석과 과거 성공 이력(RAG)이 주입된 피드백 학습 시스템으로 진화함.

---

## Agent 역할

| Agent | 역할 | 실행 시점 |
|-------|------|----------|
| **Orchestrator** | 런타임 제어, 상태 복구(Hydration), 피드백 분석(VLM 이전), VLM 및 Memory 호출 통합 관리 | Runtime (매 요청) |
| **VLM Analyzer** | 현재 이미지의 물리적(노이즈, 톤)/의미적(씬, 객체) 상태 추출 | Runtime (피드백 분석 후, Planner 전) |
| **Memory Agent** | VLM + User Prompt 기반 과거 유사 성공 사례 검색(RAG) 및 피드백 색인 | Runtime(검색), Async/Batch(색인) |
| **Planner** | 프롬프트, VLM 결과, 과거 사례(RAG), 실패 이력(Negative Constraints)을 종합하여 Plan 생성 | Runtime |
| **Validator** | Plan의 파라미터 정합성 및 실행 가능성 심사 *(현재 비활성화됨 - Bypassed)* | Runtime (Disabled) |
| **Tool Generator** | 세션 로그(unmet_requirements) 분석 → 신규 tool 코드 생성 및 등록 | 오프라인 배치 |

---

## 런타임 데이터 흐름 (Synchronous)

사용자의 피드백(Implicit) 분석은 값비싼 VLM(이미지 분석)을 호출하기 직전 **Orchestrator의 가장 첫 번째 단계**로 수행되어 이전 편집에 대한 사용자 의도(보정/불만족)를 먼저 확정합니다.

**VLM 결과(`source_image_context`)는 Planner에 직접 전달되지 않습니다.** Memory Agent의 RAG 검색 품질을 높이기 위해서만 사용되며, Planner는 오직 RAG로 검색된 사례(`retrieved_cases`)를 통해서만 간접적으로 이미지 상태 정보를 얻습니다.

```text
User Request (w/ Implicit/Explicit Feedback)
  └─ Orchestrator (메모리 부재 시 DB에서 Trajectory Hydration)
       ├─ 1. Next Prompt Analyzer (의도 및 피드백 분석): 사용자의 텍스트가 이전 플랜에 대한 교정인지 판단
       ├─ 2. VLM Analyzer (현재 이미지 상태 추출): Memory Agent용 이미지 상태 벡터 생성에만 사용
       └─ 3. Memory Agent (VLM + Prompt 기반 성공 사례 RAG 검색)
                ↓ retrieved_cases만 Planner에 전달 (VLM 원본은 전달 안 함)
            └─ Planner (RAG 사례 + 실패 이력 주입)
                 └─ Plan JSON 생성
                      └─ (Validator - 현재 Bypass) → Plan 실행 (Tool.run)
                           └─ Trajectory Store (DB/File): edit_applied 이벤트 및 VLM Context, Feedback 등 영구 기록
```

---

## 개발/학습 시점 흐름 (Asynchronous / Offline)

```text
Trajectory Store (과거 세션 데이터)
  ├─ Tool Generator: unmet_requirements 집계 → Tool 자동 생성 → Registry
  └─ Memory Agent: satisfaction_score >= 0.8 이벤트 필터링
       └─ [Prompt + VLM Context] 조합 벡터화 (Embedding)
            └─ Vector DB Upsert (성공적인 Params 및 Rationale 포함)
```

---

## 공통 계약 (Contracts)

### 1. Session & Trajectory 관리 (Hydration)

기존 메모리(dict) 기반 Tree 구조는 영속성 문제로 폐기. 모든 상태는 `trajectory_store.py`가 관리하는 데이터베이스(또는 파일)가 Single Source of Truth(SSoT)가 됨.

- **Hydration**: Orchestrator는 런타임에 메모리가 비어있으면 SSoT에서 세션 정보를 읽어와야 함(Stateless)
- **Feedback & Context**: 최종 저장되는 `edit_applied` 이벤트 페이로드에는 `source_image_context`(VLM 결과), `satisfaction_score`, `feedback_type`이 필수 기록되어야 함

### 2. Planner Input Context

Planner는 단순 사용자 텍스트가 아닌 복합 컨텍스트를 받음. Orchestrator가 조합하여 제공.

- **`user_text`**: 원본 프롬프트
- **`retrieved_cases`**: Memory Agent가 RAG로 검색한 과거의 "유사 상황 성공 Plan" (VLM 결과는 이 검색 품질을 높이는 데만 사용됨)
- **`previous_failed_attempts`**: 직전 턴에서 사용자가 불만족(Undo, "다시 해줘")했을 경우 실패했던 툴과 파라미터 조합 (절대 반복 금지)

> **`source_image_context`(VLM 결과)는 Planner에 전달하지 않음.** VLM은 Memory Agent의 임베딩 품질 향상과 Trajectory 저장(학습 데이터)에만 사용됨.

### 3. Plan JSON (Planner Output)

V1 구조를 유지하되, `rationale` 필드에 VLM 데이터나 과거 사례를 어떻게 참고했는지, 실패 이력을 어떻게 회피했는지 반드시 명시해야 함.

```json
{
  "plan_id": "uuid",
  "intent": "추론된 의도",
  "confidence": 0.0,
  "steps": [
    {
      "step_id": "s1",
      "tool_name": "...",
      "params": {"...": "..."},
      "depends_on": [],
      "produces": "...",
      "rationale": "RAG Case 1(유사도 87%)에서 유사한 요청에 split_toning이 성공함. 이전 시도에서 Gen Edit은 거절되었으므로 제외함."
    }
  ],
  "unmet_requirements": []
}
```

### 4. Tool Registry 인터페이스

Orchestrator는 여전히 Tool을 **블랙박스**로 취급. Planner만이 `description`과 `params_schema`를 읽고 Tool을 선택. 프롬프트 기반의 Gen Edit 도구도 OpenCV 등과 동등한 Tool로 취급됨.

### 5. 공용 LLM 호출

모든 에이전트는 하드코딩 없이 `CallLLM` 래퍼(또는 `llm.py`의 `call_llm`)를 통해 모델에 접근. RAG 결과 주입이나 VLM 시스템 프롬프트 업데이트는 각 Agent 내부의 메시지 조립부에서 담당.

---

## 모듈 문서 (V2)

- `01_orchestrator.md` (제어/Hydration)
- `02_planner.md` (복합 Context 기반 프롬프팅)
- `03_validator.md` (정합성 - 현재 비활성화)
- `04_tool_generator.md` (도구 자동 생성)
- `05_memory_agent.md` (피드백 RAG 시스템)
- `06_vlm_analyzer.md` (이미지 상태 추출 파이프라인 - 신규)
