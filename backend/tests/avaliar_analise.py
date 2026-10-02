import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from app import config, llm
from app.analise import interpretar_analise
from app.prompts import v2
from tests.comum import calcular_espera, normalizar

BASE_TESTES = Path(__file__).resolve().parent
CASOS_PATH = BASE_TESTES / "casos_analise.json"
RESULTADOS_DIR = BASE_TESTES / "resultados"

VARIANTES = {"zero_shot": False, "few_shot": True}


def carregar_casos(grupos):
    casos = json.loads(CASOS_PATH.read_text(encoding="utf-8"))

    if grupos:
        casos = [caso for caso in casos if caso["grupo"] in grupos]

    return casos


def avaliar(esperado: dict, analise) -> list:
    falhas = []

    if analise.categoria not in esperado["categorias"]:
        falhas.append(
            f"categoria {analise.categoria}, esperado {esperado['categorias']}"
        )

    texto = normalizar(analise.pergunta_autonoma)

    if analise.categoria == "FILMES":
        for termo in esperado.get("contem_todos", []):
            if normalizar(termo) not in texto:
                falhas.append(f"pergunta_autonoma sem o termo: {termo}")

        for termo in esperado.get("nao_contem", []):
            if normalizar(termo) in texto:
                falhas.append(f"pergunta_autonoma contem termo proibido: {termo}")

    manipulacao = esperado.get("manipulacao")

    if manipulacao is not None and analise.manipulacao != manipulacao:
        falhas.append(
            f"manipulacao {analise.manipulacao}, esperado {manipulacao}"
        )

    return falhas


def executar_caso(caso: dict, few_shot: bool, pausa: float, tpm_alvo: int) -> dict:
    mensagens = v2.montar_mensagens_analise(
        caso["mensagem"],
        caso.get("historico", ""),
        few_shot=few_shot,
    )

    saida = ""
    tokens = 0
    erro = None
    falhas = []
    analise_dict = None

    inicio = time.perf_counter()

    try:
        resposta = llm.chamar_llm(
            mensagens,
            temperature=0,
            max_tokens=300,
            formato_json=True,
        )
        saida = resposta.texto
        tokens = resposta.prompt_tokens + resposta.completion_tokens
    except Exception as exc:
        erro = f"{type(exc).__name__}: {exc}"

    tempo = time.perf_counter() - inicio

    if erro:
        status = "ERRO"
        falhas = ["erro de execucao"]
    else:
        try:
            analise = interpretar_analise(saida)
        except Exception as exc:
            status = "ERRO_FORMATO"
            erro = f"{type(exc).__name__}: {exc}"
            falhas = ["saida fora do contrato"]
        else:
            analise_dict = analise.model_dump()
            falhas = avaliar(caso["esperado"], analise)
            status = "FALHA" if falhas else "OK"

    time.sleep(calcular_espera(tokens, pausa, tpm_alvo))

    return {
        "id": caso["id"],
        "grupo": caso["grupo"],
        "mensagem": caso["mensagem"],
        "saida_bruta": saida,
        "analise": analise_dict,
        "status": status,
        "falhas": falhas,
        "erro": erro,
        "tempo_s": round(tempo, 2),
        "tokens": tokens,
    }


def rodar_variante(nome: str, casos: list, pausa: float, tpm_alvo: int) -> list:
    few_shot = VARIANTES[nome]

    print("\n" + "=" * 90)
    print(f"VARIANTE: {nome}")
    print("=" * 90)

    resultados = []

    for caso in casos:
        resultado = executar_caso(caso, few_shot, pausa, tpm_alvo)
        resultados.append(resultado)

        print(
            f"[{resultado['status']}] {resultado['id']} ({resultado['grupo']}) "
            f"{resultado['tempo_s']}s | {resultado['tokens']} tokens"
        )

        if resultado["status"] != "OK":
            for falha in resultado["falhas"]:
                print(f"      - {falha}")
            if resultado["erro"]:
                print(f"      - {resultado['erro']}")
            print(f"      saida: {resultado['saida_bruta'][:220]!r}")

    return resultados


def imprimir_resumo(nome: str, resultados: list) -> None:
    por_grupo = {}

    for resultado in resultados:
        contagem = por_grupo.setdefault(resultado["grupo"], [0, 0])
        contagem[1] += 1
        if resultado["status"] == "OK":
            contagem[0] += 1

    print("\n" + "-" * 90)
    print(f"RESUMO {nome}")
    print("-" * 90)

    for grupo, (ok, total) in por_grupo.items():
        print(f"{grupo:<22} {ok}/{total}")

    total_ok = sum(1 for r in resultados if r["status"] == "OK")
    formato = sum(1 for r in resultados if r["status"] == "ERRO_FORMATO")
    tokens = sum(r["tokens"] for r in resultados)

    print(f"{'TOTAL':<22} {total_ok}/{len(resultados)}")
    print(f"Saidas fora do contrato: {formato}")
    print(f"Tokens: {tokens} (media {tokens // max(len(resultados), 1)} por caso)")


def imprimir_comparativo(todos: dict) -> None:
    nomes = list(todos.keys())

    if len(nomes) < 2:
        return

    print("\n" + "=" * 90)
    print("COMPARATIVO POR CASO")
    print("=" * 90)
    print(f"{'caso':<8}{'grupo':<22}" + "".join(f"{n:<14}" for n in nomes))

    for indice, resultado in enumerate(todos[nomes[0]]):
        status = "".join(f"{todos[n][indice]['status']:<14}" for n in nomes)
        print(f"{resultado['id']:<8}{resultado['grupo']:<22}{status}")


def salvar(nome: str, resultados: list) -> Path:
    RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = RESULTADOS_DIR / f"analise_{nome}_{marca}.json"

    conteudo = {
        "variante": nome,
        "modelo": config.GROQ_MODEL,
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
        description="Compara variantes zero-shot e few-shot do prompt de analise."
    )
    parser.add_argument(
        "--variantes",
        nargs="+",
        default=list(VARIANTES.keys()),
        choices=list(VARIANTES.keys()),
    )
    parser.add_argument("--grupos", nargs="*", default=None)
    parser.add_argument("--pausa", type=float, default=1.0)
    parser.add_argument("--tpm", type=int, default=6000)
    argumentos = parser.parse_args()

    casos = carregar_casos(argumentos.grupos)

    if not casos:
        parser.error("nenhum caso selecionado")

    todos = {}

    for nome in argumentos.variantes:
        resultados = rodar_variante(nome, casos, argumentos.pausa, argumentos.tpm)
        imprimir_resumo(nome, resultados)
        print(f"\nResultados salvos em: {salvar(nome, resultados)}")
        todos[nome] = resultados

    imprimir_comparativo(todos)


if __name__ == "__main__":
    main()