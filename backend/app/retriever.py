import json

import faiss
from sentence_transformers import SentenceTransformer

from app import config

_modelo_embedding = None
_indice_faiss = None
_chunks = None


def _carregar_recursos():
    global _modelo_embedding, _indice_faiss, _chunks

    if _modelo_embedding is None:
        _modelo_embedding = SentenceTransformer(config.EMBEDDING_MODEL_NAME)

    if _indice_faiss is None:
        if not config.FAISS_INDEX_PATH.exists():
            raise RuntimeError(
                "Indice FAISS nao encontrado em "
                f"{config.FAISS_INDEX_PATH}. Execute "
                "'python -m app.build_index' antes de iniciar a API."
            )
        _indice_faiss = faiss.read_index(str(config.FAISS_INDEX_PATH))

    if _chunks is None:
        with open(config.CHUNKS_METADATA_PATH, encoding="utf-8") as arquivo:
            _chunks = json.load(arquivo)


def recuperar(pergunta, top_k=None):
    _carregar_recursos()

    if top_k is None:
        top_k = config.TOP_K

    vetor_pergunta = _modelo_embedding.encode(
        [pergunta],
        normalize_embeddings=True,
    ).astype("float32")

    scores, indices = _indice_faiss.search(vetor_pergunta, top_k)

    resultados = []

    for score, indice in zip(scores[0], indices[0]):
        if indice < 0:
            continue

        chunk = _chunks[indice].copy()
        chunk["score"] = float(score)
        resultados.append(chunk)

    return resultados