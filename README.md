# API Financeiro

Backend FastAPI de um SaaS multi-tenant de controle de gastos. A pessoa se cadastra, envia o
**extrato CSV** que baixou do banco e vê **quanto gastou em cada mês, por categoria**. Cada cadastro
cria um tenant (família, empresa…) isolado, com a pessoa como admin.

**Stack:** Python 3.11+, FastAPI, SQLAlchemy 2, MySQL 8 (PyMySQL), Redis, Alembic, jwcrypto (JWE), Argon2.

```
app/
├── core/          config, segurança (Argon2 + JWE), cliente Redis, estado de sessão (token_store)
├── db/            Base declarativa, sessão, isolamento de tenant (tenant.py)
├── models/        Tenant, Usuario, Conta, Categoria, Transacao, Importacao
├── schemas/       modelos Pydantic de entrada/saída
├── api/deps/      dependencies: auth, redis, tenant (get_tenant_db)
├── api/routes/    auth, usuarios, importacoes, resumo, contas, categorias, transacoes
├── services/      csv_extrato (leitura do CSV), categorizacao, importacao
├── cli.py         criação de tenant pelo servidor (opcional, backoffice)
└── main.py
alembic/           migrations (0001 = schema inicial, 0002 = importação de extratos)
tests/             pytest (SQLite em memória ou MySQL real + fakeredis)
```

---

## Como rodar localmente

### Opção A: tudo em Docker

```bash
cp .env.example .env
# gere duas chaves e cole em JWE_ACCESS_KEY e JWE_REFRESH_KEY:
python -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode())"
# para testar via http://localhost sem HTTPS, defina COOKIE_SECURE=false no .env

docker compose up --build -d          # MySQL, Redis e API (aplica migrations ao subir)
```

Depois é só se cadastrar em `POST /auth/signup` (veja o fluxo abaixo).

A API fica em http://localhost:8000 e a documentação em http://localhost:8000/docs (desativada quando `ENVIRONMENT=production`).

### Opção B: API no host, MySQL/Redis em Docker

```bash
docker compose up -d mysql redis
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                 # preencha as chaves, COOKIE_SECURE=false
alembic upgrade head
uvicorn app.main:app --reload
```

### Fluxo básico

```bash
# cadastro → cria o tenant, você vira admin e já sai logado
curl -c jar -X POST localhost:8000/auth/signup -H 'content-type: application/json' \
  -d '{"nome":"Maria","email":"maria@exemplo.com","senha":"minhasenha","nome_tenant":"Família Souza"}'

# login → access token no corpo, refresh token em cookie
curl -c jar -X POST localhost:8000/auth/login -H 'content-type: application/json' \
  -d '{"email":"admin@silva.com","senha":"..."}'

# importar um extrato (Nubank é reconhecido sozinho) e ver o resumo do mês
curl -H "Authorization: Bearer <access>" -F arquivo=@Nubank_2026-10.csv -F "conta_nome=Nubank - Cartão" localhost:8000/importacoes
curl -H "Authorization: Bearer <access>" "localhost:8000/resumo?mes=2026-10"
curl -b jar -c jar -X POST localhost:8000/auth/refresh     # novo access + refresh rotacionado
```

### Testes

```bash
pytest                                      # SQLite em memória + fakeredis, sem dependências
TEST_DATABASE_URL='mysql+pymysql://financeiro:financeiro@localhost:3306/financeiro_test?charset=utf8mb4' pytest
```

O teste pedido (tenant A não lê, edita nem deleta transação do tenant B manipulando o ID na URL) é
`tests/test_tenant_isolation.py::test_tenant_a_nao_le_edita_nem_deleta_transacao_do_tenant_b`.

---

## Endpoints

| Método | Rota | Acesso |
|---|---|---|
| POST | `/auth/signup` | público: cria tenant + admin e já loga (limite por IP) |
| POST | `/auth/login` | público (com rate limit) |
| POST | `/auth/refresh` | cookie de refresh |
| POST | `/auth/logout` | idempotente |
| POST / GET | `/usuarios` | **admin**: cria/lista usuários do próprio tenant |
| GET | `/usuarios/me` | autenticado |
| POST | `/importacoes/preview` | lê o CSV **sem salvar**: formato detectado, colunas, 5 primeiras linhas, sugestão de colunas |
| POST | `/importacoes` | importa o CSV (multipart) para uma conta |
| GET | `/importacoes` | histórico de importações |
| DELETE | `/importacoes/{id}` | desfaz: remove a importação e os lançamentos que ela criou |
| GET | `/resumo?mes=AAAA-MM` | gastos, entradas, saldo e despesas por categoria do mês |
| GET | `/resumo/meses` | meses que têm lançamentos |
| CRUD | `/contas`, `/categorias`, `/transacoes` | autenticado (o front usa a listagem e a troca de categoria) |

