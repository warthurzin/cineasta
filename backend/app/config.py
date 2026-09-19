import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL_NAME",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)

DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DOCUMENTOS_PATH = DATA_DIR / "filmes.json"

INDEX_DIR = Path(os.getenv("INDEX_DIR", BASE_DIR / "index"))
FAISS_INDEX_PATH = INDEX_DIR / "faiss.index"
CHUNKS_METADATA_PATH = INDEX_DIR / "chunks.json"

TOP_K = int(os.getenv("TOP_K", "8"))
LIMIAR_EVIDENCIA = float(os.getenv("LIMIAR_EVIDENCIA", "0.35"))

MAX_TURNOS_HISTORICO = int(os.getenv("MAX_TURNOS_HISTORICO", "6"))

LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))

LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "900"))

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

def validar_configuracao():
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY nao foi definida. Configure a variavel de ambiente "
            "GROQ_API_KEY (ver arquivo .env.example) antes de iniciar a "
            "aplicacao."
        )