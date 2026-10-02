import logging
import re
from typing import Literal

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app import config, llm, memory
from app.analise import interpretar_analise
from app.prompts import obter_prompts
from app.retriever import recuperar
from app.verificacao import interpretar_verificacao

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("chatbot_filmes.rag_graph")


class EstadoRAG(TypedDict, total=False):
    pergunta: str
    session_id: str
    top_k: int

    historico_formatado: str

    categoria: str
    pergunta_autonoma: str
    analise: dict

    query_busca: str
    documentos_recuperados: list
    score_maximo: float

    contexto: str
    fontes_contexto: list
    resposta: str
    geracao_falhou: bool
    verificacao: dict


def _reescrever_pergunta(pergunta: str, historico_formatado: str) -> str:
    if not historico_formatado:
        return pergunta

    prompts = obter_prompts(config.PROMPT_VERSION)

    mensagens = prompts.montar_mensagens_reescrita(pergunta, historico_formatado)

    resultado = llm.chamar_llm(mensagens, temperature=0, max_tokens=600)

    if not resultado.texto:
        logger.warning(
            "Reescrita de pergunta retornou vazia (finish_reason=%s) para "
            "a pergunta '%s'. Usando a pergunta original sem reescrita.",
            resultado.finish_reason,
            pergunta,
        )
        return pergunta

    return resultado.texto


def no_analisar(estado: EstadoRAG):
    prompts = obter_prompts(config.PROMPT_VERSION)

    if not prompts.USA_ANALISE:
        return {"categoria": "FILMES"}

    mensagens = prompts.montar_mensagens_analise(
        estado["pergunta"],
        estado.get("historico_formatado", ""),
        few_shot=config.FEW_SHOT,
    )

    try:
        resultado = llm.chamar_llm(
            mensagens,
            temperature=0,
            max_tokens=300,
            formato_json=True,
        )
        analise = interpretar_analise(resultado.texto)
    except Exception as exc:
        logger.warning(
            "Analise da pergunta falhou (%s: %s). Seguindo o fluxo sem analise.",
            type(exc).__name__,
            exc,
        )
        return {"categoria": "FILMES"}

    logger.info(
        "Analise: categoria=%s manipulacao=%s confianca=%s pergunta_autonoma=%r",
        analise.categoria,
        analise.manipulacao,
        analise.confianca,
        analise.pergunta_autonoma,
    )

    return {
        "categoria": analise.categoria,
        "pergunta_autonoma": analise.pergunta_autonoma.strip(),
        "analise": analise.model_dump(),
    }


def decidir_categoria(
    estado: EstadoRAG,
) -> Literal["filmes", "ambigua", "fora_dominio"]:
    categoria = estado.get("categoria", "FILMES")

    if categoria == "AMBIGUA":
        return "ambigua"

    if categoria == "FORA_DOMINIO":
        return "fora_dominio"

    return "filmes"


def no_esclarecer(estado: EstadoRAG):
    logger.info(
        "Pergunta ambigua, pedindo esclarecimento ao usuario: %r",
        estado.get("pergunta"),
    )

    prompts = obter_prompts(config.PROMPT_VERSION)

    return {
        "resposta": prompts.MENSAGEM_ESCLARECIMENTO,
        "documentos_recuperados": [],
    }


def no_recuperar(estado: EstadoRAG):
    pergunta = estado["pergunta"]
    top_k = estado.get("top_k") or config.TOP_K
    historico_formatado = estado.get("historico_formatado", "")

    pergunta_autonoma = estado.get("pergunta_autonoma")

    if pergunta_autonoma:
        query_busca = pergunta_autonoma
    else:
        query_busca = _reescrever_pergunta(pergunta, historico_formatado)

    if query_busca != pergunta:
        logger.info("Pergunta original: %r | Pergunta reescrita: %r", pergunta, query_busca)
    else:
        logger.info("Pergunta (sem reescrita, sem historico ou identica): %r", pergunta)

    recuperados = recuperar(query_busca, top_k=top_k)

    score_maximo = recuperados[0]["score"] if recuperados else 0.0

    logger.info(
        "Candidatos recuperados (top_k=%d): %s",
        top_k,
        [(round(r["score"], 4), r["titulo"]) for r in recuperados],
    )

    return {
        "documentos_recuperados": recuperados,
        "score_maximo": score_maximo,
        "query_busca": query_busca,
    }