`POST /importacoes` (multipart/form-data): `arquivo` (CSV, até 5 MB / 50 mil linhas) e `conta_id`
**ou** `conta_nome` (cria a conta se não existir). Para bancos não reconhecidos: `coluna_data`,
`coluna_descricao`, `coluna_valor` e `gastos_positivos` (true quando gastos vêm positivos, como em
faturas). Resposta: `{importacao: {importadas, duplicadas, com_erro, ...}, meses, erros: [{linha, motivo}]}`.

`GET /transacoes` aceita: `data_inicio`, `data_fim`, `campo_data` (`competencia` padrão, ou `lancamento`),
`conta_id`, `categoria_id`, `incluir_subcategorias` (padrão `true`), `tipo`, `limit` (1–500), `offset`.
A resposta é `{items, total, limit, offset}`.

---

## Decisões de arquitetura e raciocínio

### 1. Multi-tenancy: shared database / shared schema

Todas as tabelas de domínio (`contas`, `categorias`, `transacoes`, e também `usuarios`) têm
`tenant_id BIGINT NOT NULL` com FK para `tenants` e índice. As consultas mais quentes têm índices
compostos começando por `tenant_id` (`(tenant_id, data_competencia)`, `(tenant_id, data_lancamento)`),
porque toda consulta filtra por tenant primeiro.

**Por quê:** é o modelo mais barato de operar (um schema, uma migration, um pool de conexões) e escala
bem até muitos tenants pequenos, que é o perfil de um app de controle de gastos. O custo é que o
isolamento passa a ser responsabilidade da aplicação. Os itens 2 e 8 existem para pagar esse custo.

### 2. Isolamento centralizado (`app/db/tenant.py` + `app/api/deps/tenant.py`)

As rotas de domínio não recebem uma `Session` crua. Recebem um `TenantSession` pela dependency
`get_tenant_db`, que pega o `tenant_id` **do usuário autenticado**, nunca de path, query ou body.

O filtro é aplicado em duas camadas:

- **Leitura:** um listener `do_orm_execute` adiciona
  `with_loader_criteria(TenantScopedMixin, tenant_id == X)` a **todo** SELECT/UPDATE/DELETE ORM daquela
  sessão. Isso vale para qualquer model que herde `TenantScopedMixin`. Cobre `session.get()`, lazy
  loads de relacionamentos, subqueries (o `count()` da paginação) e `update()` em massa. O código das
  rotas não tem nenhum `where(tenant_id == ...)`: esquecer o filtro deixa de ser um erro possível.
- **Escrita:** um listener `before_flush` preenche `tenant_id` em objetos novos e levanta
  `TenantViolationError` se alguém tentar inserir, alterar ou deletar um registro com `tenant_id`
  diferente do da sessão (inclusive "mover" um registro trocando o `tenant_id`).

Complementos:
- Schemas de entrada usam `extra="forbid"`: mandar `tenant_id` no corpo dá 422 em vez de ser ignorado.
- Referências cruzadas (`conta_id`, `categoria_id`, `categoria_pai_id`) são validadas pela sessão
  filtrada. Sem isso, um usuário poderia criar uma transação no próprio tenant apontando para a conta
  de outro, já que uma FK simples não impede.
- Registro de outro tenant retorna **404, não 403**, para não revelar que o ID existe.
- Sessões sem tenant (signup, login, CLI) não são filtradas. O único bypass explícito
  (`execution_options(skip_tenant_filter=True)`) é a checagem de e-mail duplicado, que devolve só um booleano.

### 3. Auth com JWE (jwcrypto)

Os tokens são JWTs **criptografados** (`alg=dir`, `enc=A256GCM`), não apenas assinados. Um JWT comum é
só base64: qualquer um que o intercepte (logs, ferramentas de debug, extensões) lê `user_id`,
`tenant_id` e `role`. Com JWE, o conteúdo é opaco para o cliente, e o AES-GCM também garante integridade.

- Chaves simétricas de 256 bits, **separadas para access e refresh**. Um tipo de token nunca decifra
  com a chave do outro, e o claim `typ` é verificado mesmo assim.
- Algoritmos aceitos são fixos (`algs=["dir","A256GCM"]`), o que fecha ataques de troca de algoritmo.
- Access: 15 min. Refresh: 7 dias. Ambos configuráveis.
- Senhas com **Argon2id**. No login, um hash dummy é verificado quando o e-mail não existe, para que o
  tempo de resposta não revele quais e-mails estão cadastrados.

