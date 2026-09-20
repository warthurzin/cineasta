import json
import os
import time
from datetime import date
from pathlib import Path

import requests

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
IDIOMA = "pt-BR"
TOTAL_FILMES_DESEJADO = 100
PAUSA_ENTRE_REQUISICOES = 0.05  

VOTOS_MINIMOS = 1000

DATA_LIMITE = date.today().isoformat()

ORDENACOES_DESCOBERTA = [
    "popularity.desc",
    "vote_average.desc",
]


def _requisitar(endpoint, params=None):
    params = params or {}
    params["api_key"] = TMDB_API_KEY
    params["language"] = IDIOMA

    resposta = requests.get(f"{TMDB_BASE_URL}/{endpoint}", params=params, timeout=15)
    resposta.raise_for_status()
    return resposta.json()


def coletar_ids_de_filmes(total_desejado):
    ids_coletados = []
    ids_vistos = set()

    pagina = 1
    while len(ids_coletados) < total_desejado and pagina <= 15:
        for ordenacao in ORDENACOES_DESCOBERTA:
            if len(ids_coletados) >= total_desejado:
                break

            dados = _requisitar(
                "discover/movie",
                params={
                    "page": pagina,
                    "sort_by": ordenacao,
                    "vote_count.gte": VOTOS_MINIMOS,
                    "release_date.lte": DATA_LIMITE,
                    "include_adult": "false",
                },
            )
            time.sleep(PAUSA_ENTRE_REQUISICOES)

            for resultado in dados.get("results", []):
                filme_id = resultado["id"]
                if filme_id not in ids_vistos:
                    ids_vistos.add(filme_id)
                    ids_coletados.append(filme_id)

        pagina += 1

    return ids_coletados[:total_desejado]


def buscar_detalhes_filme(filme_id):
    return _requisitar(f"movie/{filme_id}")


def buscar_creditos_filme(filme_id):
    return _requisitar(f"movie/{filme_id}/credits")


def extrair_diretor(creditos):
    diretores = [
        pessoa["name"]
        for pessoa in creditos.get("crew", [])
        if pessoa.get("job") == "Director"
    ]
    return ", ".join(diretores) if diretores else "Nao informado"


def extrair_elenco_principal(creditos, limite=5):
    elenco = creditos.get("cast", [])[:limite]
    return [
        f"{pessoa['name']} (como {pessoa['character']})"
        if pessoa.get("character")
        else pessoa["name"]
        for pessoa in elenco
    ]


def formatar_data(data_str):
    if not data_str:
        return "data nao informada"
    return data_str.split("-")[0]


def _formatar_valor_monetario(valor):
    if not valor:
        return "nao informado"

    if valor >= 1_000_000_000:
        return f"{valor / 1_000_000_000:.2f} bilhoes de dolares".replace(".00", "")
    if valor >= 1_000_000:
        return f"{valor / 1_000_000:.1f} milhoes de dolares".replace(".0", "")

    return f"{valor} dolares"


