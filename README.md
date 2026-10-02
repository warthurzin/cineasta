# Cineasta - Chatbot com RAG sobre Filmes

Chatbot web com Retrieval-Augmented Generation (RAG) sobre uma base de
conhecimento de 100 filmes, orquestrado com LangGraph, busca vetorial
com FAISS e geracao de resposta final com a Groq (modelo
`qwen/qwen3.8-27b`).

Na Atividade 2, o projeto evoluiu com foco em Engenharia de Prompt: os
prompts foram identificados, refinados e avaliados antes e depois, e
foram acrescentadas uma etapa de analise da pergunta e uma etapa de
verificacao da resposta. O relatorio completo esta em
[`docs/ENGENHARIA_DE_PROMPT.md`](docs/ENGENHARIA_DE_PROMPT.md).

## Equipe

- Arthur Marques da Silveira
- Pedro Henrique Leal Amaral
- Luanna Evellyn Batista da Silva
- Marielly de Araujo Silva

## Sumario

- [Dominio e base de conhecimento](#dominio-e-base-de-conhecimento)
- [Arquitetura](#arquitetura)
- [Pipeline de RAG](#pipeline-de-rag)
- [Estrutura do repositorio](#estrutura-do-repositorio)
- [Pre-requisitos](#pre-requisitos)
- [Configuracao das variaveis de ambiente](#configuracao-das-variaveis-de-ambiente)
- [Como executar com Docker (recomendado)](#como-executar-com-docker-recomendado)
- [Como executar localmente sem Docker](#como-executar-localmente-sem-docker)
- [Como executar no GitHub Codespaces](#como-executar-no-github-codespaces)
- [Regerando a base de conhecimento](#regerando-a-base-de-conhecimento)
- [Uso da interface](#uso-da-interface)
- [Engenharia de prompt (Atividade 2)](#engenharia-de-prompt-atividade-2)
- [Testes e avaliacao dos prompts](#testes-e-avaliacao-dos-prompts)
- [Decisoes e observacoes tecnicas](#decisoes-e-observacoes-tecnicas)
- [Limitacoes conhecidas](#limitacoes-conhecidas)

## Dominio e base de conhecimento

O dominio escolhido foi **filmes**. A base de conhecimento tem **100
filmes**, coletados de forma programatica a partir da API publica do
**TMDb (The Movie Database)**, garantindo dados reais e verificaveis,
com sinopses em portugues do Brasil.

- Fonte dos dados: [TMDb API v3](https://developer.themoviedb.org/reference/intro/getting-started)
- Script de coleta: [`backend/data/coletar_tmdb.py`](backend/data/coletar_tmdb.py)
- Base gerada (versionada no repositorio): [`backend/data/filmes.json`](backend/data/filmes.json)
- Cada filme na base registra tambem o campo `fonte_url`, com o link
  direto para a pagina do filme no TMDb, permitindo auditar a origem
  de qualquer informacao.

Cada filme e representado por 9 fatos (secoes) independentes: sinopse,
ano de lancamento, direcao, genero, duracao, orcamento, bilheteria,
elenco principal e avaliacao media de usuarios.

Este produto usa a API do TMDb, mas nao e endossado ou certificado
pelo TMDb, conforme exigido pelos
[termos de uso da API](https://www.themoviedb.org/documentation/api/terms-of-use).

## Arquitetura

```
[ Navegador ]
      |
      | HTTP (fetch)
      v
[ Frontend: nginx + HTML/CSS/JS ]  (porta 5500)
      |
      | HTTP (POST /chat)
      v
[ Backend: FastAPI ]  (porta 8000)
      |
      |-- LangGraph (orquestracao do fluxo de RAG)
      |     |-- analise da pergunta (Groq, saida JSON): dominio, ambiguidade
      |     |     e pergunta legitima
      |     |-- recuperacao vetorial (FAISS + sentence-transformers)
      |     |-- roteamento condicional (com/sem evidencia)
      |     |-- montagem de contexto (agrupado por filme)
      |     |-- geracao da resposta final (Groq)
      |     |-- verificacao da resposta (Groq, saida JSON)
      |
      |-- Memoria de conversa (em memoria de processo, por sessao)
      |
      v
[ API externa: Groq (qwen/qwen3.8-27b) ]
```

Frontend e backend rodam em containers Docker separados, comunicando-se
por HTTP.

## Pipeline de RAG

1. O script `coletar_tmdb.py` busca 100 filmes ja lancados e com
   avaliacao consolidada (minimo de 1000 votos no TMDb), combinando
   ordenacao por popularidade e por nota media, para gerar uma base
   diversa e com dados confiaveis.
2. Para cada filme, cada fato (sinopse, direcao, genero, duracao,
   orcamento, bilheteria, elenco, avaliacao, ano de lancamento) e
   escrito como uma frase de linguagem natural completa e autocontida,
   e nao como um rotulo tecnico solto (por exemplo, "O filme Cidade de
   Deus foi dirigido por Fernando Meirelles." em vez de "Direcao:
   Fernando Meirelles."). O nome do filme e repetido dentro de cada
   frase. Essa decisao de formato foi resultado de testes praticos e
   esta detalhada na secao "Decisoes e observacoes tecnicas".
3. O script `build_index.py` cria um chunk por fato (nao corta o texto
   por contagem de palavras): cada filme gera 9 chunks, um por secao.
4. Cada chunk e transformado em um embedding vetorial usando o modelo
   multilingue `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.
5. Os embeddings sao armazenados em um indice vetorial FAISS
   (`IndexFlatIP`, equivalente a similaridade de cosseno com vetores
   normalizados).
6. O indice e gerado automaticamente durante o build da imagem Docker
   do backend, a partir do `filmes.json` versionado no repositorio (nao
   e necessario nenhum passo manual de indexacao antes de subir os
   containers).
7. Quando o usuario envia uma pergunta pela interface, o backend recebe
   a mensagem e o identificador da sessao de conversa.
8. A mensagem passa primeiro por um prompt de analise (Groq, saida em
   JSON), que a classifica como `FILMES`, `AMBIGUA` ou `FORA_DOMINIO`,
   extrai a pergunta legitima (descartando instrucoes dirigidas ao
   assistente) e, quando ha historico, resolve referencias como "ele"
   ou "esse filme". Perguntas ambiguas recebem um pedido de
   esclarecimento e perguntas fora do dominio recebem a abstencao,
   ambas sem busca e sem geracao.
9. A pergunta autonoma e usada para buscar os 8 chunks mais relevantes
   no indice FAISS.
10. Um roteamento condicional no grafo do LangGraph verifica se o score
    de similaridade do melhor resultado ultrapassa um limiar minimo
    (0.35). Se nao ultrapassar, o fluxo desvia para uma resposta padrao
    de abstencao, sem chamar a LLM e sem exibir nenhuma fonte.
11. Se houver evidencia suficiente, os chunks recuperados sao agrupados
    por filme em blocos delimitados e enviados, junto com o historico
    da conversa, para a Groq gerar a resposta final. As instrucoes vao
    na mensagem `system` e os dados na mensagem `user`.
12. A resposta gerada passa por um prompt de verificacao (Groq, saida em
    JSON), que checa se ela esta sustentada pelas fontes citadas. Se
    nao estiver, e substituida por uma resposta de evidencia
    insuficiente.
13. A resposta e devolvida a interface junto com a(s) fonte(s) (titulo
    do filme) efetivamente citada(s) pela LLM no formato [Fonte X]; se
    nenhuma fonte for citada (por exemplo, na resposta de abstencao),
    nenhuma fonte e exibida.

Todo esse fluxo (analise, recuperacao, decisoes condicionais, montagem
de contexto, geracao e verificacao) e implementado como um grafo do
LangGraph em `backend/app/rag_graph.py`. Com `PROMPT_VERSION=v1`, o fluxo
volta ao comportamento da Atividade 1 (reescrita de pergunta quando ha
historico, sem analise e sem verificacao).

## Estrutura do repositorio

```
.
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py               # API FastAPI (endpoints /chat, /health)
│   │   ├── config.py             # Configuracao via variaveis de ambiente
│   │   ├── models.py             # Schemas Pydantic
│   │   ├── rag_graph.py          # Grafo LangGraph (RAG conversacional)
│   │   ├── llm.py                # Chamada centralizada a Groq (modo JSON, tokens)
│   │   ├── analise.py            # Contrato JSON da analise da pergunta
│   │   ├── verificacao.py        # Contrato JSON da verificacao da resposta
│   │   ├── prompts/
│   │   │   ├── __init__.py       # Selecao da versao de prompt
│   │   │   ├── v1.py             # Prompts da Atividade 1 (baseline)
│   │   │   └── v2.py             # Prompts refinados (Atividade 2)
│   │   ├── retriever.py          # Busca vetorial no indice FAISS
│   │   ├── memory.py             # Memoria de conversa por sessao
│   │   └── build_index.py        # Script de indexacao (chunking + FAISS)
│   ├── data/
│   │   ├── filmes.json           # Base de conhecimento (100 filmes, TMDb)
│   │   ├── coletar_tmdb.py       # Script que coleta e gera filmes.json
│   │   └── requirements-dados.txt # Dependencia extra so para coletar_tmdb.py
│   ├── tests/
│   │   ├── casos_teste.json              # Suite principal (27 casos)
│   │   ├── casos_analise.json            # Analise isolada (16 casos)
│   │   ├── casos_verificacao.json        # Verificacao isolada (12 casos)
│   │   ├── casos_injecao_indireta.json   # Injection indireta (7 casos)
│   │   ├── documentos_injecao.json       # Documentos ficticios com instrucoes maliciosas
│   │   ├── avaliar_prompts.py            # Executa a suite por versao de prompt
│   │   ├── avaliar_analise.py            # Compara zero-shot e few-shot
│   │   ├── avaliar_verificador.py        # Avalia o verificador
│   │   ├── avaliar_injecao_indireta.py   # Executa a injection indireta
│   │   ├── base_injecao.py               # Mescla documentos envenenados na busca
│   │   ├── resumir_injecao.py            # Resume os resultados de injection indireta
│   │   ├── comum.py                      # Funcoes compartilhadas
│   │   └── resultados/                   # JSONs gerados pelas avaliacoes
│   ├── requirements.txt
│   └── Dockerfile
│   └── .dockerignore
├── frontend/
│   ├── index.html
│   ├── style.css
│   ├── script.js
│   ├── config.js                 # URL da API (ajustavel por ambiente)
│   ├── nginx.conf
│   └── Dockerfile
├── docs/
│   └── ENGENHARIA_DE_PROMPT.md       # Relatorio da Atividade 2
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

## Pre-requisitos

- Docker e Docker Compose (plugin `docker compose`), para o metodo de
  execucao recomendado.
- Python 3.12+ e `pip`, apenas se for executar sem Docker.
- Uma chave de API da Groq (gratuita, sem cartao de credito). Crie em
  console.groq.com, na secao "API Keys".
- Uma chave de API do TMDb, apenas se for regerar a base de dados
  (`filmes.json` ja vem pronto no repositorio, entao isso e opcional).
  Crie gratuitamente em themoviedb.org/settings/api.

## Configuracao das variaveis de ambiente

Antes de qualquer metodo de execucao, copie o arquivo de exemplo e
preencha sua chave da Groq:

```bash
cp .env.example .env
```

Edite o `.env` e substitua `coloque_sua_chave_groq_aqui` pela sua chave
real (formato `gsk_...`):

| Variavel             | Obrigatoria | Padrao             | Descricao                                                         |
| -------------------- | :---------: | ------------------ | ----------------------------------------------------------------- |
| `GROQ_API_KEY`       |     Sim     | -                  | Chave de API da Groq, usada na analise, geracao e verificacao.    |
| `GROQ_MODEL`         |     Nao     | `qwen/qwen3.8-27b` | Modelo da Groq utilizado em todas as chamadas a LLM.              |
| `CORS_ORIGINS`       |     Nao     | `*`                | Origens permitidas para chamadas do frontend a API.               |
| `PROMPT_VERSION`     |     Nao     | `v2`               | Versao dos prompts. `v1` restaura o comportamento da Atividade 1. |
| `FEW_SHOT`           |     Nao     | `true`             | Inclui exemplos (few-shot) no prompt de analise da pergunta.      |
| `VERIFICAR_RESPOSTA` |     Nao     | `true`             | Liga ou desliga a etapa de verificacao da resposta gerada.        |

O `docker-compose.yml` repassa essas seis variaveis ao container do
backend. Para trocar de versao ou desligar uma etapa, edite o `.env` e
suba os containers novamente com `docker compose up`.

Outros parametros do pipeline sao lidos por `backend/app/config.py` e
podem ser definidos por variavel de ambiente na execucao local sem
Docker (o `docker-compose.yml` nao os repassa; para usa-los em
container, inclua-os na secao `environment` do servico `backend`):

| Variavel                | Padrao | Descricao                                                               |
| ----------------------- | :----: | ----------------------------------------------------------------------- |
| `TOP_K`                 |  `8`   | Quantidade de chunks recuperados do indice FAISS por pergunta.          |
| `LIMIAR_EVIDENCIA`      | `0.35` | Score minimo do melhor chunk; abaixo dele o fluxo vai para a abstencao. |
| `MAX_TURNOS_HISTORICO`  |  `6`   | Quantidade maxima de turnos de historico considerados na conversa.      |
| `LLM_TEMPERATURE`       | `0.1`  | Temperatura da geracao da resposta (analise e verificacao usam 0).      |
| `LLM_MAX_TOKENS`        | `900`  | Limite de tokens da resposta gerada.                                    |
| `EMBEDDING_MODEL_NAME`  |   -    | Modelo de embeddings (`paraphrase-multilingual-MiniLM-L12-v2`).         |
| `DATA_DIR`, `INDEX_DIR` |   -    | Pastas da base de conhecimento e do indice FAISS.                       |

## Como executar com Docker (recomendado)

Este e o metodo de execucao principal, testado e recomendado para uso
local (fora do GitHub Codespaces; para Codespaces, ver a secao
especifica mais abaixo).

1. Clone o repositorio e entre na pasta do projeto.

2. Configure o `.env` conforme a secao anterior.

3. Suba os containers:

   ```bash
   docker compose up --build
   ```

   Esse comando builda a imagem do backend (instala dependencias e
   gera o indice FAISS automaticamente a partir de `filmes.json`, ja
   incluido no repositorio) e a imagem do frontend (nginx servindo os
   arquivos estaticos), e sobe os dois servicos.

   Durante o build do backend, o log deve mostrar algo como:

   ```
   Documentos carregados: 100
   Chunks gerados: 900
   Indexacao concluida com sucesso: 100 filmes, 900 chunks, 900 vetores.
   ```

4. Acesse a aplicacao:
   - Frontend (chat): http://localhost:5500
   - Backend (API): http://localhost:8000
   - Verificacao de saude da API: http://localhost:8000/health
   - Documentacao interativa da API: http://localhost:8000/docs

   O arquivo frontend/config.js já aponta, por padrão, para http://localhost:8000, que é o endereço correto quando os containers rodam localmente. Ainda assim, é necessário garantir que a porta 8000 (backend) esteja configurada como pública e não como privada na aba PORTS do ambiente (clique com o botão direito na porta 8000 e selecione Port Visibility > Public), caso contrário o navegador não conseguirá se comunicar com a API mesmo com a URL correta configurada.

5. Para parar os containers:

   ```bash
   docker compose down
   ```

6. Caso precise reconstruir do zero (por exemplo, apos regenerar
   `filmes.json`), garanta que nao ha imagens ou cache antigos
   interferindo:

   ```bash
   docker compose down
   docker builder prune -a -f
   docker compose up --build
   ```

## Como executar localmente sem Docker

Util para desenvolvimento e depuracao do backend isoladamente.

1. Configure o `.env` conforme a secao de variaveis de ambiente (na
   raiz do repositorio; o backend le esse arquivo mesmo rodando fora de
   um container).

2. Crie e ative um ambiente virtual, e instale as dependencias:

   ```bash
   cd backend
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

   No Windows, ative o ambiente virtual com `venv\Scripts\activate`.

3. Gere o indice FAISS a partir da base de conhecimento (ja incluida no
   repositorio):

   ```bash
   python -m app.build_index
   ```

4. Suba a API:

   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

5. Em outro terminal (com o passo 4 continuando a rodar), sirva o
   frontend (arquivos estaticos):

   ```bash
   cd frontend
   python3 -m http.server 5500
   ```

6. Acesse http://localhost:5500. O frontend/config.js já aponta para http://localhost:8000 por padrão, Ainda assim, é necessário garantir que a porta 8000 (backend) esteja configurada como pública e não como privada na aba PORTS do ambiente (clique com o botão direito na porta 8000 e selecione Port Visibility > Public), caso contrário o navegador não conseguirá se comunicar com a API mesmo com a URL correta configurada.

## Como executar no GitHub Codespaces

O projeto tambem pode ser executado dentro de um Codespace. Os passos
sao os mesmos das secoes anteriores (Docker ou execucao local), com
duas diferencas importantes causadas pela forma como o Codespaces expoe
portas para a internet:

1. Tornar a porta do backend publica. Na aba PORTS do Codespace,
   localize a porta 8000, clique com o botao direito nela e selecione
   Port Visibility > Public. Por padrao ela fica privada, o que impede
   o navegador de acessar a API.

2. Apontar o frontend para a URL publica do backend. Copie a URL
   publica gerada pelo Codespaces para a porta 8000 (formato
   `https://SEU-CODESPACE-8000.app.github.dev`, visivel na propria aba
   PORTS) e defina-a em `frontend/config.js`:

   ```js
   window.CHATBOT_API_BASE_URL = "https://SEU-CODESPACE-8000.app.github.dev";
   ```

   Isso e necessario porque o navegador acessa a aplicacao pela URL
   publica do Codespaces, nao pelo localhost da maquina que hospeda os
   containers ou processos.

   Se estiver usando Docker, reconstrua a imagem do frontend apos essa
   mudanca (ela e copiada para dentro da imagem no build):

   ```bash
   docker compose up --build frontend
   ```

   Se estiver rodando sem Docker (`python3 -m http.server`), basta
   salvar o arquivo e recarregar a pagina no navegador.

3. Atencao ao espaco em disco. Codespaces tem um limite de disco menor
   que uma maquina local. Se o build do Docker falhar por falta de
   espaco, limpe imagens e cache nao utilizados antes de tentar de
   novo:

   ```bash
   docker system prune -a -f
   ```

Fora essas duas diferencas, o restante do processo (configurar `.env`,
subir os containers ou processos, testar) e identico ao descrito nas
secoes anteriores.

## Regerando a base de conhecimento

O arquivo `filmes.json` ja vem pronto no repositorio, entao este passo
e opcional (util caso a equipe queira coletar uma base atualizada ou
com criterios diferentes).

1. Obtenha uma chave de API do TMDb (gratuita) em
   themoviedb.org/settings/api.

2. Instale a dependencia extra usada apenas por este script:

   ```bash
   cd backend
   source venv/bin/activate
   pip install -r data/requirements-dados.txt
   ```

3. Exporte sua chave do TMDb como variavel de ambiente (esta chave nao
   vai para o `.env` do projeto nem e usada pela aplicacao em runtime,
   apenas por este script pontual):

   ```bash
   export TMDB_API_KEY="sua_chave_do_tmdb_aqui"
   ```

4. Rode o script de coleta (leva cerca de 1 a 2 minutos, faz por volta
   de 200 requisicoes a API do TMDb):

   ```bash
   cd data
   python3 coletar_tmdb.py
   ```

   Isso sobrescreve `filmes.json` com uma nova coleta de 100 filmes.

5. Reindexe e, se estiver usando Docker, reconstrua a imagem do backend
   do zero para que o novo indice seja gerado (ver secao "Como executar
   com Docker", passo 6).

## Uso da interface

- Digite uma pergunta sobre algum dos 100 filmes da base: sinopse,
  diretor, elenco, genero, duracao, ano de lancamento, orcamento,
  bilheteria ou avaliacao.
- A conversa mantem memoria: perguntas de continuidade como "quem e o
  diretor do filme?" ou "qual a duracao?" (sem repetir o nome do filme)
  sao entendidas no contexto do filme mencionado anteriormente na mesma
  conversa.
- Cada resposta exibe a fonte (titulo do filme) que a LLM efetivamente
  citou para fundamentar a resposta. Quando o sistema nao encontra a
  informacao, nenhuma fonte e exibida.
- O botao "Nova conversa" limpa o historico da sessao atual (tanto no
  navegador quanto na memoria do backend) e inicia uma conversa nova.
- Perguntas fora do dominio da base (por exemplo, "qual a capital da
  Franca?") ou sem evidencia suficiente recebem uma resposta padrao
  informando que a informacao nao foi encontrada na base consultada,
  em vez de uma resposta inventada pela LLM.
- Perguntas ambiguas, em que nenhum filme pode ser identificado (por
  exemplo, "qual a duracao?" no inicio de uma conversa), fazem o
  assistente pedir o titulo do filme.
- Se a verificacao concluir que a resposta gerada nao esta sustentada
  pelas fontes, o assistente informa que nao encontrou evidencia
  suficiente, em vez de entregar a resposta.

## Engenharia de prompt (Atividade 2)

A versao dos prompts e escolhida por `PROMPT_VERSION`. A `v1` e a
original da Atividade 1, mantida congelada para comparacao; a `v2` e a
versao refinada, usada por padrao.

| Prompt      | No do grafo      | Responsabilidade                                                                                                  | Saida                 |
| ----------- | ---------------- | ----------------------------------------------------------------------------------------------------------------- | --------------------- |
| Analise     | `analisar`       | Classificar a mensagem (`FILMES`, `AMBIGUA`, `FORA_DOMINIO`), extrair a pergunta legitima e sinalizar manipulacao | JSON validado         |
| Geracao     | `gerar_resposta` | Responder usando somente o contexto recuperado, citando as fontes                                                 | Texto com `[Fonte N]` |
| Verificacao | `verificar`      | Checar se a resposta esta sustentada pelas fontes citadas                                                         | JSON validado         |

Tecnicas aplicadas: papel, tarefa, regras e formato de saida explicitos;
separacao entre instrucoes (`system`) e dados (`user`); delimitadores
`<contexto>`, `<fonte>`, `<pergunta>`; contexto agrupado por filme com
`<` e `>` neutralizados; comportamento definido quando nao ha
evidencia; zero-shot e few-shot no prompt de analise; decomposicao em
prompts menores encadeados pelo grafo; e defesas contra prompt
injection direta e indireta.

Resultado na suite de 27 casos (mesmos casos, mesmo modelo, trocando
apenas a versao dos prompts):

|                         |   v1   |   v2   |
| ----------------------- | :----: | :----: |
| Casos que passam        | 19/27  | 24/27  |
| Injection direta        |  3/6   |  6/6   |
| Perguntas ambiguas      |  0/2   |  2/2   |
| Chamadas a LLM na suite |   31   |   72   |
| Tokens na suite         | 34.495 | 83.978 |

A v2 acerta mais, mas consome cerca de 2,4 vezes mais tokens. No teste de
injection indireta (instrucao maliciosa dentro de um documento
recuperado), nenhuma das duas versoes obedeceu a injection, entao esse
teste nao diferencia as versoes. Os detalhes, as limitacoes e as
ressalvas de cada medicao estao em
[`docs/ENGENHARIA_DE_PROMPT.md`](docs/ENGENHARIA_DE_PROMPT.md).

## Testes e avaliacao dos prompts

Os testes sao scripts Python que chamam a aplicacao de verdade (incluindo
a Groq) e comparam as respostas com regras automaticas. Eles rodam no
ambiente local (ver "Como executar localmente sem Docker"), e nao dentro
do container: precisam da chave da Groq no `.env` e do indice gerado
(`python -m app.build_index`). A partir de `backend/`, com o ambiente
virtual ativo:

```bash
python -m tests.avaliar_prompts --versoes v1 v2
python -m tests.avaliar_analise
python -m tests.avaliar_verificador
python -m tests.avaliar_injecao_indireta --apenas-recuperacao
python -m tests.avaliar_injecao_indireta --versoes v1 v2 --forcar-recuperacao
python -m tests.resumir_injecao
```

| Comando                    | O que faz                                                                                                     |
| -------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `avaliar_prompts`          | Suite principal de 27 casos, por versao de prompt                                                             |
| `avaliar_analise`          | Compara o prompt de analise em zero-shot e few-shot (16 casos)                                                |
| `avaliar_verificador`      | Avalia o prompt de verificacao isoladamente (12 casos)                                                        |
| `avaliar_injecao_indireta` | Mescla documentos ficticios com instrucoes maliciosas na busca e verifica se a aplicacao as obedece (7 casos) |
| `resumir_injecao`          | Resume os resultados de injection indireta ja gerados, sem chamar a LLM                                       |

Cada execucao salva um JSON em `backend/tests/resultados/`. Os
resultados usados no relatorio estao nessa pasta, e as execucoes
intermediarias, em `backend/tests/resultados/historico/`.

Observacoes importantes:

- Uma execucao completa da suite na v2 consome cerca de 84 mil tokens da
  Groq. A conta gratuita tem limites de tokens por minuto e por dia; os
  scripts controlam o ritmo (`--tpm`, padrao 6000), e as opcoes
  `--categorias` e `--grupos` permitem rodar apenas parte dos casos.
- `--apenas-recuperacao` nao chama a LLM e nao consome tokens.
- Como a LLM nao e deterministica, os numeros podem variar entre
  execucoes.

## Decisoes e observacoes tecnicas

Esta secao documenta os principais problemas encontrados durante o
desenvolvimento e as solucoes adotadas, para referencia da equipe e de
quem for avaliar o projeto.

- Modelo da Groq: tentamos utilizar inicialmente o modelo
  `qwen/qwen3.6-27b`. Durante o desenvolvimento, esse modelo foi
  descontinuado pela Groq e passou a retornar erro 404 (model_not_found). O
  projeto foi atualizado para usar `qwen/qwen3.8-27b`.
- Chunking por fato, em linguagem natural (nao por contagem de
  palavras): a primeira versao do pipeline de indexacao cortava o
  texto de cada filme em blocos de tamanho fixo (~80 palavras), e cada
  fato era escrito como um rotulo tecnico ("Direcao: X. Duracao: Y.").
  Em testes com a base de 100 filmes (de estrutura textual repetitiva),
  esse formato causava recuperacoes incorretas: perguntas factuais
  como "quem dirigiu X?" muitas vezes recuperavam a sinopse de outro
  filme em vez da ficha tecnica correta, porque o modelo de embeddings
  (treinado sobre linguagem natural) associava melhor a pergunta a
  frases narrativas do que a blocos de rotulos concatenados. A solucao
  foi reescrever cada fato como uma frase natural e autocontida,
  repetindo o nome do filme dentro da propria frase (por exemplo, "O
  filme Cidade de Deus foi dirigido por Fernando Meirelles." em vez de
  "Direcao: Fernando Meirelles."), e gerar um chunk por fato em vez de
  cortar por contagem de palavras.
- Reescrita de pergunta antes da busca vetorial: perguntas de
  continuidade (por exemplo, "e quais premios ele ganhou?"), quando
  usadas diretamente na busca vetorial, geram embeddings pouco
  informativos e podem recuperar chunks do filme errado. Quando ha
  historico de conversa, a pergunta e reescrita por uma chamada a LLM
  antes da busca no FAISS, tornando-a autossuficiente. Na v2, essa
  tarefa passou para o no de analise, que tambem classifica a
  mensagem e descarta instrucoes maliciosas antes da busca; a
  reescrita da v1 permanece apenas como reserva, caso a analise
  falhe.
- Filtragem de fontes citadas: a lista de fontes exibida na interface
  mostra apenas os chunks cuja numeracao [Fonte X] foi efetivamente
  citada pela LLM na resposta. Quando a LLM nao cita nenhuma fonte (por
  exemplo, na resposta de abstencao), a lista de fontes retornada e
  vazia, em vez de mostrar todos os chunks candidatos que foram
  recuperados mas descartados.
- PyTorch CPU-only: o Dockerfile do backend instala explicitamente a
  versao CPU-only do PyTorch (dependencia do sentence-transformers) a
  partir do indice oficial do PyTorch, evitando o download de
  dependencias de CUDA/GPU desnecessarias para este projeto, o que
  reduz significativamente o tamanho e o tempo de build da imagem.
- Modo offline do Hugging Face em runtime: o modelo de embeddings e
  baixado e cacheado durante o build da imagem Docker. Em tempo de
  execucao, o container roda com HF_HUB_OFFLINE=1 e
  TRANSFORMERS_OFFLINE=1, evitando que o container tente acessar a
  internet desnecessariamente ao iniciar.
- Logs estruturados do pipeline de RAG: cada etapa do grafo (pergunta
  original e reescrita, candidatos recuperados com seus scores, decisao
  do roteamento condicional, resposta final e fontes citadas) e
  registrada via logging, facilitando o diagnostico de problemas de
  recuperacao ou geracao diretamente pelos logs do backend (visiveis no
  terminal do uvicorn ou em docker compose up, sem -d).

## Limitacoes conhecidas

- A memoria de conversa e mantida em memoria de processo (nao em um
  banco de dados), associada a um session_id gerado pelo navegador.
  Isso e suficiente para o escopo desta atividade, mas significa que o
  historico de conversas e perdido caso o container do backend seja
  reiniciado.
- A conta gratuita da Groq tem limites de taxa (requisicoes e tokens
  por minuto). Em uso intenso e continuo, e possivel esbarrar
  ocasionalmente em erros 429. Na v2, uma pergunta que chega a geracao
  faz ate tres chamadas a LLM (analise, geracao e verificacao);
  `FEW_SHOT=false` e `VERIFICAR_RESPOSTA=false` reduzem o consumo.
- Para alguns filmes, secoes especificas
  podem, em casos pontuais, nao ser recuperadas entre os 8 candidatos
  considerados, caso a secao correta esteja competindo de perto com
  secoes de outros filmes na busca por similaridade. Isso e mitigado
  pelo TOP_K relativamente alto (8) e pela escrita das secoes em
  linguagem natural, mas nao eliminado por completo.
- A base de conhecimento cobre apenas os 100 filmes presentes em
  filmes.json (selecionados automaticamente por popularidade e nota no
  TMDb); perguntas sobre filmes fora dessa lista corretamente resultam
  na resposta de abstencao.
- Campos que a propria TMDb nao disponibiliza para um filme especifico
  (por exemplo, duracao ou orcamento de alguns titulos) sao registrados
  explicitamente como "nao informado" na base, e o assistente reporta
  essa ausencia em vez de inventar um valor.
- O verificador de respostas e rigoroso: reprova uma resposta que afirme
  qualquer fato ausente das fontes, mesmo que verdadeiro (por exemplo,
  chamar um filme de "brasileiro" quando isso nao consta na base). Isso
  protege contra afirmacoes sem fonte, mas pode trocar respostas uteis por
  uma resposta de evidencia insuficiente.
- Perguntas que envolvem dois filmes dependem de a busca vetorial trazer
  chunks dos dois; quando traz de apenas um, o assistente responde que nao
  encontrou a informacao.
- As defesas contra prompt injection sao baseadas em prompts e em
  validacao de formato. Nos testes realizados nenhuma injection foi
  obedecida, mas a amostra e pequena e o resultado vale para este modelo.
  Em um sistema com ferramentas ou acoes externas, seriam necessarios
  controles fora do modelo.
- Detalhes, numeros e ressalvas da avaliacao dos prompts em
  [`docs/ENGENHARIA_DE_PROMPT.md`](docs/ENGENHARIA_DE_PROMPT.md).