### 4. Access token no corpo, refresh token em cookie HttpOnly

- **Access token no JSON**, guardado em memória pelo frontend: não fica em `localStorage` (exposto a
  XSS persistente) e não é enviado automaticamente pelo navegador (imune a CSRF).
- **Refresh token em cookie** `HttpOnly; Secure; SameSite=Strict; Path=/api/auth`: JavaScript não o lê,
  ele só trafega em HTTPS e nunca é enviado em requisições cross-site. O `Path` faz com que ele só
  vá para `/api/auth/refresh` e `/api/auth/logout`, e não para cada chamada de API. O valor é o caminho
  **que o navegador vê** (`REFRESH_COOKIE_PATH`): atrás do proxy é `/api/auth`; acessando a API
  direto, sem proxy, use `/auth`.
- `SameSite=Strict` funciona porque frontend e API ficam na **mesma origem** atrás de um proxy reverso
  (ex.: `app.com/` → frontend, `app.com/api/*` → esta API, com o proxy removendo o prefixo `/api`). Por isso não há CORS configurado.
- Ao recarregar a página, o frontend chama `/auth/refresh` para recuperar um access token.

**Estado no Redis (`app/core/token_store.py`):**
- **Rotação de refresh:** cada refresh token só pode ser usado uma vez (allowlist por `jti` com `GETDEL`
  atômico). Cada uso emite um par novo.
- **Detecção de reuso:** se um refresh token válido mas já consumido aparece de novo, provavelmente
  foi roubado. A **família** inteira é revogada, o que derruba também o token que o atacante já tinha
  rotacionado.
- **Logout** revoga a família de refresh e coloca o `jti` do access token atual numa denylist até ele
  expirar, para que o logout tenha efeito imediato e não só depois de 15 min.
- **Rate limit de login:** 5 tentativas por e-mail a cada 15 min.
- Usuário ou tenant desativado perde acesso na próxima requisição, porque `get_current_user` confere no banco.

### 5. Cadastro público com um tenant por cadastro

`POST /auth/signup` cria **um tenant novo** com quem se cadastra como `admin`, devolve o access token
e seta o cookie de refresh, como no login. O cadastro **nunca** coloca alguém dentro de um tenant
existente: isso exigiria um convite, senão qualquer pessoa poderia entrar nos dados de outra. Usuários
adicionais de um tenant são criados pelo admin em `POST /usuarios`, sempre no tenant do próprio admin.

- O schema recusa `role` e `tenant_id` no corpo (422): não dá para se cadastrar em outro tenant nem
  escolher o perfil.
- Há um limite de cadastros por IP (`SIGNUP_MAX_PER_IP` por `SIGNUP_WINDOW_SECONDS`) contra criação
  em massa de tenants. Atrás do proxy, o IP vem de `X-Forwarded-For` (`--proxy-headers` no uvicorn).
- O e-mail é único globalmente, então o login não pede tenant: ele é inferido do usuário. Por isso o
  cadastro responde 409 para e-mail já usado, o que revela que o e-mail existe. É o custo usual de um
  signup sem confirmação por e-mail (veja os próximos passos).
- A CLI `python -m app.cli criar-tenant` continua disponível para criar tenants pelo servidor
  (backoffice), mas não é necessária.

### 6. Modelo de domínio

- **Dinheiro em centavos, `BIGINT`, nunca float.** Float não representa 0,10 exatamente, e erros de
  arredondamento se acumulam em somas. O schema usa `strict=True`, então `10.5` ou `"1050"` são
  rejeitados. O valor é sempre positivo (`CHECK valor_centavos > 0`) e o sinal vem de `tipo`
  (`receita`/`despesa`): somar receitas e despesas não depende de convenção de sinal.
- **`data_competencia` vs `data_lancamento`:** uma compra no cartão em 20/09 *pertence* a setembro
  (competência, que serve para orçamento por mês) mas *sai do caixa* em 05/10 com a fatura (lançamento,
  que serve para fluxo de caixa). O filtro `campo_data` escolhe qual usar. Se `data_lancamento` não for
  enviada, ela assume o valor da competência.
- **Categorias hierárquicas** via `categoria_pai_id` (auto-referência), com validação contra ciclos.
  Filtrar por uma categoria inclui as subcategorias por padrão.
- **Contas** `carteira | corrente | cartao_credito`. FKs com `RESTRICT`: não dá para apagar uma conta
  ou categoria em uso (409). A conta pode ser desativada em vez de apagada.
- Enums gravados como `VARCHAR` (não `ENUM` nativo do MySQL), para que adicionar um valor não exija
  `ALTER TABLE` pesado.

### 7. Importação de extratos CSV

