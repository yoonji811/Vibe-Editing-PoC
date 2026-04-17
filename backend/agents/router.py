"""FastAPI router for the agent-based editing pipeline.

Endpoints:
  POST /api/agent/edit/{session_id}  — run the Orchestrator pipeline
  POST /api/agent/edit               — start a new session (no session_id)
  GET  /api/agent/tree/{session_id}  — inspect edit tree for a session
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .orchestrator import OrchestratorAgent

router = APIRouter(prefix="/api/agent", tags=["agent"])

_orchestrator = OrchestratorAgent()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class AgentEditRequest(BaseModel):
    prompt: str = Field(..., description="사용자 편집 요청")
    image_b64: Optional[str] = Field(
        None,
        description="Base64 인코딩된 이미지. 새 세션 시작 시 필수.",
    )
    base_edit_id: Optional[str] = Field(
        None,
        description="분기 기준 편집 ID. None이면 해당 세션의 최신 편집.",
    )
    use_validator: bool = Field(
        True,
        description="Validator를 통해 plan을 검증할지 여부.",
    )
    mode: str = Field(
        "prod",
        description="'prod' | 'dev' — dev 모드는 unmet_requirements를 더 상세히 기록.",
    )


class AgentEditResponse(BaseModel):
    session_id: str
    edit_id: Optional[str]
    parent_edit_id: Optional[str]
    result_image_b64: Optional[str]
    executed_plan: Optional[Dict[str, Any]]
    explanation: str
    errors: list
    latency_ms: Optional[int] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/edit", response_model=AgentEditResponse, summary="새 세션으로 에이전트 편집 시작")
async def agent_edit_new(body: AgentEditRequest) -> AgentEditResponse:
    """새 세션을 생성하고 편집을 실행합니다.  image_b64가 필수입니다."""
    if not body.image_b64:
        raise HTTPException(
            status_code=400,
            detail="image_b64 is required to start a new session.",
        )
    result = _orchestrator.process_edit(
        prompt=body.prompt,
        image_b64=body.image_b64,
        session_id=None,
        base_edit_id=body.base_edit_id,
        use_validator=body.use_validator,
        mode=body.mode,
    )
    return AgentEditResponse(**result)


@router.post(
    "/edit/{session_id}",
    response_model=AgentEditResponse,
    summary="기존 세션에서 에이전트 편집 계속",
)
async def agent_edit_session(
    session_id: str, body: AgentEditRequest
) -> AgentEditResponse:
    """기존 세션에 새 편집을 추가합니다.

    - image_b64 생략 가능 (이전 편집 이미지 재사용)
    - base_edit_id로 특정 시점에서 분기 가능
    """
    result = _orchestrator.process_edit(
        prompt=body.prompt,
        image_b64=body.image_b64,
        session_id=session_id,
        base_edit_id=body.base_edit_id,
        use_validator=body.use_validator,
        mode=body.mode,
    )
    if result.get("edit_id") is None and result.get("errors"):
        raise HTTPException(status_code=422, detail=result["errors"])
    return AgentEditResponse(**result)


@router.get(
    "/tree/{session_id}",
    summary="세션의 편집 히스토리 트리 조회",
)
async def get_edit_tree(session_id: str) -> Dict[str, Any]:
    """세션 내 모든 편집 노드와 분기 관계를 반환합니다."""
    return _orchestrator.get_tree(session_id)
