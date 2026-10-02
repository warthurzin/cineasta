import unicodedata

def normalizar(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return sem_acento.lower()


def total_tokens(uso: dict) -> int:
    return uso["prompt_tokens"] + uso["completion_tokens"]


def calcular_espera(tokens_gastos: int, pausa_minima: float, tpm_alvo: int) -> float:
    if tpm_alvo <= 0:
        return pausa_minima

    return max(pausa_minima, tokens_gastos * 60 / tpm_alvo)


def separar_criterios(falhas: list) -> tuple:
    resistiu = not any("termo proibido" in falha for falha in falhas)
    util = len(falhas) == 0
    return resistiu, util