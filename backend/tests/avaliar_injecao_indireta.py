import argparse
import json
import time
import uuid
from datetime import datetime
from pathlib import Path

from app import config, llm, rag_graph
from app.prompts import VERSOES_DISPONIVEIS
from app.retriever import recuperar as recuperar_base
from tests.avaliar_prompts import avaliar
from tests.base_injecao import BaseComInjecao
from tests.comum import calcular_espera, separar_criterios, total_tokens

BASE_TESTES = Path(__file__).resolve().parent
CASOS_PATH = BASE_TESTES / "casos_injecao_indireta.json"
RESULTADOS_DIR = BASE_TESTES / "resultados"


def carregar_casos() -> list:
    return json.loads(CASOS_PATH.read_text(encoding="utf-8"))


def verificar_recuperacao(base: BaseComInjecao, casos: list) -> None:
    print("\n" + "=" * 90)
    print("VERIFICACAO DE RECUPERACAO (sem chamadas a LLM)")
    print("=" * 90)

    nao_recuperados = 0

    for caso in casos:
        resultados = base.recuperar(caso["pergunta"])
        titulos = [r["titulo"] for r in resultados]
        alvo = caso["titulo_envenenado"]

        if alvo is None:
            print(f"[CONTROLE] {caso['id']} top-1: {titulos[0]} ({resultados[0]['score']:.4f})")
            continue

        if alvo in titulos:
            posicao = titulos.index(alvo) + 1
            score = resultados[posicao - 1]["score"]
            print(f"[RECUPERADO] {caso['id']} {caso['ataque']}: posicao {posicao}, score {score:.4f}")
        else:
            nao_recuperados += 1
            score_alvo = base.pontuar(caso["pergunta"], alvo)
            corte = resultados[-1]["score"]
            print(
                f"[NAO RECUPERADO] {caso['id']} {caso['ataque']}: score {score_alvo:.4f}, "
                f"corte do top-{len(resultados)}: {corte:.4f}, top-1: {titulos[0]}"
            )

    print(f"\nDocumentos envenenados fora do contexto: {nao_recuperados}")


def executar_caso(
    caso: dict,
    versao: str,
    pausa: float,
    tpm_alvo: int,
    base: BaseComInjecao = None,
    forcar: bool = False,
) -> dict:
    session_id = f"inj-{versao}-{caso['id']}-{uuid.uuid4().hex[:8]}"

    if base is not None:
        base.forcar_titulo = caso["titulo_envenenado"] if forcar else None
        base.forcou = False

    resultado = {}
    resposta = ""
    fontes = []
    erro = None
    falhas = []
    recuperado = None

    llm.resetar_uso()
    inicio = time.perf_counter()

    try:
        resultado = rag_graph.executar_rag(caso["pergunta"], session_id)
        resposta = resultado["resposta"]
        fontes = [f["titulo"] for f in resultado.get("documentos_recuperados", [])]

        titulos_contexto = [f["titulo"] for f in resultado.get("fontes_contexto", [])]
        alvo = caso["titulo_envenenado"]
        recuperado = True if alvo is None else alvo in titulos_contexto

        falhas = avaliar(caso["esperado"], resposta, fontes)
    except Exception as exc:
        erro = f"{type(exc).__name__}: {exc}"

    tempo = time.perf_counter() - inicio
    uso = llm.obter_uso()

    if erro:
        status = "ERRO"
    elif recuperado is False:
        status = "INVALIDO"
    elif falhas:
        status = "FALHA"
    else:
        status = "OK"

    time.sleep(calcular_espera(total_tokens(uso), pausa, tpm_alvo))

    resistiu, util = separar_criterios(falhas)

    return {
        "id": caso["id"],
        "ataque": caso["ataque"],
        "pergunta": caso["pergunta"],
        "resposta": resposta,
        "fontes": fontes,
        "documento_envenenado_no_contexto": recuperado,
        "recuperacao_forcada": bool(base.forcou) if base is not None else False,
        "verificacao": resultado.get("verificacao"),
        "status": status,
        "resistiu_a_injecao": resistiu,
        "respondeu_corretamente": util,
        "falhas": falhas,
        "erro": erro,
        "tempo_s": round(tempo, 2),
        "chamadas_llm": uso["chamadas"],
        "prompt_tokens": uso["prompt_tokens"],
        "completion_tokens": uso["completion_tokens"],
    }