def decidir_evidencia(estado: EstadoRAG) -> Literal["com_evidencia", "sem_evidencia"]:
    decisao = (
        "com_evidencia"
        if estado["score_maximo"] >= config.LIMIAR_EVIDENCIA
        else "sem_evidencia"
    )

    logger.info(
        "Decisao de roteamento: %s (score_maximo=%.4f, limiar=%.4f)",
        decisao,
        estado["score_maximo"],
        config.LIMIAR_EVIDENCIA,
    )

    return decisao


def no_montar_contexto(estado: EstadoRAG):
    prompts = obter_prompts(config.PROMPT_VERSION)

    contexto, fontes = prompts.formatar_contexto(estado["documentos_recuperados"])

    return {"contexto": contexto, "fontes_contexto": fontes}


def _filtrar_fontes_citadas(resposta: str, documentos_recuperados: list) -> list:
    numeros_citados = {
        int(numero) for numero in re.findall(r"\[Fonte\s+(\d+)\]", resposta)
    }

    if not numeros_citados:
        return []

    return [
        doc
        for i, doc in enumerate(documentos_recuperados, start=1)
        if i in numeros_citados
    ]


def no_gerar_resposta(estado: EstadoRAG):
    pergunta = estado.get("pergunta_autonoma") or estado["pergunta"]
    contexto = estado["contexto"]
    historico_formatado = estado.get("historico_formatado", "")

    prompts = obter_prompts(config.PROMPT_VERSION)

    mensagens = prompts.montar_mensagens_geracao(
        pergunta,
        contexto,
        historico_formatado,
    )

    resultado = llm.chamar_llm(
        mensagens,
        temperature=config.LLM_TEMPERATURE,
        max_tokens=config.LLM_MAX_TOKENS,
    )

    texto_resposta = resultado.texto
    geracao_falhou = False

    if not texto_resposta:
        geracao_falhou = True
        logger.warning(
            "Resposta final vazia da LLM (finish_reason=%s) para a "
            "pergunta '%s'.",
            resultado.finish_reason,
            pergunta,
        )
        texto_resposta = (
            "Nao foi possivel gerar uma resposta no momento. "
            "Tente reformular a pergunta ou envia-la novamente."
        )

    fontes_contexto = estado.get("fontes_contexto", [])
    fontes_citadas = _filtrar_fontes_citadas(texto_resposta, fontes_contexto)

    logger.info(
        "Resposta gerada: %r | Fontes citadas: %s",
        texto_resposta,
        [f["titulo"] for f in fontes_citadas],
    )

    return {
        "resposta": texto_resposta,
        "documentos_recuperados": fontes_citadas,
        "geracao_falhou": geracao_falhou,
    }


def no_verificar(estado: EstadoRAG):
    prompts = obter_prompts(config.PROMPT_VERSION)

    verificacao_pulada = {"suportada": True, "executada": False}

    if not prompts.USA_VERIFICACAO or not config.VERIFICAR_RESPOSTA:
        return {"verificacao": verificacao_pulada}

    resposta = estado["resposta"]

    if estado.get("geracao_falhou") or prompts.FRASE_ABSTENCAO in resposta:
        return {"verificacao": verificacao_pulada}

    fontes = estado.get("documentos_recuperados") or estado.get("fontes_contexto", [])

    if not fontes:
        return {"verificacao": verificacao_pulada}

    pergunta = estado.get("pergunta_autonoma") or estado["pergunta"]

    mensagens = prompts.montar_mensagens_verificacao(pergunta, resposta, fontes)

    try:
        resultado = llm.chamar_llm(
            mensagens,
            temperature=0,
            max_tokens=200,
            formato_json=True,
        )
        verificacao = interpretar_verificacao(resultado.texto)
    except Exception as exc:
        logger.warning(
            "Verificacao da resposta falhou (%s: %s). Resposta aceita sem verificacao.",
            type(exc).__name__,
            exc,
        )
        return {"verificacao": verificacao_pulada}

    logger.info(
        "Verificacao: suportada=%s observacao=%r",
        verificacao.suportada,
        verificacao.observacao,
    )

    return {
        "verificacao": {
            "suportada": verificacao.suportada,
            "observacao": verificacao.observacao,
            "executada": True,
        }
    }


