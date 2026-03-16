import hmac

from fastapi import Depends, HTTPException, Request

from app.config import settings


def require_admin_key(request: Request) -> None:
    key = request.headers.get("X-Admin-Key", "")
    if not key or not hmac.compare_digest(key, settings.admin_secret_key):
        raise HTTPException(status_code=401, detail="Invalid or missing admin key")


AdminKeyDep = Depends(require_admin_key)
