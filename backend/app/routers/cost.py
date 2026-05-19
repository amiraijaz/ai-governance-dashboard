from fastapi import APIRouter

from app.services.cost_service import summarize_cost

router = APIRouter()


@router.get("/summary")
def cost_summary():
    return summarize_cost()
