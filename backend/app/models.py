from typing import List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):

    mensagem: str = Field(
        ...,
        min_length=1,
        description="Pergunta ou mensagem do usuario.",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Identificador da sessao de conversa, gerado pelo front-end. "
            "Usado para manter a memoria de conversa entre mensagens."
        ),
    )


class FonteResposta(BaseModel):

    titulo: str
    categoria: str
    score: float


class ChatResponse(BaseModel):

    resposta: str
    session_id: str
    score_maximo: float
    fontes: List[FonteResposta] = []


class HealthResponse(BaseModel):

    status: str
    indice_carregado: bool
    total_chunks: Optional[int] = None