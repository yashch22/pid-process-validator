from fastapi import APIRouter

from .upload import router as upload_router
from .graph import router as graph_router

api_router = APIRouter()
api_router.include_router(upload_router)
api_router.include_router(graph_router)
