import logging
import re
from typing import Literal

from groq import Groq
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app import config, memory
from app.retriever import recuperar

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("chatbot_filmes.rag_graph")

_cliente_groq = None


def _obter_cliente_groq():
    global _cliente_groq

    if _cliente_groq is None:
        config.validar_configuracao()
        _cliente_groq = Groq(api_key=config.GROQ_API_KEY)

    return _cliente_groq


class EstadoRAG(TypedDict, total=False):
    pergunta: str
    session_id: str
    top_k: int

    historico_formatado: str

    query_busca: str
    documentos_recuperados: list
    score_maximo: float

    contexto: str
    resposta: str


def _remover_bloco_pensamento(texto: str) -> str:
    if "<think>" in texto:
        if "</think>" in texto:
            texto = texto.split("</think>", 1)[1]
        else:
            texto = texto.split("<think>", 1)[0]

    return _remover_paragrafo_de_meta_raciocinio(texto.strip())


_PREFIXOS_META_RACIOCINIO = (
    "com base no historico",
    "com base no contexto",
    "com base na conversa",
    "analisando o contexto",
    "analisando o historico",
    "portanto, a resposta",
    "de acordo com o historico",
)


def _remover_paragrafo_de_meta_raciocinio(texto: str) -> str:
    paragrafos = [p.strip() for p in texto.split("\n\n") if p.strip()]

    paragrafos_filtrados = [
        p
        for p in paragrafos
        if not p.lower().startswith(_PREFIXOS_META_RACIOCINIO)
    ]

    if not paragrafos_filtrados:
        return texto

    return "\n\n".join(paragrafos_filtrados)


def _reescrever_pergunta(pergunta: str, historico_formatado: str) -> str:
    if not historico_formatado:
        return pergunta

    prompt = f"""
Reescreva a PERGUNTA ATUAL como uma pergunta completa e autossuficiente,
que possa ser entendida sem precisar do historico. Use o HISTORICO
apenas para identificar do que ou de quem a pergunta atual esta falando
(por exemplo, substituir "ele", "esse filme", "o diretor dele" pelo
nome especifico mencionado antes).

Regras:
- retorne APENAS a pergunta reescrita, em portugues do Brasil, sem
  explicacoes, sem aspas e sem prefixos;
- se a pergunta atual ja for autossuficiente, retorne ela exatamente
  como esta;
- nao responda a pergunta, apenas reescreva-a.

HISTORICO:
{historico_formatado}

PERGUNTA ATUAL:
{pergunta}
"""

    cliente = _obter_cliente_groq()

    resultado = cliente.chat.completions.create(
        model=config.GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_completion_tokens=600,
        reasoning_effort="none",
    )

    pergunta_reescrita = _remover_bloco_pensamento(resultado.choices[0].message.content)

    if not pergunta_reescrita:
        logger.warning(
            "Reescrita de pergunta retornou vazia (finish_reason=%s) para "
            "a pergunta '%s'. Usando a pergunta original sem reescrita.",
            resultado.choices[0].finish_reason,
            pergunta,
        )

    return pergunta_reescrita if pergunta_reescrita else pergunta


