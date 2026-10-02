import json
import logging
from dataclasses import dataclass

from groq import Groq

from app import config

logger = logging.getLogger("chatbot_filmes.llm")

_cliente_groq = None

_uso = {"chamadas": 0, "prompt_tokens": 0, "completion_tokens": 0}

_PREFIXOS_META_RACIOCINIO = (
    "com base no historico",
    "com base no contexto",
    "com base na conversa",
    "analisando o contexto",
    "analisando o historico",
    "portanto, a resposta",
    "de acordo com o historico",
)


@dataclass
class RespostaLLM:
    texto: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int


def obter_cliente():
    global _cliente_groq

    if _cliente_groq is None:
        config.validar_configuracao()
        _cliente_groq = Groq(api_key=config.GROQ_API_KEY)

    return _cliente_groq


def remover_bloco_pensamento(texto: str) -> str:
    if "<think>" in texto:
        if "</think>" in texto:
            texto = texto.split("</think>", 1)[1]
        else:
            texto = texto.split("<think>", 1)[0]

    return _remover_paragrafo_de_meta_raciocinio(texto.strip())


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


def chamar_llm(
    mensagens: list,
    temperature: float = 0,
    max_tokens: int = 600,
    formato_json: bool = False,
) -> RespostaLLM:
    cliente = obter_cliente()

    parametros = {
        "model": config.GROQ_MODEL,
        "messages": mensagens,
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
        "reasoning_effort": "none",
    }

    if formato_json:
        parametros["response_format"] = {"type": "json_object"}

    resultado = cliente.chat.completions.create(**parametros)

    escolha = resultado.choices[0]
    uso = getattr(resultado, "usage", None)

    prompt_tokens = getattr(uso, "prompt_tokens", 0) or 0
    completion_tokens = getattr(uso, "completion_tokens", 0) or 0

    _uso["chamadas"] += 1
    _uso["prompt_tokens"] += prompt_tokens
    _uso["completion_tokens"] += completion_tokens

    return RespostaLLM(
        texto=remover_bloco_pensamento(escolha.message.content or ""),
        finish_reason=str(escolha.finish_reason),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def resetar_uso() -> None:
    for chave in _uso:
        _uso[chave] = 0


def obter_uso() -> dict:
    return dict(_uso)


def extrair_json(texto: str) -> dict:
    inicio = texto.find("{")
    fim = texto.rfind("}")

    if inicio == -1 or fim == -1 or fim < inicio:
        raise ValueError("a resposta nao contem um objeto JSON")

    dados = json.loads(texto[inicio : fim + 1])

    if not isinstance(dados, dict):
        raise ValueError("o JSON retornado nao e um objeto")

    return dados