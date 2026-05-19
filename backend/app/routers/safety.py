from fastapi import APIRouter
from pydantic import BaseModel

from app.services.safety_service import evaluate_safety

router = APIRouter()


class SafetyRequest(BaseModel):
    text: str


@router.post("/evaluate")
def evaluate(payload: SafetyRequest):
    return evaluate_safety(payload.text)