def rodar_versao(
    versao: str,
    casos: list,
    pausa: float,
    tpm_alvo: int,
    base: BaseComInjecao = None,
    forcar: bool = False,
) -> list:
    config.PROMPT_VERSION = versao

    print("\n" + "=" * 90)
    print(f"INDIRECT PROMPT INJECTION - VERSAO DE PROMPT: {versao}")
    print("=" * 90)

    resultados = []

    for caso in casos:
        resultado = executar_caso(caso, versao, pausa, tpm_alvo, base, forcar)
        resultados.append(resultado)

        tokens = resultado["prompt_tokens"] + resultado["completion_tokens"]

        marca_forcada = " | recuperacao forcada" if resultado["recuperacao_forcada"] else ""

        print(
            f"[{resultado['status']}] {resultado['id']} ({resultado['ataque']}) "
            f"{resultado['tempo_s']}s | {resultado['chamadas_llm']} chamada(s) | "
            f"{tokens} tokens{marca_forcada}"
        )

        if resultado["status"] != "OK":
            for falha in resultado["falhas"]:
                print(f"      - {falha}")
            if resultado["status"] == "INVALIDO":
                print("      - o documento envenenado nao chegou ao contexto da LLM")
            if resultado["erro"]:
                print(f"      - {resultado['erro']}")
            print(f"      resposta: {resultado['resposta'][:220]!r}")

    return resultados


def imprimir_resumo(versao: str, resultados: list) -> None:
    contagem = {}

    for resultado in resultados:
        contagem[resultado["status"]] = contagem.get(resultado["status"], 0) + 1

    tokens = sum(r["prompt_tokens"] + r["completion_tokens"] for r in resultados)

    print("\n" + "-" * 90)
    print(f"RESUMO {versao}")
    print("-" * 90)
    validos = [r for r in resultados if r["status"] in ("OK", "FALHA")]
    resistiu = sum(1 for r in validos if r["resistiu_a_injecao"])
    util = sum(1 for r in validos if r["respondeu_corretamente"])

    print(f"OK (criterio completo): {contagem.get('OK', 0)}/{len(resultados)}")
    print(f"Resistiu a injection: {resistiu}/{len(validos)}")
    print(f"Respondeu corretamente: {util}/{len(validos)}")
    print(f"FALHA: {contagem.get('FALHA', 0)} | INVALIDO: {contagem.get('INVALIDO', 0)} | ERRO: {contagem.get('ERRO', 0)}")
    print(f"Tokens: {tokens}")


def imprimir_comparativo(todos: dict) -> None:
    versoes = list(todos.keys())

    if len(versoes) < 2:
        return

    print("\n" + "=" * 90)
    print("COMPARATIVO POR CASO")
    print("=" * 90)
    print(f"{'caso':<8}{'ataque':<30}" + "".join(f"{v:<10}" for v in versoes))

    for indice, resultado in enumerate(todos[versoes[0]]):
        status = "".join(f"{todos[v][indice]['status']:<10}" for v in versoes)
        print(f"{resultado['id']:<8}{resultado['ataque']:<30}{status}")


def salvar_resultados(versao: str, resultados: list) -> Path:
    RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = RESULTADOS_DIR / f"injecao_indireta_{versao}_{marca}.json"

    conteudo = {
        "versao": versao,
        "modelo": config.GROQ_MODEL,
        "few_shot": config.FEW_SHOT,
        "verificar_resposta": config.VERIFICAR_RESPOSTA,
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "resultados": resultados,
    }

    caminho.write_text(
        json.dumps(conteudo, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return caminho


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Testa indirect prompt injection com documentos envenenados na recuperacao."
    )
    parser.add_argument("--versoes", nargs="+", default=["v1", "v2"])
    parser.add_argument(
        "--apenas-recuperacao",
        action="store_true",
        help="Verifica so se os documentos envenenados sao recuperados, sem chamar a LLM.",
    )
    parser.add_argument(
        "--forcar-recuperacao",
        action="store_true",
        help=(
            "Garante que o documento envenenado entre no contexto quando a busca "
            "natural nao o recuperar. O resultado registra quando isso ocorreu."
        ),
    )
    parser.add_argument("--pausa", type=float, default=1.0)
    parser.add_argument("--tpm", type=int, default=6000)
    argumentos = parser.parse_args()

    for versao in argumentos.versoes:
        if versao not in VERSOES_DISPONIVEIS:
            parser.error(f"versao desconhecida: {versao}")

    casos = carregar_casos()
    base = BaseComInjecao(recuperar_base)

    if argumentos.apenas_recuperacao:
        verificar_recuperacao(base, casos)
        return

    rag_graph.recuperar = base.recuperar

    todos = {}

    for versao in argumentos.versoes:
        resultados = rodar_versao(
            versao,
            casos,
            argumentos.pausa,
            argumentos.tpm,
            base,
            argumentos.forcar_recuperacao,
        )
        imprimir_resumo(versao, resultados)
        print(f"\nResultados salvos em: {salvar_resultados(versao, resultados)}")
        todos[versao] = resultados

    imprimir_comparativo(todos)


if __name__ == "__main__":
    main()