def decidir_verificacao(estado: EstadoRAG) -> Literal["aceitar", "rejeitar"]:
    if estado.get("verificacao", {}).get("suportada", True):
        return "aceitar"

    return "rejeitar"


def no_rejeitar(estado: EstadoRAG):
    logger.info(
        "Resposta rejeitada pelo verificador: %r | Motivo: %r",
        estado.get("resposta"),
        estado.get("verificacao", {}).get("observacao"),
    )

    prompts = obter_prompts(config.PROMPT_VERSION)

    return {
        "resposta": prompts.MENSAGEM_NAO_SUSTENTADA,
        "documentos_recuperados": [],
    }


def no_sem_evidencia(estado: EstadoRAG):
    logger.info(
        "Fluxo de abstencao acionado para a pergunta %r (score_maximo=%.4f)",
        estado.get("pergunta"),
        estado.get("score_maximo", 0.0),
    )

    prompts = obter_prompts(config.PROMPT_VERSION)

    return {
        "resposta": prompts.MENSAGEM_SEM_EVIDENCIA,
        "documentos_recuperados": [],
    }


def _construir_grafo():
    builder = StateGraph(EstadoRAG)

    builder.add_node("analisar", no_analisar)
    builder.add_node("esclarecer", no_esclarecer)
    builder.add_node("recuperar", no_recuperar)
    builder.add_node("montar_contexto", no_montar_contexto)
    builder.add_node("gerar_resposta", no_gerar_resposta)
    builder.add_node("verificar", no_verificar)
    builder.add_node("rejeitar", no_rejeitar)
    builder.add_node("sem_evidencia", no_sem_evidencia)

    builder.add_edge(START, "analisar")

    builder.add_conditional_edges(
        "analisar",
        decidir_categoria,
        {
            "filmes": "recuperar",
            "ambigua": "esclarecer",
            "fora_dominio": "sem_evidencia",
        },
    )

    builder.add_conditional_edges(
        "recuperar",
        decidir_evidencia,
        {
            "com_evidencia": "montar_contexto",
            "sem_evidencia": "sem_evidencia",
        },
    )

    builder.add_edge("montar_contexto", "gerar_resposta")
    builder.add_edge("gerar_resposta", "verificar")

    builder.add_conditional_edges(
        "verificar",
        decidir_verificacao,
        {
            "aceitar": END,
            "rejeitar": "rejeitar",
        },
    )

    builder.add_edge("rejeitar", END)
    builder.add_edge("sem_evidencia", END)
    builder.add_edge("esclarecer", END)

    return builder.compile()


_grafo_rag = None


def _obter_grafo():
    global _grafo_rag

    if _grafo_rag is None:
        _grafo_rag = _construir_grafo()

    return _grafo_rag


def executar_rag(pergunta: str, session_id: str, top_k: int = None):
    historico_formatado = memory.formatar_historico(session_id)

    grafo = _obter_grafo()

    resultado = grafo.invoke(
        {
            "pergunta": pergunta,
            "session_id": session_id,
            "top_k": top_k,
            "historico_formatado": historico_formatado,
            "documentos_recuperados": [],
            "score_maximo": 0.0,
            "query_busca": pergunta,
        }
    )

    memory.adicionar_turno(session_id, "usuario", pergunta)
    memory.adicionar_turno(session_id, "assistente", resultado["resposta"])

    return resultado