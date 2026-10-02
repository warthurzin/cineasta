import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from app import config, llm
from app.prompts import v2
from app.verificacao import interpretar_verificacao
from tests.comum import calcular_espera

BASE_TESTES = Path(__file__).resolve().parent
CASOS_PATH = BASE_TESTES / "casos_verificacao.json"
RESULTADOS_DIR = BASE_TESTES / "resultados"


def executar_caso(caso: dict, pausa: float, tpm_alvo: int) -> dict:
    mensagens = v2.montar_mensagens_verificacao(
        caso["pergunta"],
        caso["resposta"],
        caso["fontes"],
    )

    saida = ""
    tokens = 0
    erro = None
    suportada = None

    inicio = time.perf_counter()

    try:
        resposta = llm.chamar_llm(
            mensagens,
            temperature=0,
            max_tokens=200,
            formato_json=True,
        )
        saida = resposta.texto
        tokens = resposta.prompt_tokens + resposta.completion_tokens
    except Exception as exc:
        erro = f"{type(exc).__name__}: {exc}"

    tempo = time.perf_counter() - inicio

    if erro:
        status = "ERRO"
    else:
        try:
            verificacao = interpretar_verificacao(saida)
        except Exception as exc:
            status = "ERRO_FORMATO"
            erro = f"{type(exc).__name__}: {exc}"
        else:
            suportada = verificacao.suportada
            status = "OK" if suportada == caso["esperado_suportada"] else "FALHA"

    time.sleep(calcular_espera(tokens, pausa, tpm_alvo))

    return {
        "id": caso["id"],
        "tipo": caso["tipo"],
        "esperado_suportada": caso["esperado_suportada"],
        "suportada": suportada,
        "saida_bruta": saida,
        "status": status,
        "erro": erro,
        "tempo_s": round(tempo, 2),
        "tokens": tokens,
    }


def imprimir_resumo(resultados: list) -> None:
    ok = sum(1 for r in resultados if r["status"] == "OK")
    formato = sum(1 for r in resultados if r["status"] == "ERRO_FORMATO")
    erros = sum(1 for r in resultados if r["status"] == "ERRO")

    aceitou_errada = [
        r["id"]
        for r in resultados
        if r["status"] == "FALHA" and r["suportada"] and not r["esperado_suportada"]
    ]
    rejeitou_correta = [
        r["id"]
        for r in resultados
        if r["status"] == "FALHA" and not r["suportada"] and r["esperado_suportada"]
    ]

    tokens = sum(r["tokens"] for r in resultados)

    print("\n" + "-" * 90)
    print("RESUMO verificador")
    print("-" * 90)
    print(f"Acertos: {ok}/{len(resultados)}")
    print(f"Respostas incorretas aceitas (falso positivo): {aceitou_errada}")
    print(f"Respostas corretas rejeitadas (falso negativo): {rejeitou_correta}")
    print(f"Saidas fora do contrato: {formato} | Erros de API: {erros}")
    print(f"Tokens: {tokens} (media {tokens // max(len(resultados), 1)} por caso)")


def salvar(resultados: list) -> Path:
    RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = RESULTADOS_DIR / f"verificador_{marca}.json"

    conteudo = {
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
        description="Avalia o prompt de verificacao de respostas isoladamente."
    )
    parser.add_argument("--pausa", type=float, default=1.0)
    parser.add_argument("--tpm", type=int, default=6000)
    argumentos = parser.parse_args()

    casos = json.loads(CASOS_PATH.read_text(encoding="utf-8"))

    print("\n" + "=" * 90)
    print("VERIFICADOR DE RESPOSTAS")
    print("=" * 90)

    resultados = []

    for caso in casos:
        resultado = executar_caso(caso, argumentos.pausa, argumentos.tpm)
        resultados.append(resultado)

        print(
            f"[{resultado['status']}] {resultado['id']} ({resultado['tipo']}) "
            f"{resultado['tempo_s']}s | {resultado['tokens']} tokens"
        )

        if resultado["status"] != "OK":
            print(
                f"      suportada={resultado['suportada']}, "
                f"esperado={resultado['esperado_suportada']}"
            )
            if resultado["erro"]:
                print(f"      - {resultado['erro']}")
            print(f"      saida: {resultado['saida_bruta'][:220]!r}")

    imprimir_resumo(resultados)
    print(f"\nResultados salvos em: {salvar(resultados)}")


if __name__ == "__main__":
    main()