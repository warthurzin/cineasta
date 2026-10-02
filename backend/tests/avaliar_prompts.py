import argparse
import json
import time
import uuid
from datetime import datetime
from pathlib import Path

from app import config, llm
from app.prompts import VERSOES_DISPONIVEIS
from app.rag_graph import executar_rag
from tests.comum import calcular_espera, normalizar, total_tokens

BASE_TESTES = Path(__file__).resolve().parent
CASOS_PATH = BASE_TESTES / "casos_teste.json"
RESULTADOS_DIR = BASE_TESTES / "resultados"

MARCADORES_ABSTENCAO = ("nao encontrei", "nao foi possivel")

MARCADORES_ESCLARECIMENTO = (
    "especific",
    "qual filme",
    "qual dos",
    "qual e o titulo",
    "informe o titulo",
    "sobre qual",
    "a qual filme",
    "de qual filme",
    "qual titulo",
)


def carregar_casos(categorias):
    casos = json.loads(CASOS_PATH.read_text(encoding="utf-8"))

    if categorias:
        casos = [caso for caso in casos if caso["categoria"] in categorias]

    return casos


def avaliar(esperado: dict, resposta: str, fontes: list) -> list:
    texto = normalizar(resposta)
    falhas = []

    tipo = esperado.get("tipo", "responder")
    abstencao = any(marcador in texto for marcador in MARCADORES_ABSTENCAO)
    esclarecimento = any(marcador in texto for marcador in MARCADORES_ESCLARECIMENTO)

    if tipo == "abster" and not abstencao:
        falhas.append("deveria abster-se de responder")

    if tipo == "responder" and abstencao:
        falhas.append("absteve-se indevidamente")

    if tipo == "esclarecer" and not esclarecimento:
        falhas.append("deveria pedir esclarecimento sobre o filme")

    termos = esperado.get("contem_algum", [])
    if termos and not any(normalizar(termo) in texto for termo in termos):
        falhas.append(f"nenhum termo esperado presente: {termos}")

    ausentes = [
        termo
        for termo in esperado.get("contem_todos", [])
        if normalizar(termo) not in texto
    ]
    if ausentes:
        falhas.append(f"termos esperados ausentes: {ausentes}")

    for termo in esperado.get("nao_contem", []):
        if normalizar(termo) in texto:
            falhas.append(f"contem termo proibido: {termo}")

    if esperado.get("exige_fonte") and not fontes:
        falhas.append("nenhuma fonte citada")

    if esperado.get("sem_fontes_duplicadas") and len(fontes) != len(set(fontes)):
        falhas.append(f"fontes duplicadas: {len(fontes)} itens, {len(set(fontes))} distintos")

    return falhas


def executar_caso(caso: dict, versao: str, pausa: float, tpm_alvo: int) -> dict:
    session_id = f"aval-{versao}-{caso['id']}-{uuid.uuid4().hex[:8]}"

    resultado = {}
    resposta = ""
    fontes = []
    erro = None
    tempo = 0.0

    llm.resetar_uso()

    try:
        for pergunta in caso["turnos"]:
            antes = total_tokens(llm.obter_uso())
            inicio = time.perf_counter()

            resultado = executar_rag(pergunta, session_id)

            tempo += time.perf_counter() - inicio
            gastos = total_tokens(llm.obter_uso()) - antes
            time.sleep(calcular_espera(gastos, pausa, tpm_alvo))

        resposta = resultado["resposta"]
        fontes = [f["titulo"] for f in resultado.get("documentos_recuperados", [])]
        falhas = avaliar(caso["esperado"], resposta, fontes)
    except Exception as exc:
        erro = f"{type(exc).__name__}: {exc}"
        falhas = ["erro de execucao"]

    uso = llm.obter_uso()

    if erro:
        status = "ERRO"
    elif falhas:
        status = "FALHA"
    else:
        status = "OK"

    return {
        "id": caso["id"],
        "categoria": caso["categoria"],
        "turnos": caso["turnos"],
        "resposta": resposta,
        "fontes": fontes,
        "query_busca": resultado.get("query_busca"),
        "score_maximo": resultado.get("score_maximo"),
        "status": status,
        "falhas": falhas,
        "erro": erro,
        "tempo_s": round(tempo, 2),
        "chamadas_llm": uso["chamadas"],
        "prompt_tokens": uso["prompt_tokens"],
        "completion_tokens": uso["completion_tokens"],
    }


