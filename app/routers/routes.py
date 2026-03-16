from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.dependencies import storage
from app.middleware.auth import AdminKeyDep
from app.models.schemas import RouteEntry, RouteUpdateRequest

router = APIRouter(prefix="/api/v1/routes", dependencies=[AdminKeyDep])


@router.get("")
async def list_routes():
    mappings = await storage.get_route_mappings()
    return mappings


@router.get("/{apple_id:path}")
async def get_route(apple_id: str):
    mappings = await storage.get_route_mappings()
    entry = mappings.mappings.get(apple_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Route not found")
    return entry


@router.put("")
async def update_route(req: RouteUpdateRequest):
    mappings = await storage.get_route_mappings()
    mappings.mappings[req.apple_id] = RouteEntry(
        apple_id=req.apple_id,
        sandbox_id=req.sandbox_id,
        sandbox_url=req.sandbox_url,
        owner_email=req.owner_email,
        updated_at=datetime.utcnow(),
    )
    await storage.put_route_mappings(mappings)
    return mappings.mappings[req.apple_id]


@router.delete("/{apple_id:path}")
async def delete_route(apple_id: str):
    mappings = await storage.get_route_mappings()
    if apple_id not in mappings.mappings:
        raise HTTPException(status_code=404, detail="Route not found")
    del mappings.mappings[apple_id]
    await storage.put_route_mappings(mappings)
    return {"status": "deleted", "apple_id": apple_id}
