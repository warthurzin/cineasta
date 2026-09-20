from app import config

_historicos = {}


def obter_historico(session_id):
    return _historicos.get(session_id, [])


def adicionar_turno(session_id, papel, texto):
    historico = _historicos.setdefault(session_id, [])
    historico.append({"papel": papel, "texto": texto})

    limite_mensagens = config.MAX_TURNOS_HISTORICO * 2
    if len(historico) > limite_mensagens:
        _historicos[session_id] = historico[-limite_mensagens:]


def formatar_historico(session_id):
    historico = obter_historico(session_id)

    if not historico:
        return ""

    linhas = []
    for turno in historico:
        rotulo = "Usuario" if turno["papel"] == "usuario" else "Assistente"
        linhas.append(f"{rotulo}: {turno['texto']}")

    return "\n".join(linhas)


def limpar_sessao(session_id):
    _historicos.pop(session_id, None)