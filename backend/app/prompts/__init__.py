from importlib import import_module

VERSOES_DISPONIVEIS = ("v1", "v2")


def obter_prompts(versao: str):
    if versao not in VERSOES_DISPONIVEIS:
        raise ValueError(
            f"Versao de prompt desconhecida: {versao!r}. "
            f"Versoes disponiveis: {', '.join(VERSOES_DISPONIVEIS)}."
        )

    return import_module(f"app.prompts.{versao}")