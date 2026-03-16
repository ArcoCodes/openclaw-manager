from fastapi import APIRouter

from app.middleware.auth import AdminKeyDep
from app.models.schemas import CronJobCreateRequest, CronJobStubResponse

router = APIRouter(prefix="/api/v1/cron-jobs", dependencies=[AdminKeyDep])


@router.post("", response_model=CronJobStubResponse)
async def create_cron_job(req: CronJobCreateRequest):
    return CronJobStubResponse()


@router.get("")
async def list_cron_jobs():
    return {"status": "stub", "message": "Not yet implemented", "jobs": []}


@router.delete("/{job_id}")
async def delete_cron_job(job_id: str):
    return {"status": "stub", "message": "Not yet implemented"}
