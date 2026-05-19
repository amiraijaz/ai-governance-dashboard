from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class LogBase(BaseModel):
    model: str
    provider: str
    prompt: str
    response: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    safety_score: float = 1.0
    user_id: Optional[str] = None


class LogCreate(LogBase):
    pass


class LogRead(LogBase):
    id: int
    timestamp: datetime = datetime.utcnow()
