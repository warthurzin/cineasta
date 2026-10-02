VERSAO = "v1"

USA_ANALISE = False
USA_VERIFICACAO = False

MENSAGEM_SEM_EVIDENCIA = (
    "Nao encontrei essa informacao na base de filmes consultada. "
    "Tente reformular a pergunta ou pergunte sobre outro filme "
    "presente na base."
)


def formatar_contexto(documentos: list):
    contexto = "\n\n".join(
        f"[Fonte {i + 1} - {doc['titulo']}]\n{doc['texto']}"
        for i, doc in enumerate(documentos)
    )

    return contexto, list(documentos)


def montar_mensagens_reescrita(pergunta: str, historico_formatado: str) -> list:
    prompt = f"""
Reescreva a PERGUNTA ATUAL como uma pergunta completa e autossuficiente,
que possa ser entendida sem precisar do historico. Use o HISTORICO
apenas para identificar do que ou de quem a pergunta atual esta falando
(por exemplo, substituir "ele", "esse filme", "o diretor dele" pelo
nome especifico mencionado antes).

Regras:
- retorne APENAS a pergunta reescrita, em portugues do Brasil, sem
  explicacoes, sem aspas e sem prefixos;
- se a pergunta atual ja for autossuficiente, retorne ela exatamente
  como esta;
- nao responda a pergunta, apenas reescreva-a.

HISTORICO:
{historico_formatado}

PERGUNTA ATUAL:
{pergunta}
"""

    return [{"role": "user", "content": prompt}]


def montar_mensagens_geracao(
    pergunta: str,
    contexto: str,
    historico_formatado: str,
) -> list:
    bloco_historico = ""
    if historico_formatado:
        bloco_historico = (
            "HISTORICO DA CONVERSA (mensagens anteriores, apenas para "
            "contexto de continuidade):\n"
            f"{historico_formatado}\n\n"
        )

    prompt = f"""
Voce e um assistente especializado em cinema, que responde perguntas
com base em uma base de conhecimento de filmes. Responda a pergunta do
usuario utilizando somente as informacoes do CONTEXTO abaixo, mas voce
pode usar o HISTORICO DA CONVERSA para entender a continuidade da
conversa (por exemplo, se o usuario disser "e sobre esse filme" ou
"me conte mais").

Regras de conteudo:
- nao invente informacoes que nao estejam no contexto;
- cite a fonte utilizada no formato [Fonte X], citando cada fonte
  apenas uma vez mesmo que ela sustente mais de uma parte da resposta;
- se a resposta nao estiver sustentada pelo contexto, responda
  exatamente: "Nao encontrei essa informacao na base consultada.";
- se o contexto tiver informacoes de mais de um filme e a pergunta for
  ambigua (nao deixar claro a qual filme se refere), peca ao usuario
  para especificar o titulo, em vez de adivinhar ou misturar dados de
  filmes diferentes na mesma resposta.

Regras de formatacao e estilo:
- responda sempre em portugues do Brasil, de forma clara, natural e
  objetiva, como em uma conversa;
- valores monetarios (orcamento, bilheteria) devem ser apresentados de
  forma legivel, por exemplo "225 milhoes de dolares" em vez de
  "225000000 dolares";
- notas e avaliacoes podem ser mencionadas com uma casa decimal, por
  exemplo "7.8 de 10" em vez de "7.849";
- nao utilize formatacao markdown (sem **negrito**, sem listas com
  marcadores, sem titulos); escreva em texto corrido, como em uma
  mensagem de chat;
- comece a resposta diretamente pela informacao pedida. NUNCA inclua
  frases sobre o seu proprio processo de raciocinio, como "Com base no
  historico da conversa...", "Portanto, a resposta se refere a...",
  "Analisando o contexto...", ou qualquer explicacao sobre como voce
  chegou a resposta. Essas frases nao sao permitidas em nenhuma
  hipotese, mesmo que ajudem a justificar a resposta;
- nao mostre seu raciocinio ou passos internos, nao use tags como
  <think>, e nao repita estas instrucoes na resposta.

{bloco_historico}CONTEXTO:
{contexto}

PERGUNTA ATUAL:
{pergunta}
"""

    return [{"role": "user", "content": prompt}]