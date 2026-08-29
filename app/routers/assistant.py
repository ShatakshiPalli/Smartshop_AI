from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import AssistantAnswer, AssistantQuery
from app.services.assistant import answer_question

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.post("/ask", response_model=AssistantAnswer)
def ask(payload: AssistantQuery, db: Session = Depends(get_db)):
    result = answer_question(db, payload.question, product_id=payload.product_id)
    return AssistantAnswer(answer=result["answer"], sources=result["sources"])
