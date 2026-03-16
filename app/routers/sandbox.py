from fastapi import APIRouter, HTTPException

from app.dependencies import sandbox_service
from app.middleware.auth import AdminKeyDep
from app.models.schemas import SandboxCreateRequest, SandboxResponse

router = APIRouter(prefix="/api/v1/sandboxes", dependencies=[AdminKeyDep])


def _to_response(meta) -> SandboxResponse:
    return SandboxResponse(
        sandbox_id=meta.sandbox_id,
        owner_email=meta.owner_email,
        apple_id=meta.apple_id,
        public_url=meta.public_url,
        state=meta.state,
        template_id=meta.template_id,
        created_at=meta.created_at,
        last_renewed_at=meta.last_renewed_at,
    )


@router.post("", status_code=201)
async def create_sandbox(req: SandboxCreateRequest):
    try:
        meta = await sandbox_service.create(
            email=req.email,
            apple_id=req.apple_id,
            template_id=req.template_id,
        )
        return _to_response(meta)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("")
async def list_sandboxes():
    all_meta = await sandbox_service.list_all()
    return [_to_response(m) for m in all_meta]


@router.get("/{sandbox_id}")
async def get_sandbox(sandbox_id: str):
    meta = await sandbox_service.get(sandbox_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    return _to_response(meta)


@router.post("/{sandbox_id}/pause")
async def pause_sandbox(sandbox_id: str):
    try:
        meta = await sandbox_service.pause(sandbox_id)
        return _to_response(meta)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{sandbox_id}/resume")
async def resume_sandbox(sandbox_id: str):
    try:
        meta = await sandbox_service.resume(sandbox_id)
        return _to_response(meta)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{sandbox_id}")
async def kill_sandbox(sandbox_id: str):
    try:
        meta = await sandbox_service.kill(sandbox_id)
        return _to_response(meta)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