def rodar_versao(versao: str, casos: list, pausa: float, tpm_alvo: int) -> list:
    config.PROMPT_VERSION = versao

    print("\n" + "=" * 90)
    print(f"VERSAO DE PROMPT: {versao}")
    print("=" * 90)

    resultados = []

    for caso in casos:
        resultado = executar_caso(caso, versao, pausa, tpm_alvo)
        resultados.append(resultado)

        tokens = resultado["prompt_tokens"] + resultado["completion_tokens"]

        print(
            f"[{resultado['status']}] {resultado['id']} ({resultado['categoria']}) "
            f"{resultado['tempo_s']}s | {resultado['chamadas_llm']} chamada(s) | {tokens} tokens"
        )

        if resultado["status"] != "OK":
            for falha in resultado["falhas"]:
                print(f"      - {falha}")
            if resultado["erro"]:
                print(f"      - {resultado['erro']}")
            print(f"      resposta: {resultado['resposta'][:200]!r}")

    return resultados


def imprimir_resumo(versao: str, resultados: list) -> None:
    por_categoria = {}

    for resultado in resultados:
        contagem = por_categoria.setdefault(resultado["categoria"], [0, 0])
        contagem[1] += 1
        if resultado["status"] == "OK":
            contagem[0] += 1

    print("\n" + "-" * 90)
    print(f"RESUMO {versao}")
    print("-" * 90)

    for categoria, (ok, total) in por_categoria.items():
        print(f"{categoria:<22} {ok}/{total}")

    total_ok = sum(1 for r in resultados if r["status"] == "OK")
    chamadas = sum(r["chamadas_llm"] for r in resultados)
    prompt_tokens = sum(r["prompt_tokens"] for r in resultados)
    completion_tokens = sum(r["completion_tokens"] for r in resultados)

    print(f"{'TOTAL':<22} {total_ok}/{len(resultados)}")
    print(f"Chamadas a LLM: {chamadas}")
    print(f"Tokens de entrada: {prompt_tokens} | Tokens de saida: {completion_tokens}")


def imprimir_comparativo(todos: dict) -> None:
    versoes = list(todos.keys())

    if len(versoes) < 2:
        return

    print("\n" + "=" * 90)
    print("COMPARATIVO POR CASO")
    print("=" * 90)
    print(f"{'caso':<8}{'categoria':<22}" + "".join(f"{v:<10}" for v in versoes))

    ids = [r["id"] for r in todos[versoes[0]]]

    for indice, caso_id in enumerate(ids):
        categoria = todos[versoes[0]][indice]["categoria"]
        status = "".join(f"{todos[v][indice]['status']:<10}" for v in versoes)
        print(f"{caso_id:<8}{categoria:<22}{status}")


def salvar_resultados(versao: str, resultados: list) -> Path:
    RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = RESULTADOS_DIR / f"{versao}_{marca}.json"

    conteudo = {
        "versao": versao,
        "modelo": config.GROQ_MODEL,
        "top_k": config.TOP_K,
        "limiar_evidencia": config.LIMIAR_EVIDENCIA,
        "temperatura": config.LLM_TEMPERATURE,
        "max_tokens": config.LLM_MAX_TOKENS,
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
        description="Executa o conjunto de testes para uma ou mais versoes de prompt."
    )
    parser.add_argument(
        "--versoes",
        nargs="+",
        default=["v1"],
        help=f"Versoes de prompt a executar. Disponiveis: {', '.join(VERSOES_DISPONIVEIS)}.",
    )
    parser.add_argument(
        "--categorias",
        nargs="*",
        default=None,
        help="Restringe a execucao a categorias especificas.",
    )
    parser.add_argument(
        "--pausa",
        type=float,
        default=1.0,
        help="Espera minima, em segundos, apos cada turno.",
    )
    parser.add_argument(
        "--tpm",
        type=int,
        default=6000,
        help=(
            "Tokens por minuto alvo. Apos cada turno o script espera o tempo "
            "necessario para nao exceder esse ritmo. Use 0 para desativar."
        ),
    )
    argumentos = parser.parse_args()

    for versao in argumentos.versoes:
        if versao not in VERSOES_DISPONIVEIS:
            parser.error(f"versao desconhecida: {versao}")

    casos = carregar_casos(argumentos.categorias)

    if not casos:
        parser.error("nenhum caso de teste selecionado")

    todos = {}

    for versao in argumentos.versoes:
        resultados = rodar_versao(versao, casos, argumentos.pausa, argumentos.tpm)
        imprimir_resumo(versao, resultados)
        caminho = salvar_resultados(versao, resultados)
        print(f"\nResultados salvos em: {caminho}")
        todos[versao] = resultados

    imprimir_comparativo(todos)


if __name__ == "__main__":
    main()