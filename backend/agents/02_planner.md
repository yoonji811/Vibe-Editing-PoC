# Planner

사용자 prompt를 Plan JSON으로 변환한다. Gemini 기반. **실행하지 않는다, 설계만 한다.**

## 책임

1. prompt + 세션 컨텍스트 + 이미지 메타를 종합해 의도를 추론하고 Plan JSON을 생성
2. 각 step에 registry의 tool을 고르고 params를 결정하고 rationale을 남긴다
3. 현재 registry만으로 완벽히 달성 불가능한 요구가 있으면 `unmet_requirements`에 기록 (런타임 동작에 영향 없음, Tool Generator 오프라인 분석용)
4. Validator reject 시 feedback을 반영해 재생성

## 입력 (Orchestrator가 전달)

- `prompt`
- `ancestor_chain`: base_edit_id부터 루트까지의 조상 편집들. 각 항목은 `{prompt, intent, plan_summary}`. **sibling 분기는 포함되지 않음.**
- `image_meta`: width, height, detected_objects, dominant_colors, scene_tags
- `available_tools`: registry에서 받은 `[{name, description, params_schema}]`
- `feedback` (재시도 시만): Validator의 직전 reject 사유
- `mode`: `"dev"` | `"prod"` — tool 부족 신호를 어떻게 낼지 결정

## 출력

공통 계약의 Plan JSON. 주요 필드:
- `intent`: 추론한 의도를 한 문장으로
- `confidence`: 모호한 prompt일수록 낮게
- `steps`: 최소 step 구성, 각 step에 `rationale` 필수
- `unmet_requirements`: 현재 tool로 완전히 커버되지 않는 요구 (아래 참조)

## LLM에 좋은 컨텍스트를 주는 방법

prompt 해석을 if/else 규칙으로 분기하지 않는다. 대신 **LLM이 판단할 수 있도록 충분하고 구조화된 컨텍스트를 주는 것**이 Planner의 핵심 설계다.

시스템 프롬프트에 포함되어야 할 요소:

**1. 사용 가능한 tool 카탈로그**
   - 각 tool의 `name`, `description`, `params_schema`를 읽기 쉬운 형태로 렌더
   - tool이 많아지면 카테고리별로 묶어서 제공 (블러/색보정/세그먼트/생성/업스케일 등)
   - LLM이 "이 작업엔 이 tool"을 스스로 판단하도록 함

**2. 이미지의 현재 상태를 구체적으로**
   - 단순 "인물 사진"이 아니라 "detected: face×2, sky, tree / dominant: blue sky, green / 1920×1080"
   - 조상 chain의 이전 plan 요약도 현재 이미지의 상태를 유추하는 근거가 됨

**3. 조상 chain을 시간 순서로**
   - "T-2: 배경 흐리게 했음 → T-1: 하늘 추가했음 → 현재" 형태
   - 이렇게 주면 "더 어둡게" 같은 모호 prompt에 대해 LLM이 직전 작업과 연결해 해석

**4. 출력 제약**
   - registry에 없는 tool_name을 만들어내면 안 됨
   - 언급되지 않은 요소는 건드리지 않음 (보존 원칙)
   - 최소 step 원칙
   - rationale 필수

**5. 재시도 시 feedback 구분 블록**
   - "이전 시도의 문제: …" 로 명확히 표시
   - LLM이 무엇을 고쳐야 하는지 직접 읽을 수 있게

Planner는 해석 규칙을 내장하지 않는다. 컨텍스트를 잘 주면 LLM이 해석한다. 규칙은 확장성도 없고 새로운 prompt 유형에 취약하다.

## 모드: dev vs prod

런타임에는 Tool Generator가 돌지 않는다. 하지만 "이 prompt는 지금 tool로는 불가능" 같은 신호는 수집되어야 한다.

**prod 모드**
- `unmet_requirements`는 조용히 기록만 함 (로그 + 세션 DB에 저장)
- 사용자에게는 "가능한 범위에서 최선의 plan"을 반환 (불완전해도 실행됨)
- 오프라인 Tool Generator가 이 로그를 주기적으로 분석

**dev 모드**
- `unmet_requirements`를 더 상세히 기록
- 필요하면 plan 자체를 비우고 "이 요청은 tool X, Y가 필요함"을 리턴해 개발자가 바로 확인
- 테스트/내부 툴에서 사용

`unmet_requirements` 포맷 예:
```json
[
  {
    "need": "이미지를 수채화 스타일로 전환",
    "why_unmet": "registry에 style transfer 계열 tool 없음",
    "suggested_tool_type": "generative"
  }
]
```

## 자체 체크 (반환 직전)

- 모든 `tool_name`이 `available_tools` 안에 있는가
- `depends_on`의 모든 참조가 존재하는 `step_id`를 가리키는가
- 모든 step에 `rationale`이 비어있지 않은가
- 조상 chain을 고려한 `intent`인가 (필요 시 self-review)

Validator가 다시 걸러내지만 여기서 미리 막으면 왕복이 줄어든다.

## 하지 말 것

- registry에 없는 tool 이름을 만들어내기 (반드시 `unmet_requirements`로 플래그)
- sibling 분기(이번 base_edit의 형제 가지)의 내용을 참고하기
- prompt 해석을 하드코딩된 규칙 테이블로 처리하기 (LLM 컨텍스트 설계로 해결)
- plan 실행이나 사용자 응답 조립 (Orchestrator의 일)
