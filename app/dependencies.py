"""Singleton service instances shared across the app."""

from app.services.gateway import GatewayClient
from app.services.sandbox import SandboxService
from app.services.scheduler import RenewalScheduler
from app.services.storage import StorageService

storage = StorageService()
gateway = GatewayClient()
sandbox_service = SandboxService(storage=storage, gateway=gateway)
renewal_scheduler = RenewalScheduler(sandbox_service=sandbox_service)
