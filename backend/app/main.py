import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import config, memory
from app.models import ChatRequest, ChatResponse, FonteResposta, HealthResponse
from app.rag_graph import executar_rag
from app.retriever import _carregar_recursos as carregar_recursos_retriever

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chatbot_filmes")

app = FastAPI(
    title="Chatbot RAG - Filmes",
    description=(
        "API de um chatbot com RAG (Retrieval-Augmented Generation) sobre "
        "uma base de conhecimento de filmes, orquestrado com LangGraph e "
        "utilizando FAISS para busca vetorial e a Groq para geracao da "
        "resposta final."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def carregar_indice_na_inicializacao():
    try:
        carregar_recursos_retriever()
        logger.info("Indice FAISS e modelo de embeddings carregados com sucesso.")
    except Exception:
        logger.exception(
            "Falha ao carregar o indice FAISS na inicializacao. "
            "Verifique se 'python -m app.build_index' foi executado."
        )


@app.get("/health", response_model=HealthResponse)
def health():
    indice_ok = config.FAISS_INDEX_PATH.exists() and config.CHUNKS_METADATA_PATH.exists()

    total_chunks = None
    if config.CHUNKS_METADATA_PATH.exists():
        with open(config.CHUNKS_METADATA_PATH, encoding="utf-8") as arquivo:
            total_chunks = len(json.load(arquivo))

    return HealthResponse(
        status="ok",
        indice_carregado=indice_ok,
        total_chunks=total_chunks,
    )


@app.post("/chat", response_model=ChatResponse)
def chat(requisicao: ChatRequest):
    try:
        resultado = executar_rag(
            pergunta=requisicao.mensagem,
            session_id=requisicao.session_id,
        )
    except RuntimeError as erro:
        logger.error("Erro ao executar o fluxo de RAG: %s", erro)
        raise HTTPException(status_code=500, detail=str(erro)) from erro
    except Exception as erro:
        logger.exception("Erro inesperado ao processar a mensagem de chat.")
        raise HTTPException(
            status_code=500,
            detail="Erro interno ao processar a mensagem.",
        ) from erro

    fontes = [
        FonteResposta(
            titulo=doc["titulo"],
            categoria=doc.get("categoria", ""),
            score=doc["score"],
        )
        for doc in resultado.get("documentos_recuperados", [])
    ]

    return ChatResponse(
        resposta=resultado["resposta"],
        session_id=requisicao.session_id,
        score_maximo=resultado.get("score_maximo", 0.0),
        fontes=fontes,
    )


@app.delete("/chat/{session_id}")
def limpar_sessao(session_id: str):
    memory.limpar_sessao(session_id)
    return {"status": "sessao limpa", "session_id": session_id}