def montar_documento(detalhes, creditos):
    titulo = detalhes.get("title") or detalhes.get("original_title")
    ano = formatar_data(detalhes.get("release_date"))
    generos = ", ".join(g["name"] for g in detalhes.get("genres", []))
    sinopse = detalhes.get("overview") or "Sinopse nao disponivel em portugues nesta base."
    diretor = extrair_diretor(creditos)
    elenco_principal = extrair_elenco_principal(creditos)
    nota_media = detalhes.get("vote_average")
    quantidade_votos = detalhes.get("vote_count")
    duracao = detalhes.get("runtime")
    orcamento = detalhes.get("budget") or 0
    bilheteria = detalhes.get("revenue") or 0

    ano_texto = f"foi lancado em {ano}" if ano != "data nao informada" else "nao tem data de lancamento informada"

    direcao_texto = (
        f"O filme {titulo} foi dirigido por {diretor}."
        if diretor != "Nao informado"
        else f"O diretor do filme {titulo} nao esta informado na base de dados."
    )

    genero_texto = (
        f"O filme {titulo} e classificado nos seguintes generos: {generos}."
        if generos
        else f"O genero do filme {titulo} nao esta informado na base de dados."
    )

    duracao_texto = (
        f"O filme {titulo} tem duracao de {duracao} minutos."
        if duracao
        else f"A duracao do filme {titulo} nao esta informada na base de dados."
    )

    orcamento_texto = (
        f"O orcamento estimado de producao do filme {titulo} foi de {_formatar_valor_monetario(orcamento)}."
        if orcamento
        else f"O orcamento de producao do filme {titulo} nao esta informado na base de dados."
    )

    bilheteria_texto = (
        f"O filme {titulo} arrecadou aproximadamente {_formatar_valor_monetario(bilheteria)} em bilheteria."
        if bilheteria
        else f"A bilheteria do filme {titulo} nao esta informada na base de dados."
    )

    elenco_texto = (
        f"O filme {titulo} e estrelado por um elenco principal formado pelos "
        f"seguintes atores e atrizes, com seus respectivos personagens: "
        + "; ".join(elenco_principal)
        + f". Esses sao os interpretes principais do filme {titulo}."
        if elenco_principal
        else f"O elenco principal do filme {titulo} nao esta informado na base de dados."
    )

    nota_formatada = f"{nota_media:.1f}" if nota_media is not None else None
    avaliacao_texto = (
        f"O filme {titulo} tem nota media de {nota_formatada} (em uma escala de 0 a 10), "
        f"com base em {quantidade_votos} avaliacoes de usuarios no TMDb."
        if nota_formatada is not None
        else f"A avaliacao do filme {titulo} nao esta disponivel na base de dados."
    )

    return {
        "id": f"tmdb_{detalhes['id']}",
        "titulo": f"{titulo} ({ano})",
        "categoria": generos.split(",")[0].strip() if generos else "Nao informado",
        "secoes": {
            "sinopse": f"A sinopse do filme {titulo} e a seguinte: {sinopse}",
            "ano_de_lancamento": f"O filme {titulo} {ano_texto}.",
            "direcao": direcao_texto,
            "genero": genero_texto,
            "duracao": duracao_texto,
            "orcamento": orcamento_texto,
            "bilheteria": bilheteria_texto,
            "elenco": elenco_texto,
            "avaliacao": avaliacao_texto,
        },
        "fonte": "TMDb (The Movie Database)",
        "fonte_url": f"https://www.themoviedb.org/movie/{detalhes['id']}",
    }


def main():
    if not TMDB_API_KEY:
        raise RuntimeError(
            "Defina a variavel de ambiente TMDB_API_KEY com sua chave da "
            "API do TMDb antes de executar este script."
        )

    print(f"Coletando IDs de ate {TOTAL_FILMES_DESEJADO} filmes no TMDb...")
    ids_filmes = coletar_ids_de_filmes(TOTAL_FILMES_DESEJADO)
    print(f"IDs coletados: {len(ids_filmes)}")

    documentos = []

    for indice, filme_id in enumerate(ids_filmes, start=1):
        try:
            detalhes = buscar_detalhes_filme(filme_id)
            time.sleep(PAUSA_ENTRE_REQUISICOES)

            creditos = buscar_creditos_filme(filme_id)
            time.sleep(PAUSA_ENTRE_REQUISICOES)

            documento = montar_documento(detalhes, creditos)
            documentos.append(documento)

            print(f"[{indice}/{len(ids_filmes)}] Coletado: {documento['titulo']}")
        except requests.HTTPError as erro:
            print(f"[{indice}/{len(ids_filmes)}] Falha ao coletar filme {filme_id}: {erro}")

    saida = Path(__file__).parent / "filmes.json"
    saida.write_text(
        json.dumps(documentos, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\nTotal de documentos gerados: {len(documentos)}")
    print(f"Arquivo salvo em: {saida}")


if __name__ == "__main__":
    main()