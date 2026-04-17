# Tool Generator

**개발 시점에만 동작하는 오프라인 agent.** 런타임 파이프라인과 완전히 독립적이며, Orchestrator를 거치지 않고 독립 실행된다. 세션 로그와 히스토리를 읽고, 자주 필요하지만 registry에 없거나 비효율적인 tool 패턴을 찾아 **tool 코드를 생성하고 registry에 등록**하는 것까지 전부 책임진다.

## 실행 방식

- 독립 CLI 또는 주기적 배치 job (예: cron, 수동 트리거)
- 입력: 세션 로그 DB, 기존 tool registry
- 출력: 새 tool 코드 파일 + registry 업데이트

런타임 agent들(Orchestrator/Planner/Validator)은 Tool Generator의 존재를 알 필요 없다. 그저 registry를 조회할 뿐.

## 책임

1. **세션 로그 분석**: 최근 세션의 prompt, plan, `unmet_requirements`, 실패/재시도 패턴을 집계
2. **Tool 갭 식별**: 반복되는 unmet requirement, 동일 목적으로 여러 step을 조합하는 패턴 등 → "이게 단일 tool로 있으면 좋겠다" 후보 추출
3. **중복 체크**: 추가하려는 tool이 기존 registry에 유사하게 있는지 확인
4. **Spec 정제**: 모호한 후보를 구체적 입출력/params로 정리
5. **코드 생성**: 표준 Tool 인터페이스를 만족하는 Python 모듈 생성
6. **안전 검증**: 정적 분석 + sandbox 실행 테스트
7. **Registry 등록**: 검증 통과한 tool을 파일로 저장하고 registry 엔트리 추가

## 입력

```
session_log_source: DB 연결 or 로그 파일 경로
existing_registry: 현재 registry 스냅샷
analysis_window: 분석 대상 기간 (예: 최근 7일)
constraints: { allowed_libs, max_runtime_ms, target_mode: "staging"|"prod" }
human_review_required: bool (기본 true)
```

## 출력

각 후보에 대해:
```
status: created | duplicate | infeasible | failed
tool_name
code_path
registry_entry
analysis_evidence: 왜 이 tool이 필요하다고 판단했는지 (어느 세션/로그에서)
test_results
```

사람 리뷰 모드면 staging에 등록하고 승격 대기. 자동 모드면 prod에 바로 등록.

## 분석 단계: 세션 로그에서 tool 갭 찾기

Tool Generator의 핵심은 "무엇을 만들 것인가"를 스스로 판단하는 능력이다.

**1차 신호: 명시적 unmet_requirements**
- Planner가 `unmet_requirements`에 남긴 기록을 모음
- 유사한 need를 LLM으로 클러스터링 (임베딩 기반)
- 빈도 높은 클러스터 → 후보 tool

**2차 신호: 반복 조합 패턴**
- "같은 prompt 유형에서 항상 A→B→C 3-step이 쓰인다" → 단일 tool로 묶으면 효율적
- plan history에서 연속 step 시퀀스의 빈도 집계
- Validator reject가 잦은 패턴 → 현재 tool 조합으로 해결이 어색하다는 신호

**3차 신호: 사용자 재시도**
- 같은 세션에서 동일 의도 prompt가 여러 번 시도되고 결과가 불만족스러웠던 케이스
- prompt 유사도 + 사용자 재편집 행동으로 탐지

이 셋을 종합해 **"만들 가치가 있는 tool 후보 리스트"**를 뽑는다. 이 단계는 LLM 분석 + 통계 집계의 혼합.

## Tool 생성 파이프라인

각 후보에 대해:

**1. 중복 체크**
- 이름 유사도 + description 임베딩 cosine
- 유사도 높으면 duplicate로 스킵하고 "기존 X로 해결 가능"을 리포트

**2. Spec 정제 (LLM)**
- 후보 설명을 명확한 입출력/params로 정리
- 접근 방식 힌트 생성 (OpenCV 함수 조합? 생성형 wrapper?)

**3. 코드 생성 (LLM)**
- 표준 Tool 인터페이스 준수
- 허용된 라이브러리만 사용
- docstring, 타입 힌트, 입력 검증 포함