def no_recuperar(estado: EstadoRAG):
    pergunta = estado["pergunta"]
    top_k = estado.get("top_k") or config.TOP_K
    historico_formatado = estado.get("historico_formatado", "")

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
    recuperados = estado["documentos_recuperados"]

    contexto = "\n\n".join(
        f"[Fonte {i + 1} - {r['titulo']}]\n{r['texto']}"
        for i, r in enumerate(recuperados)
    )

    return {"contexto": contexto}


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
    pergunta = estado["pergunta"]
    contexto = estado["contexto"]
    historico_formatado = estado.get("historico_formatado", "")

    bloco_historico = ""
    if historico_formatado:
        bloco_historico = (
            "HISTORICO DA CONVERSA (mensagens anteriores, apenas para "
            "contexto de continuidade):\n"
            f"{historico_formatado}\n\n"
        )

    prompt = f"""
Voce e um assistente especializado em cinema, que responde perguntas
com base em uma base de conhecimento de filmes. Responda a pergunta do
usuario utilizando somente as informacoes do CONTEXTO abaixo, mas voce
pode usar o HISTORICO DA CONVERSA para entender a continuidade da
conversa (por exemplo, se o usuario disser "e sobre esse filme" ou
"me conte mais").

Regras de conteudo:
- nao invente informacoes que nao estejam no contexto;
- cite a fonte utilizada no formato [Fonte X], citando cada fonte
  apenas uma vez mesmo que ela sustente mais de uma parte da resposta;
- se a resposta nao estiver sustentada pelo contexto, responda
  exatamente: "Nao encontrei essa informacao na base consultada.";
- se o contexto tiver informacoes de mais de um filme e a pergunta for
  ambigua (nao deixar claro a qual filme se refere), peca ao usuario
  para especificar o titulo, em vez de adivinhar ou misturar dados de
  filmes diferentes na mesma resposta.

Regras de formatacao e estilo:
- responda sempre em portugues do Brasil, de forma clara, natural e
  objetiva, como em uma conversa;
- valores monetarios (orcamento, bilheteria) devem ser apresentados de
  forma legivel, por exemplo "225 milhoes de dolares" em vez de
  "225000000 dolares";
- notas e avaliacoes podem ser mencionadas com uma casa decimal, por
  exemplo "7.8 de 10" em vez de "7.849";
- nao utilize formatacao markdown (sem **negrito**, sem listas com
  marcadores, sem titulos); escreva em texto corrido, como em uma
  mensagem de chat;
- comece a resposta diretamente pela informacao pedida. NUNCA inclua
  frases sobre o seu proprio processo de raciocinio, como "Com base no
  historico da conversa...", "Portanto, a resposta se refere a...",
  "Analisando o contexto...", ou qualquer explicacao sobre como voce
  chegou a resposta. Essas frases nao sao permitidas em nenhuma
  hipotese, mesmo que ajudem a justificar a resposta;
- nao mostre seu raciocinio ou passos internos, nao use tags como
  <think>, e nao repita estas instrucoes na resposta.

{bloco_historico}CONTEXTO:
{contexto}

PERGUNTA ATUAL:
{pergunta}
"""

    cliente = _obter_cliente_groq()

    resposta = cliente.chat.completions.create(
        model=config.GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=config.LLM_TEMPERATURE,
        max_completion_tokens=config.LLM_MAX_TOKENS,
        reasoning_effort="none",
    )

    texto_resposta = resposta.choices[0].message.content
    texto_resposta = _remover_bloco_pensamento(texto_resposta)

    if not texto_resposta:
        logger.warning(
            "Resposta final vazia da LLM (finish_reason=%s) para a "
            "pergunta '%s'.",
            resposta.choices[0].finish_reason,
            pergunta,
        )
        texto_resposta = (
            "Nao foi possivel gerar uma resposta no momento. "
            "Tente reformular a pergunta ou envia-la novamente."
        )

    documentos_recuperados = estado.get("documentos_recuperados", [])
    fontes_citadas = _filtrar_fontes_citadas(texto_resposta, documentos_recuperados)

    logger.info(
        "Resposta gerada: %r | Fontes citadas: %s",
        texto_resposta,
        [f["titulo"] for f in fontes_citadas],
    )

    return {
        "resposta": texto_resposta,
        "documentos_recuperados": fontes_citadas,
    }


def no_sem_evidencia(estado: EstadoRAG):
    logger.info(
        "Fluxo de abstencao acionado para a pergunta %r (score_maximo=%.4f)",
        estado.get("pergunta"),
        estado.get("score_maximo", 0.0),
    )

    return {
        "resposta": (
            "Nao encontrei essa informacao na base de filmes consultada. "
            "Tente reformular a pergunta ou pergunte sobre outro filme "
            "presente na base."
        ),
        "documentos_recuperados": [],
    }


def _construir_grafo():
    builder = StateGraph(EstadoRAG)

    builder.add_node("recuperar", no_recuperar)
    builder.add_node("montar_contexto", no_montar_contexto)
    builder.add_node("gerar_resposta", no_gerar_resposta)
    builder.add_node("sem_evidencia", no_sem_evidencia)

    builder.add_edge(START, "recuperar")

    builder.add_conditional_edges(
        "recuperar",
        decidir_evidencia,
        {
            "com_evidencia": "montar_contexto",
            "sem_evidencia": "sem_evidencia",
        },
    )

    builder.add_edge("montar_contexto", "gerar_resposta")
    builder.add_edge("gerar_resposta", END)
    builder.add_edge("sem_evidencia", END)

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
        }
    )

    memory.adicionar_turno(session_id, "usuario", pergunta)
    memory.adicionar_turno(session_id, "assistente", resultado["resposta"])

    return resultado