**Leitura (`app/services/csv_extrato.py`, sem acesso a banco, testada isoladamente):**
- Codificação UTF-8 (com ou sem BOM) ou Windows-1252, que é o que os bancos brasileiros exportam.
  O separador (`,`, `;` ou tab) é detectado sozinho.
- **Nubank reconhecido pelo cabeçalho:** conta (`Data,Valor,Identificador,Descrição`, negativo =
  saída) e cartão (`date,title,amount`, positivo = compra). Qualquer outro CSV entra no modo
  **genérico**: o preview sugere as colunas pelo nome (data, histórico/descrição, valor) e a pessoa
  confirma na tela. Assim funciona com qualquer banco sem que precisemos conhecer o formato de cada um.
- Valores viram centavos com `Decimal`, nunca `float`. Aceita `-45.90`, `1.234,56`, `R$ 1.234,56`,
  `(45,90)` e `45,90-`. Datas em `dd/mm/aaaa`, `aaaa-mm-dd`, `dd/mm/aa`, inclusive com hora.
- Linhas ilegíveis não derrubam a importação: são puladas e devolvidas como `{linha, motivo}`.

**Reimportar não duplica.** Cada lançamento importado guarda um `id_externo`, que é único por
`(tenant, conta, id_externo)`:
- no Nubank conta, é o `Identificador` do próprio banco;
- nos demais formatos, é uma impressão digital `hash(data, valor, descrição, ocorrência)`. A
  `ocorrência` diferencia lançamentos idênticos no mesmo arquivo (dois cafés iguais no mesmo dia) e é
  estável ao reler o arquivo. Na prática, quem baixa o extrato de novo, ou um período que se sobrepõe
  ao anterior, só recebe os lançamentos novos.

**Categorização automática** (`app/services/categorizacao.py`): regras por palavra-chave (iFood →
Alimentação, Uber → Transporte, Drogasil → Saúde…) e "Outros" quando nenhuma casa. As categorias
padrão são criadas no tenant na primeira importação. As regras são simples de propósito: a pessoa
troca a categoria na tela (`PATCH /transacoes/{id}`) e o resumo reflete a troca.

**Pagamento de fatura fica fora dos totais.** Quem importa o extrato da conta *e* a fatura do cartão
veria a mesma despesa duas vezes: cada compra na fatura e depois o "Pagamento de fatura" na conta.
A categoria "Pagamento de fatura" tem `fora_do_resumo = true`. O resumo exclui esses valores dos
gastos e das entradas e os informa à parte (`fora_do_resumo_centavos`).

**Desfazer:** cada arquivo gera um registro em `importacoes`, e `DELETE /importacoes/{id}` remove
os lançamentos criados por ele (útil quando o arquivo foi enviado para a conta errada).

**Resumo do mês** (`GET /resumo`): agrega no banco (`GROUP BY` categoria e tipo), pela data de
competência. Como toda consulta da sessão, o filtro de tenant é aplicado automaticamente, e há teste
garantindo que o tenant A não vê o resumo, os meses nem as importações do tenant B.

### 8. Testes de isolamento

`tests/test_tenant_isolation.py` cria dois tenants via API e verifica que A recebe 404 ao fazer
GET/PATCH/DELETE de uma transação de B pelo ID, que filtros com `conta_id`/`categoria_id` de B voltam
vazios, que A não consegue referenciar a conta ou categoria de B, que `tenant_id` no corpo é rejeitado
e que a transação de B continua intacta. Um teste adicional exercita o `TenantSession` diretamente
(SELECT sem WHERE, `session.get`, `count`, `update` em massa e escrita cruzada). Esses testes falham se
o listener de tenant for removido: isso foi conferido durante o desenvolvimento.

---

## Próximos passos sugeridos

- **FK composta `(tenant_id, conta_id) → contas(tenant_id, id)`** para que o próprio banco recuse
  referências entre tenants (hoje isso é validado na aplicação).
- **Rotação de chaves JWE** com `kid` no header e um JWKSet com a chave atual e a anterior.
- Rate limit também por IP, e por rota no proxy.
- Auditoria (quem alterou o quê) para transações.
- **Regras de categoria aprendidas:** quando a pessoa recategoriza "Padaria X", aplicar a mesma
  escolha nas próximas importações.
- Formatos reconhecidos automaticamente para outros bancos (Inter, Itaú, Bradesco…) e OFX.
- **Confirmação de e-mail no cadastro** (conta inativa até clicar no link) e CAPTCHA no signup.
  Também permitiria responder ao cadastro sem revelar se o e-mail já existe.
- **Convites:** o admin envia um link para alguém entrar no tenant dele, em vez de definir a senha da pessoa.