**4. 정적 분석**
- AST 파싱으로 금지 import/call 탐지
- `FORBIDDEN_IMPORTS = {os, sys, subprocess, socket, requests, urllib, pickle, shutil}`
- `FORBIDDEN_CALLS = {eval, exec, compile, __import__, open}`
- 위반 시 1회 재생성, 또 걸리면 failed

**5. Sandbox 실행 테스트**
- 별도 프로세스 또는 컨테이너에서 실행
- CPU/메모리/시간 제한
- 네트워크/파일시스템 차단
- 여러 해상도/채널의 더미 이미지로 run() 호출, 반환 타입 검증

**6. Registry 등록**
- tool 모듈을 `tools/generated/<name>_v<version>.py` 로 저장
- registry에 엔트리 추가 (name, description, params_schema, version_hash, module_path)
- 사람 리뷰 모드면 status를 `"staging"`으로, 자동 모드면 `"prod"`로

## 표준 Tool 인터페이스

생성되는 모든 tool이 따라야 할 구조:

```python
class Tool:
    name: str
    tool_type: str                # "opencv" | "generative" | "hybrid"
    description: str
    params_schema: dict           # JSON schema
    def run(self, image: np.ndarray, **params) -> np.ndarray: ...
```

## Registry 엔트리 형식

```
{
  "name": "opencv_color_keep",
  "version": "1.0.0",
  "type": "opencv",
  "module_path": "tools/generated/color_keep_v1.py",
  "description": "사용자 설명용 텍스트",
  "params_schema": { ... },
  "status": "staging" | "prod",
  "version_hash": "sha256:...",
  "created_by": "tool_generator",
  "created_at": ts,
  "analysis_evidence": {           # 왜 만들었는지 추적
    "trigger_signal": "unmet_requirement",
    "session_ids": [...],
    "frequency": 12
  }
}
```

## 코드 생성 LLM 지침

System prompt에 반드시 포함:
- 출력은 실행 가능한 단일 Python 파일, 다른 설명 없음
- 허용된 라이브러리만 import
- **파일 I/O, 네트워크 호출, `os.system`, `subprocess`, `eval`, `exec`, `__import__` 절대 금지**
- run() 시작부에 입력 검증 (None, shape, dtype)
- OpenCV 이미지는 BGR 가정
- 입력의 dtype/shape은 특별한 이유 없으면 보존
- 극단적 파라미터에도 예외 없이 동작하거나 명확한 에러
- 외부 API 호출이 필요한 tool은 클라이언트 주입 패턴 (코드 안에서 직접 호출 금지)

## 외부 API 의존 Tool

생성형 tool (inpainting, style transfer 등)은 외부 API를 쓰지만 **생성 코드가 직접 호출하지 않는다.** 의존성 주입:

```python
class InpaintingTool(Tool):
    def __init__(self, api_client):
        self.client = api_client
    def run(self, image, **params):
        return self.client.inpaint(image, params["mask"], params["prompt"])
```

이래야 sandbox에서 네트워크 막아도 검증 가능하고, 나중에 백엔드 교체도 쉽다.

## 안전 경계

- Tool Generator는 프로덕션 서비스 경로와 분리된 환경에서 실행 (별도 권한, 별도 container)
- 사람 리뷰 (staging → prod 승격)가 기본값
- 자동 모드(prod 직행)는 신중하게 선택. 특정 팀/프로젝트에서만 허용
- 등록된 tool은 `version_hash`로 변조 감지
- 생성된 tool의 실제 사용 로그를 모니터링, 문제 발생 시 status를 `deprecated`로 전환

## 전체 분석-생성 flow

```
세션 로그 DB ──┐
              ├──→ 1차/2차/3차 신호 집계 (LLM + 통계)
registry 스냅샷─┘             ↓
                       후보 리스트
                              ↓
            각 후보에 대해: 중복체크 → spec정제 → 코드생성
                          → 정적분석 → sandbox테스트
                              ↓
                   staging 등록 (+ 사람 리뷰) → prod 승격
                              ↓
                         registry 업데이트
```

## 하지 말 것

- 런타임 요청에 응답하기 (이 agent는 런타임과 무관)
- Orchestrator/Planner/Validator와 직접 통신 (오직 공용 registry와 로그 DB를 통해서만 간접 통신)
- 정적 분석이나 sandbox를 건너뛰고 등록하기
- 중복 체크 없이 비슷한 tool을 계속 추가하기
- 생성 근거(analysis_evidence) 없이 tool을 만들기
