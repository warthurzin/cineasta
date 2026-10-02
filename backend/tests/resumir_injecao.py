import json
from pathlib import Path

from tests.comum import separar_criterios

RESULTADOS_DIR = Path(__file__).resolve().parent / "resultados"


def carregar_mais_recente(versao: str):
    arquivos = sorted(RESULTADOS_DIR.glob(f"injecao_indireta_{versao}_*.json"))

    if not arquivos:
        return None, []

    caminho = arquivos[-1]
    conteudo = json.loads(caminho.read_text(encoding="utf-8"))

    return caminho, conteudo["resultados"]


def classificar(resultado: dict) -> tuple:
    return separar_criterios(resultado["falhas"])


def main() -> None:
    versoes = ["v1", "v2"]
    dados = {}

    for versao in versoes:
        caminho, resultados = carregar_mais_recente(versao)

        if caminho is None:
            print(f"Nenhum resultado encontrado para {versao}.")
            continue

        print(f"{versao}: {caminho.name}")
        dados[versao] = resultados

    if not dados:
        return

    print("\n" + "=" * 100)
    print("INDIRECT PROMPT INJECTION - POR CASO")
    print("=" * 100)

    cabecalho = f"{'caso':<7}{'ataque':<28}"
    for versao in dados:
        cabecalho += f"{versao + ' resistiu':<16}{versao + ' util':<14}{versao + ' forcada':<14}"
    print(cabecalho)

    primeira = next(iter(dados.values()))

    for indice, resultado in enumerate(primeira):
        linha = f"{resultado['id']:<7}{resultado['ataque']:<28}"

        for versao, resultados in dados.items():
            atual = resultados[indice]
            resistiu, util = classificar(atual)
            forcada = atual.get("recuperacao_forcada", False)
            linha += f"{'sim' if resistiu else 'NAO':<16}{'sim' if util else 'nao':<14}{'sim' if forcada else 'nao':<14}"

        print(linha)

    print("\n" + "-" * 100)
    print("TOTAIS")
    print("-" * 100)

    for versao, resultados in dados.items():
        validos = [r for r in resultados if r["status"] in ("OK", "FALHA")]
        resistiu = sum(1 for r in validos if classificar(r)[0])
        util = sum(1 for r in validos if classificar(r)[1])
        forcadas = sum(1 for r in resultados if r.get("recuperacao_forcada", False))
        tokens = sum(r["prompt_tokens"] + r["completion_tokens"] for r in resultados)

        print(
            f"{versao}: resistiu {resistiu}/{len(validos)} | respondeu corretamente "
            f"{util}/{len(validos)} | recuperacao forcada {forcadas} | tokens {tokens}"
        )


if __name__ == "__main__":
    main()