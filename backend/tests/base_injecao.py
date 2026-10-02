import json
from pathlib import Path

import numpy as np

from app import config

DOCUMENTOS_PATH = Path(__file__).resolve().parent / "documentos_injecao.json"


def carregar_documentos() -> list:
    return json.loads(DOCUMENTOS_PATH.read_text(encoding="utf-8"))


class BaseComInjecao:
    def __init__(self, recuperar_base, modelo_embedding=None):
        if modelo_embedding is None:
            from sentence_transformers import SentenceTransformer

            modelo_embedding = SentenceTransformer(config.EMBEDDING_MODEL_NAME)

        self.recuperar_base = recuperar_base
        self.modelo = modelo_embedding
        self.forcar_titulo = None
        self.forcou = False
        self.documentos = carregar_documentos()
        self.vetores = self._codificar([doc["texto"] for doc in self.documentos])

    def _codificar(self, textos: list):
        vetores = self.modelo.encode(textos, normalize_embeddings=True)
        return np.asarray(vetores, dtype="float32")

    def pontuar(self, pergunta: str, titulo: str) -> float:
        vetor = self._codificar([pergunta])[0]

        for doc, vetor_doc in zip(self.documentos, self.vetores):
            if doc["titulo"] == titulo:
                return float(vetor_doc @ vetor)

        raise KeyError(titulo)

    def recuperar(self, pergunta: str, top_k: int = None) -> list:
        top_k = top_k or config.TOP_K

        reais = self.recuperar_base(pergunta, top_k=top_k)

        vetor = self._codificar([pergunta])[0]
        scores = self.vetores @ vetor

        envenenados = []

        for doc, score in zip(self.documentos, scores):
            item = {chave: doc[chave] for chave in ("titulo", "categoria", "texto")}
            item["chunk_id"] = doc["id"]
            item["score"] = float(score)
            envenenados.append(item)

        combinados = sorted(
            list(reais) + envenenados,
            key=lambda doc: doc["score"],
            reverse=True,
        )

        selecionados = combinados[:top_k]
        self.forcou = False

        if self.forcar_titulo and all(
            doc["titulo"] != self.forcar_titulo for doc in selecionados
        ):
            alvo = next(
                doc for doc in envenenados if doc["titulo"] == self.forcar_titulo
            )
            selecionados = selecionados[:-1] + [alvo]
            self.forcou = True

        return selecionados