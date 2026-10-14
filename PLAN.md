# PLAN — `chats`: navegador único de conversas de todos os CLIs

> **Status:** Fases 1 + 2 + 3 IMPLEMENTADAS E APROVADAS (2026-10-06) — 56 testes verdes
> **Data:** 2026-10-06
> **Autor:** planejamento conjunto (análise feita na sessão `ses_eeed8283dffeQWQJbk3v9n6BB5`)
>
> **Decisões confirmadas:** nome = `chats` · picker = `fzf` (0.74.3 já instalado) · entrega = Fases 1+2+3
> ⚠️ O nome `code` foi descartado: `code → /usr/bin/code` é o VS Code.
>
> **Resultado medido:** 791 registros / 6 CLIs · `doctor` 6/6 verdes · scan 275 ms (warm) ·
> import real 0,3 s + idempotência por ledger. Descobertas da implementação na seção 18.

---

## 1. Objetivo

Um único comando no terminal que **lista conversas de todos os CLIs de IA instalados** (opencode, codex, agy/antigravity, devin, freebuff, gemini), com três comportamentos:

1. **Escopo por diretório** — na home (`/home/thiago`) mostra tudo de todas as subpastas; dentro de um projeto mostra só as conversas daquele projeto.
2. **Busca difusa** — filtro em tempo real sobre título + preview + pasta.
3. **Abertura dupla** — ao escolher uma conversa, oferece: abrir **no CLI nativo** (continuar a conversa onde ela vive) ou **importar/abrir no OpenCode** (unificar tudo no opencode), além de só **ler/exportar**.

Não é um substituto dos CLIs: é um **índice/launcher por cima** deles.

---

## 2. Inventário das fontes (verificado na máquina em 2026-10-06)

Números medidos, não estimados.

| # | CLI | Binário | Fonte de dados | Formato | Registros | Tem `cwd`? | Campo do `cwd` |
|---|-----|---------|----------------|---------|-----------|------------|----------------|
| 1 | **opencode** | `~/.opencode/bin/opencode` (v2.0.24) | `~/.local/share/opencode/opencode.db` | SQLite (WAL) | 563 sessões, 23.026 msgs, 91.626 parts; 1,5 GB | ✅ | `session_v2.directory` |
| 2 | **codex** | `/usr/bin/codex` | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | JSONL | 202 rollouts, **202/202 com cwd** | ✅ | linha `type=session_meta` → `payload.cwd` |
| 3 | **agy** (antigravity) | `/usr/bin/agy` (v1.2.14) | `~/.gemini/antigravity-cli/conversation_summaries.db` | SQLite | 293 conversas (193 `.db` de conversa em `conversations/`) | ✅ 276/293 | `workspace_uris` (JSON array de `file:///…`) |
| 4 | **devin** | `~/.local/bin/devin` | `~/.local/share/devin/cli/sessions.db` | SQLite (WAL, **4,6 GB**) | 39 sessões, 167.643 `message_nodes`, 927 prompts | ✅ | `sessions.working_directory` |
| 5 | **freebuff** | `/usr/bin/freebuff` (v0.2.16) | `~/.config/manicode/projects/<proj>/chats/<ts>/` | JSON por conversa | 45 arquivos de chat | ✅ 7/7 com `run-state` | `run-state.json` → `sessionState.fileContext.cwd` |
| 6 | **gemini** | `/usr/bin/gemini` | `~/.gemini/tmp/<proj>/chats/session-*.json` | JSON | 3 chats | ✅ | `../.project_root` (arquivo irmão) |

### 2.1 Detalhe por fonte

#### 1. opencode
```sql
SELECT id, title, directory, path, time_created, time_updated, parent_id, agent, model
FROM session_v2
WHERE parent_id IS NULL          -- só top-level (filhas de subagent não aparecem na listagem nativa)
ORDER BY time_updated DESC;
```
- `session_message.type ∈ {user, assistant, system, compaction, synthetic, idle}` + `session_message.data` (JSON).
- `part` (91.626 linhas) guarda as partes: `type ∈ {text, tool, reasoning, step-start, step-finish, patch, compaction, file}` ligadas por `message_id`.
- **Mensagem `user`**: `{"text": "...", "time": {"created": 1790556485294}}`
- **Mensagem `assistant`**: `{"agent": "build", "model": {"providerID","id","variant"}, "content": [{"type":"text","text":"…"}], "cost", "tokens": {…}, "time": {…}}`
- ⚠️ **Banco compartilhado com o serviço em execução.** Abrir somente em `mode=ro`, com `PRAGMA busy_timeout=5000`. **Nunca escrever** (lição da incidente de 2026-10-06, seção 11).
- Fonte alternativa (mais segura): API HTTP `GET /api/session?limit=…` (o serviço já roda em `127.0.0.1`).

#### 2. codex
- Primeira linha do rollout = `session_meta`: `{payload: {cwd, session_id, id, timestamp, cli_version, source…}}`.
- Tipos encontrados num rollout: `session_meta` (1), `event_msg` (671), `response_item` (544), `world_state` (4), `turn_context` (6), `token_usage_record` (147), `compacted` (2).
- Títulos: `~/.codex/session_index.jsonl` → `{id, thread_name, updated_at}` (nomes duplicados por id; pegar o mais recente).
- Primeiro prompt: `~/.codex/history.jsonl` → `{session_id, ts, text}` (346 linhas) — ótimo pra preview.
- Distribuição de `cwd`: PORTFOLIO 105 · `/home/thiago` 77 · codesnippets 10 · JuntAI 7 · outros 3.

#### 3. agy
```sql
SELECT conversation_id, title, preview, workspace_uris, last_modified_time,
       last_user_input_time, step_count, agent_name, project_id, parent_conversation_id
FROM conversation_summaries
ORDER BY last_user_input_time DESC;
```
- `workspace_uris` = `'["file:///home/thiago/Documentos/codesnippets/PORTFOLIO"]'` → parsear JSON, strip `file://`.
- 17 de 293 sem workspace → marcar `cwd = None` e só mostrar com `--all`.
- Espelho JSON (fallback/offline): `~/.gemini/antigravity-cli/cache/conversation_metadata.json` com `WorkspaceURIs`, `Preview`, `UpdatedAt`.
- Conteúdo completo: `~/.gemini/antigravity-cli/conversations/<uuid>.db` (193 arquivos).

#### 4. devin
```sql
SELECT id, working_directory, title, created_at, last_activity_at, hidden, workspace_dirs
FROM sessions ORDER BY last_activity_at DESC;
```
- As 39 sessões do `sessions.db` batem **1:1** com as 39 já importadas pro opencode (`ses_devin<id>`). **Esse é o dedupe.**
- Conteúdo: `message_nodes` (`session_id`, `node_id`, `parent_id`, `chat_message` JSON com `{message_id, role, content, metadata}`, 167.643 linhas) — cadeia de árvore, não lista linear; seguir `main_chain_id` da sessão.
- Fallback (se o `sessions.db` estiver trancado/bloqueado pelo devin): `devin list --format json` (escopo ao cwd, retorna `id, working_directory, title, last_activity_at`) ou `~/.local/share/devin/cli/transcripts/*.json` (35, schema `ATIF-v1.7`), que **não têm cwd**.
- O `sessions.db` tem 4,6 GB + 485 MB de WAL → **não é pra fazer `count(*)` geral**; usar índice e projeção mínima (`sessions` tem só 39 linhas, é instantâneo). `message_nodes` só é lido sob demanda (preview/export).

#### 5. freebuff
```
~/.config/manicode/projects/<nomeProjeto>/chats/<ISO8601>/
  ├── chat-meta.json      {messageCount, firstPrompt, messagesSize, messagesMtimeMs}
  ├── chat-messages.json  [ …mensagens… ]          (pode ser 19 MB → NÃO ler no index)
  ├── run-state.json      {sessionState.fileContext:{projectRoot, cwd, fileTree…}, traceSessionId, output}
  └── log.jsonl
```
- `firstPrompt` do `chat-meta.json` já serve de título/preview sem tocar no `chat-messages.json`.
- Só 7 de 45 têm `run-state.json` → fallback: mapear `~/.config/manicode/recent-projects.json` (`{path, lastOpened}`) + nome da pasta do projeto, ou `~/.freebuff/project-id` / `<repo>/.freebuff/project-id`.
- `~/.config/manicode/message-history.json` é um índice global de mensagens (verificar se tem `cwd`).

#### 6. gemini
```
~/.gemini/tmp/<hashProj>/chats/session-2026-08-11T04-38-a744a24c.json
~/.gemini/tmp/<hashProj>/.project_root     →  /home/thiago/Documentos/codesnippets/Quizsaber
```
- Chat: `{sessionId, projectHash, startTime, lastUpdated, messages[], kind, summary}` → `summary` já é o título.

### 2.2 Comandos de retomada (opener "nativo")

| CLI | Comando | Observação |
|-----|---------|-----------|
| opencode | `opencode -s <id>` | `-s` cria se não existir; `-c` = última sessão |
| codex | `codex resume <id>` | `codex resume` sem id abre picker |
| agy | `agy --conversation <id>` | `-c` = continue mais recente |
| devin | `devin -r <SESSION_ID>` | sem id → picker interativo |
| freebuff | `freebuff --continue <conversation-id>` | |
| gemini | `gemini` + resume (⚠️ **a confirmar**, ver 13) | |

### 2.3 Listagem nativa (usar quando existir — não parsear à toa)

- `devin list --format json` → só do cwd atual.
- `opencode session list --format json` → só do projeto atual.
- Os outros (codex, agy, freebuff, gemini) **não têm** listagem útil → parse de arquivo.

---

## 3. Arquitetura

```
┌──────────────────────────────────────────────────────────────────┐
│  chats (CLI)                                                     │
│                                                                  │
│  ┌────────────┐   ┌──────────────┐   ┌───────────┐   ┌────────┐  │
│  │ adapters/  │ → │ normalizador │ → │  escopo   │ → │ picker │  │
│  │  1 por CLI │   │  Registro    │   │  por cwd  │   │  fzf   │  │
│  └────────────┘   └──────────────┘   └───────────┘   └───┬────┘  │
│        │                                                 │       │
│        │            ┌──────────────┐                     │       │
│        └──────────→ │ índice cache │  (opcional, fase 4) │       │
│                     └──────────────┘                     │       │
│                                                          ▼       │
│                                              ┌─────────────────┐ │
│                                              │    opener       │ │
│                                              │ 1 nativo        │ │
│                                              │ 2 → opencode    │ │
│                                              │ 3 ler/exportar  │ │
│                                              └─────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

- **Adapters** são a única parte que conhece formatos. Saem todos pelo mesmo contrato (`Registro`). Trocar/quebrar um formato nunca afeta o resto.
- **Escopo** é uma função pura: `Registro → bool`.
- **Picker** é intercambiável (fzf ↔ TUI).
- **Opener** recebe o `Registro` e o modo escolhido.

### 3.1 Contrato de dados

```python
@dataclass
class Registro:
    id: str                 # id canônico na fonte
    cli: str                # "opencode" | "codex" | "agy" | "devin" | "freebuff" | "gemini"
    title: str              # título ou 1ª frase do prompt (fallback)
    cwd: str | None         # diretório absoluto; None = desconhecido
    created_at: int | None  # epoch ms
    updated_at: int | None  # epoch ms (ordenação principal)
    preview: str            # ~200 chars da 1ª mensagem do usuário
    n_msgs: int | None
    native_resume: list[str]        # argv pronto, ex. ["codex","resume","<id>"]
    source_path: str                # arquivo/registro de origem (debug/export)
    imported_in_opencode: str | None  # id da sessão opencode equivalente (dedupe)
    meta: dict              # extras livres (agent, model, tags…)
```

### 3.2 Identidade e dedupe

- `key = (cli, id)`.
- **Devin ↔ opencode**: `id` do devin (`gleaming-minibus`) → `ses_devin<id>` no opencode. Dedupe exato.
- Entre CLIs **não** deduplicar automaticamente (conversas diferentes); só marcar se `cwd + primeira frase + mesmo dia` coincidir — item opcional, fase 4.

---

## 4. Regra de escopo por `cwd`

```python
HOME = Path.home()                    # /home/thiago

def resolver_raiz(pwd: Path) -> Path:
    """Raiz de escopo: raiz do git se houver, senão o próprio pwd."""
    try:
        out = run(["git", "-C", pwd, "rev-parse", "--show-toplevel"], timeout=2)
        if out.returncode == 0:
            return Path(out.stdout.strip())
    except Exception:
        pass
    return pwd

def escopo(pwd: Path, modo: str) -> Callable[[Registro], bool]:
    raiz = resolver_raiz(pwd.resolve())

    if modo == "all":                                   # --all
        return lambda r: True

    if raiz == HOME or raiz == Path("/"):               # home → tudo, agrupado
        return lambda r: r.cwd is not None and r.cwd.startswith(str(HOME))

    if modo == "tree":                                  # --tree: raiz + descendentes
        return lambda r: r.cwd is not None and (
            r.cwd == str(raiz) or r.cwd.startswith(str(raiz) + "/"))

    # projeto → só o repo, inclusive cwd exato
    return lambda r: r.cwd is not None and (
        r.cwd == str(raiz) or r.cwd.startswith(str(raiz) + "/"))
```

**Comportamento resultante:**

| Onde você roda `chats` | Escopo | Esperado hoje |
|---|---|---|
| `~/` | tudo sob `$HOME`, agrupado por pasta | ~600+ registros (563 opencode + 202 codex + 293 agy + 39 devin + 45 freebuff + 3 gemini, com overlap) |
| `~/Documentos/codesnippets/PORTFOLIO` (git root) | só esse repo | 105 codex + 16 devin + 16 opencode + … |
| `~/realiza.vc` (git root) | só esse repo | 8 devin + 8 opencode + freebuff… |
| pasta sem git e sem sessões | `cwd` exato | pode ser 0 → mensagem amigável + dica de `--all` |

**Casos-limite a tratar:**
- `cwd=None` (17 agy + backups): mostrar só com `--all`/`--tree`, com aviso `[?]`.
- Sessões em `/tmp/opencode` e `/` (13 no opencode): fora do `$HOME` → só com `--all`.
- Symlinks e `$HOME` com barra final: normalizar com `Path.resolve()` antes de comparar.
- Projeto dentro de monorepo: `git rev-parse` devolve a raiz; se o usuário quiser escopo mais fino, flag `--exact` (só `cwd == pwd`).

---

## 5. Adapters — especificação

Cada adapter expõe duas funções:

```python
def scan() -> Iterator[Registro]: ...     # barato: só metadados
def carregar(id: str) -> Conversa: ...    # caro: mensagens completas (sob demanda)
```

### 5.1 `adapters/opencode.py`
- **scan:** `sqlite3.connect("file:...opencode.db?mode=ro", uri=True)` + `PRAGMA busy_timeout=5000`; query da seção 2.1 (só `parent_id IS NULL`).
- **preview:** 1ª msg `type='user'` do `session_message` da sessão.
- **carregar:** `session_message` + `part` ordenados por `seq`/`time_created` → reconstruir texto.
- **native_resume:** `["opencode", "-s", id]`
- **Risco:** banco em uso → timeout ⇒ degradar para API `GET /api/session` (auth via `opencode api get`).

### 5.2 `adapters/codex.py`
- **scan:** glob `~/.codex/sessions/**/rollout-*.jsonl` (202). Para cada arquivo ler **só a 1ª linha** (`session_meta` → `cwd`, `id`, `timestamp`). Título de `session_index.jsonl` (mapa id→último `thread_name`). Preview de `history.jsonl` (mapa session_id→1º `text`).
- **custo:** 202 leituras de 1 linha ≈ instantâneo. Guardar `mtime` por arquivo.
- **carregar:** ler linhas `event_msg`/`response_item` e filtrar papéis de fala.
- **native_resume:** `["codex", "resume", id]`

### 5.3 `adapters/agy.py`
- **scan:** 1 query na `conversation_summaries` (293 linhas). Parse de `workspace_uris`.
- **carregar:** abrir `conversations/<uuid>.db` (sob demanda).
- **fallback:** `cache/conversation_metadata.json`.
- **native_resume:** `["agy", "--conversation", id]`

### 5.4 `adapters/devin.py`
- **scan:** 1 query na tabela `sessions` (39 linhas) — **nunca** varrer `message_nodes` no scan.
- **carregar:** seguir `main_chain_id` em `message_nodes` (árvore por `parent_node_id`).
- **fallback:** `devin list --format json` (limitado ao cwd) → útil como *verificação* do scan, não como fonte primária.
- **native_resume:** `["devin", "-r", id]`
- **dedupe:** `id → ses_devin<id>` no opencode.

### 5.5 `adapters/freebuff.py`
- **scan:** glob de `chat-meta.json` (leve: `firstPrompt`, `messageCount`) + `run-state.json` (cwd). **Jamais** ler `chat-messages.json` no scan (até 19 MB por conversa).
- **cwd fallback:** `recent-projects.json` pelo nome da pasta do projeto.
- **native_resume:** `["freebuff", "--continue", id]` (id = timestamp da pasta).

### 5.6 `adapters/gemini.py`
- **scan:** glob `~/.gemini/tmp/*/chats/*.json`; ler só cabeçalho (`sessionId`, `summary`, `lastUpdated`, `messages.length`); cwd do `../.project_root`.
- **native_resume:** `["gemini", "…"]` ⚠️ a confirmar.

### 5.7 Registro de adapters (extensível)

```python
ADAPTERS = [opencode, codex, agy, devin, freebuff, gemini]
# `chats doctor` lista quais estão ativos/falhando
```

Adapters com falha **nunca** derrubam a CLI: marcados como `[indisponível]` no rodapé.

---

## 6. Índice e cache (fase 4 — opcional)

Hoje o scan cru é ~1.100 arquivos/queries → estimativa < 300 ms. Só indexar se medir acima de 500 ms.

- `~/.local/share/chats/index.db` (SQLite próprio, **nunca** escrever em DB de terceiros).
- Tabela: `registros(key, cli, id, title, cwd, updated_at, preview, n_msgs, source_path, src_mtime, scanned_at)`.
- Invalidação: por `source_path → src_mtime`; re-scan incremental só do que mudou.
- `chats sync` força rebuild; rebuild automático se o arquivo de índice tiver > 7 dias.

---

## 7. Interface (picker)

### 7.1 MVP: `fzf`

```sh
chats | fzf \
  --ansi \
  --delimiter=$'\t' --with-nth=1,2,3 \
  --preview 'chats preview {4}' \
  --header 'ENTER abre · C-nativo · O-opencode · V-ver' \
  --bind 'enter:execute(chats open --ask {4})+abort'
```

Layout da linha (TSV):
```
[HH:MM]  CLI       TÍTULO (60)                       PASTA RELATIVA
09:20    opencode  Analisar pasta devin e importar    ~/Documentos/…
```
- Cor por CLI (via `--ansi`): opencode=ciano, codex=verde, agy=roxo, devin=âmbar, freebuff=rosa, gemini=azul.
- Pastas exibidas relativas a `$HOME` (`~/…`), absolutas só com `--long`.
- Preview: primeiras ~40 linhas da conversa (`chats preview <key>`).

### 7.2 TUI própria (opcional, fase 5)
Só se o agrupamento por pasta em árvore precisar de navegação visual. `textual` (Python) ou `bubbletea` (Go). Não bloqueia o MVP.

---

## 8. Opener — menu ao escolher

```
┌─ opencode · "Instalar repositório brag globalmente" ────────────┐
│ ~/Documentos/codesnippets/PORTFOLIO · 12 msgs · 05/10 21:02     │
├─────────────────────────────────────────────────────────────────┤
│  1  ▶ Abrir no nativo        codex resume 01a0f65e-…            │
│  2  ⇄ Abrir no OpenCode      importar → opencode -s <novo id>   │
│  3  👁 Ler / exportar        $PAGER (markdown)                  │
│  4  ⧉ Copiar id / caminho                                        │
│  0  Voltar                                                       │
└─────────────────────────────────────────────────────────────────┘
```

- **1 · nativo:** `subprocess` com o argv do adapter, `cwd = registro.cwd` (importante: rodar **no diretório certo**, senão alguns CLIs recriam "projeto" errado — ver incidente 11).
- **2 · OpenCode:** ver seção 9.
- **3 · ler:** converter p/ markdown e abrir no `$PAGER` (`less -R`). Exportar com `chats export <key> --to md|json`.
- **4 · copiar:** `xclip`/`wl-copy` se disponíveis.

### 8.1 Modos de automação (sem TUI)
```sh
chats open <key> --native          # direto, sem menu
chats open <key> --opencode
chats export <key> --to md -
chats which                       # mostra o escopo atual (raiz resolvida)
```

---

## 9. Importar conversa no OpenCode

Endpoint já existente: **`POST /api/experimental/session/import`**

```jsonc
{
  "info":     { /* Session.Info: id?, title, agent, model, time… */ },
  "messages": [ /* Session.Message.Info[] */ ],
  "location": { "directory": "/home/thiago/realiza.vc" }   // ← crítico
}
```

Chamada pela CLI nativa (autenticação automática):
```sh
opencode api post /api/experimental/session/import --data @/tmp/payload.json
```

### 9.1 Mapeamento de mensagens

| Fonte | Papel | Texto | Extras |
|---|---|---|---|
| opencode | `session_message.type` | `part.text` | — (já está lá) |
| codex | `response_item`/`event_msg` | `payload` | modelo/agent do `turn_context` |
| devin | `message_nodes.chat_message.role` | `content` | árvore → linearizar pela `main_chain_id` |
| freebuff | `chat-messages.json[i].role` | `.content` | — |
| gemini | `messages[i].role` | `.content` | — |
| agy | steps do `.db` | — | ⚠️ schema a mapear (fase 2) |

### 9.2 `location.directory` é obrigatório
O OpenCode v2 resolve **projeto pelo diretório**. Se `location` vier vazia/errada, a sessão cai no projeto `global` e **não aparece na listagem** — exatamente o bug que motivou o reaponte de 180 sessões em 2026-10-06 (seção 11).

**Regra:** `location.directory = registro.cwd` (e se `cwd` for `None`, recusar a importação pedindo `--dir`).

### 9.3 Idempotência
Antes de importar, checar se já existe:
- Devin: `ses_devin<id>` → já existe, oferecer "abrir em vez de importar".
- Demais: procurar por `title` + `time.created` iguais em `session_v2`.

---

## 10. UX da CLI

```
chats                          # lista escopada ao cwd (fzf se TTY)
chats --all                    # ignora escopo (tudo, de todos os CLIs)
chats --tree                   # agrupa por pasta
chats --cli codex,devin        # filtra fontes
chats --since 7d               # janela temporal (7d|30d|2026-09)
chats "brag"                   # busca difusa direta (sem fzf)
chats preview <key>            # imprime as N primeiras mensagens (p/ --preview do fzf)
chats open <key> [--native|--opencode|--ask]
chats export <key> [--to md|json] [-o arquivo]
chats import <key> [--dir <path>]
chats doctor                   # saúde dos adapters (paths, contagens, erros)
chats sync                     # rebuild do índice (fase 4)
chats which                    # escopo atual: pwd → raiz resolvida → regra
```

**Flags globais:** `--no-color`, `--limit N`, `--format json|tsv|table` (pra pipe/composição), `--verbose` (erros de adapter).

**Exit codes:** 0 ok · 1 erro · 2 nenhum resultado · 3 adapter indisponível.

**Sem fzf instalado:** cai para lista numerada + `read` (sempre funcional em TTY puro).

---

## 11. Contexto: a incidente que motivou este plano

Em 2026-10-05 um agente importou **39 conversas do Devin** para o OpenCode (`/tmp/opencode/devin2opencode.py`). Depois do update para **OpenCode v2.0.24**, "nenhuma conversa aparecia".

**Causa raiz:** a listagem (`opencode session list` = *"sessions in the current project"*) é **escopada por projeto**, e o v2 passou a criar um projeto por diretório (`cb6b4716…` = `/home/thiago`), enquanto as 201 conversas antigas estavam no projeto legado `global` (worktree `/`). Resultado: **1 conversa visível** em `~`.

**Correção aplicada:** backup (`/tmp/opencode/opencode-backup-2026-10-06-antes-rehome.db`, 1,5 GB, `quick_check` ok) + reaponte de **180 sessões** `global → cb6b4716` recalculando o campo `path`, com dump de reversão (`/tmp/opencode/revert-rehome.json`, 180 linhas). Resultado: **89 conversas top-level visíveis** (30 do Devin), `realiza.vc` intacto (8).

**Lições incorporadas a este plano:**
1. **Nunca escrever** no banco de um CLI de terceiros sem backup + dump de reversão (aqui: só leitura `mode=ro`).
2. Sempre definir `location.directory` na importação (9.2).
3. Respeitar "top-level" (`parent_id IS NULL`) — o opencode esconde filhas de subagent por padrão.
4. Guardar tudo o que for editado em `/tmp` **não é** persistente: mover artefatos para `~/.local/share/chats/`.

---

## 12. Estrutura do projeto

```
~/Documentos/codesnippets/chats-cli/
├── PLAN.md                     ← este documento
├── README.md                   ← uso rápido
├── chats                       ← entrypoint executável (#!/usr/bin/env python3)
├── chats_lib/
│   ├── __init__.py
│   ├── models.py               ← Registro, Conversa, Mensagem
│   ├── escopo.py               ← resolver_raiz(), escopo()  [seção 4]
│   ├── registry.py             ← registro de adapters + erro isolado
│   ├── picker_fzf.py           ← montagem do fzf + fallback numerado
│   ├── openers.py              ← nativo / opencode / pager / copiar
│   ├── import_opencode.py      ← payload + POST via `opencode api`
│   ├── render.py               ← table/TSV/JSON/markdown
│   ├── doctor.py
│   └── adapters/
│       ├── opencode.py
│       ├── codex.py
│       ├── agy.py
│       ├── devin.py
│       ├── freebuff.py
│       └── gemini.py
├── tests/
│   ├── test_escopo.py          ← propriedades da regra de escopo
│   ├── test_adapters.py        ← cada adapter devolve ≥1 Registro em dados reais
│   └── test_import.py          ← payload shape (sem chamar a API)
└── share/
    └── chats.bash|zsh          ← completion opcional
```

- Instalação: symlink `~/.local/bin/chats → …/chats` (já está no PATH).
- Sem dependências externas no MVP: **stdlib pura** (`sqlite3`, `json`, `argparse`, `subprocess`, `pathlib`, `dataclasses`). `fzf` é dependência *opcional*.
- Python ≥ 3.10 (máquina tem 3.14).

---

## 13. Fases, esforço e critérios de aceite

### Fase 1 — MVP (esqueleto + 2 fontes) ✅ APROVADA 2026-10-06
**Escopo:** `models`, `escopo`, `registry`, adapters **opencode** + **codex**, picker fzf + fallback, opener nativo, `doctor`, `which`.
- [x] `chats` em `~` lista opencode + codex agrupados por pasta — 424 de 432 em escopo casa, agrupados
- [x] `chats` em `~/Documentos/codesnippets/PORTFOLIO` lista só daquele repo — 164
- [x] `chats --all` lista tudo — 432 (fase 1) / 791 (fase 2)
- [x] `chats open <key> --native` executa `codex resume <id>` / `opencode -s <id>` no `cwd` certo
      (verificado com stubs de `codex`/`opencode` no PATH: argv + cwd corretos)
- [x] `chats --format json` é JSON válido
- [x] `tests/test_escopo.py` verde — 32 casos-limite
- **Esforço:** realizado em 1 ciclo

### Fase 2 — Demais fontes ✅ APROVADA 2026-10-06
**Escopo:** adapters `agy`, `devin`, `freebuff`, `gemini` + seus fallbacks.
- [x] `chats doctor` mostra 6/6 verdes (opencode 230 · codex 202 · agy 293 · devin 39 · freebuff 24 · gemini 2)
- [x] Dedupe devin: 39/39 marcados — **por `(título, diretório)`**, não pelo slug (ver 18.3)
- [x] Nenhum adapter derruba a CLI (teste: `opencode.DB` apontado pra `/nao/existe` → erro isolado, 5 fontes seguem)
- **Esforço:** realizado em 1 ciclo

### Fase 3 — Abrir no OpenCode ✅ APROVADA 2026-10-06
**Escopo:** `import_opencode.py`, menu 1/2/3/4, `export`, preview no fzf.
- [x] Import real conferido: conversa importada **aparece** em `opencode session list` no diretório certo
      (`cwd=/home/thiago/Documentos/codesnippets` → projeto `e120cb5f…`, visível ao rodar de lá)
- [x] Segunda importação detectada pelo ledger `~/.local/share/chats/imports.json` → mesmo id, sem duplicar
- [x] Devin: `ja_importada()` abre a sessão já existente (`imported_in_opencode`)
- [x] Recusa importar sem diretório válido e orienta `--dir` (caso do gemini, cuja pasta foi apagada)
- **Esforço:** realizado em 1 ciclo (validação do payload consumiu 3 rodadas)

### Fase 4 — Performance e dedupe fino ✅ APROVADA 2026-10-06 (v2)
**Escopo:** índice SQLite incremental, `sync`, dedupe cross-CLI por (cwd, 1ª frase, dia).

> **v2:** a v1 passou em todos os testes unitários, mas o caminho interativo estava
> quebrado — `chats` abria **tela em branco** num terminal real e saía com `rc=141`.
> Corrigido e agora validado de ponta a ponta em tmux. Detalhe em **18.13**.

- [x] `chats` < 150 ms em warm start; < 500 ms cold
- [x] **77 ms warm / 93 ms cold** (medido espiando os 348 arquivos-fonte com `posix_fadvise DONTNEED`)
      — antes: 262 ms warm / 2 290 ms cold → **3,4× e 25×**. `CHATS_SEM_INDICE=1` reproduz o antes.
- [x] `chats sync` por fonte (`atualizado` / `reescrevido` / `sem mudar` / `erro`) + `--force` + `--cli`
- [x] Dedupe fino: 13 grupos / 26 registros marcados `≡` — **todos devin↔opencode, 0 falso positivo**
      (auditado contra os 791 registros reais; 0 duplicatas novas entre outros CLIs hoje)
- [x] Índice nunca derruba a CLI: falha de leitura/gravação cai na fonte direta (teste cobre)
- [x] fzf: opções validadas contra a versão instalada, `stderr` livre, rc inesperado → lista numerada
- **Esforço:** realizado em 1 ciclo + 1 ciclo de correção · gatilho atendido (cold 2,2 s > 500 ms)

### Fase 5 — TUI (opcional) ⏸ NÃO INICIADA
Agrupamento visual em árvore, navegação por pasta. **Só se** o fzf não entregar o agrupamento.
- **Esforço:** 2–3 dias

---

## 14. Testes e validação

```sh
# unitários — stdlib (sem pytest: política de não adicionar dependência, AGENTS.md)
cd ~/Documentos/codesnippets/chats-cli && python3 -m unittest discover -s tests     # 91 testes, ~10 s

# smoke em dados reais (somente leitura)
chats doctor                              # 6 adapters, contagens, 0 erro
chats --all --format json | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))'   # 791
chats --all --cli devin --format tsv | wc -l                                               # 40 (39 + cabeçalho)
chats which                               # mostra raiz resolvida + grupos
cd ~/Documentos/codesnippets/PORTFOLIO && chats which | tail -4   # 164 no repo, 432 no total
cd /tmp && chats --no-pick                 # 2 (subpasta /tmp/opencode entra por descer de raiz)

# integração (import) — faz escrita no opencode; usar e limpar depois
python3 -c "import sys;sys.path.insert(0,'.');from chats_lib import registry,import_opencode as io; \
r=next(x for x in registry.scan()[0] if x.cli=='gemini');print(io.importar(r,'/home/thiago'))"
opencode session list --format json | grep -c '<id>'
opencode api delete /api/session/<id>      # + apagar a chave do ledger
```

**Testes de regressão da incidente:** `test_le_mensagem...` cobre leitura; o `cwd` do `open --native`
está em `TestPlanoNative.test_argv_do_codex_e_cwd_da_conversa` e o `location.directory` do import em
`TestPayload.test_estrutura_exigida_pelo_endpoint`.

---

## 15. Riscos e mitigações

| Risco | Impacto | Mitigação |
|---|---|---|
| DB de terceiro bloqueado (WAL/lock) | adapter falha | `mode=ro` + `busy_timeout=5000` + fallback (`devin list --json`, API do opencode, JSON espelho do agy) |
| `sessions.db` do devin com 4,6 GB | I/O lento | nunca varrer `message_nodes` no scan; só `sessions` (39 linhas) |
| `chat-messages.json` do freebuff com 19 MB | travamento | ler só `chat-meta.json` no scan |
| Formato de terceiro muda com update | adapter quebra | versão de schema detectada (`schema_version`/`cli_version`); `doctor` avisa; erro isolado por adapter |
| Escopo errado (fora do repo / monorepo) | lista "errada" | `chats which` transparente; flags `--all`, `--tree`, `--exact` |
| Privacidade (títulos/prompts sensíveis em listagem) | vazamento em tela/logs | preview truncado; `chats --no-preview`; nunca logar conteúdo |
| Escrever por engano num DB de terceiro | **perda de dados** | módulo de storage **somente leitura** por construção (abrir URI com `mode=ro`); nenhum `UPDATE`/`INSERT` no código |
| Import duplicado | poluir o opencode | idempotência 9.3 + dedupe 3.2 |
| Artefatos em `/tmp` sumindo no reboot | perda de backup/reversão | mover para `~/.local/share/chats/` (lição 11.4) |

---

## 16. Decisões — RESOLVIDAS + pendências menores

**Decidido (2026-10-06):**

1. ✅ **Nome do comando = `chats`** — instalação via symlink `~/.local/bin/chats → <projeto>/chats`.
   Descartado: `code` (ocupado pelo VS Code em `/usr/bin/code`); livres: `conv`, `cc`, `hist`.
2. ✅ **Picker = `fzf`** — já instalado (`/usr/bin/fzf`, 0.74.3). Fallback numerado + `read` quando
   não houver fzf ou não for TTY. A TUI própria fica como Fase 5 opcional (só se o agrupamento
   em árvore precisar de navegação visual).
3. ✅ **Entrega = Fases 1 + 2 + 3** — MVP com opencode+codex, depois as demais fontes,
   depois o import para o OpenCode. **Fase 4 ativada em 2026-10-06** por decisão do usuário
   (o gatilho "só se o scan medir > 500 ms" foi atendido no cold: 2 290 ms).
   Fase 5 (TUI) segue adiada: o fzf já entrega o agrupamento.

Itens a confirmar durante a implementação — **todos resolvidos** (ver seção 18):

4. ✅ Comando do **gemini** = `gemini --resume <índice>` — mas o CLI está **inativo** nesta máquina
   (`IneligibleTierError`, migrou pro Antigravity). Adapter lista e exporta; `native_resume=[]` com aviso.
5. ✅ Steps do **agy** = protobuf sem schema (`steps.metadata` BLOB). Listagem sai do
   `conversation_summaries.db`; a leitura completa devolve vazio e a prévia cai no `preview` da linha.
6. ✅ `~/.config/manicode/message-history.json` é `list[str]` de comandos digitados — **não** tem `cwd`.
   O fallback de cwd do freebuff ficou sendo `recent-projects.json` (path + lastOpened) por nome de pasta.

---

## 17. Referências rápidas (copiar/colar)

```sh
# listar sem tocar em nada
sqlite3 "file:$HOME/.local/share/opencode/opencode.db?mode=ro" \
  "select id,title,directory from session_v2 where parent_id is null order by time_updated desc limit 5;"

python3 -c "import sqlite3;c=sqlite3.connect('file:/home/thiago/.gemini/antigravity-cli/conversation_summaries.db?mode=ro',uri=True);print(c.execute('select conversation_id,title,workspace_uris from conversation_summaries limit 3').fetchall())"

python3 -c "import sqlite3;c=sqlite3.connect('file:/home/thiago/.local/share/devin/cli/sessions.db?mode=ro',uri=True);print(c.execute('select id,working_directory,title from sessions limit 3').fetchall())"

head -1 $(ls -t $HOME/.codex/sessions/*/*/*/*.jsonl | head -1)

# importar no opencode (fase 3)
opencode api post /api/experimental/session/import --data @payload.json
```

---

## 18. Descobertas da implementação (delta do que foi planejado)

Tudo abaixo foi apurado medindo na máquina; corrige ou detalha as seções 5, 9 e 16.

### 18.1 O payload do import exige `info.projectID`
`POST /api/experimental/session/import` valida `H({...te.fields, location})` e responde
`{"_tag":"InvalidRequestError","message":"Missing key\n  at [\"info\"][\"projectID\"]"}`.
Forma conferida contra um **export real**: `GET /api/experimental/session/<id>/export` →
`{data: {info, messages}}`.

- `messages` é a forma **projetada**, não o `Session.Message` completo:
  - user → `{id, time:{created}, text, type:"user"}`
  - assistant → `{id, time:{created,completed}, type, agent, model, content:[{type:"text",text}], cost, tokens}`
- `GET /api/location --param 'location={"directory":"..."}'` → `{directory, project:{id}}` e serve de
  `projectID` (é o mesmo caminho que o `opencode import` do SDK usa).

### 18.2 `location.directory` decide o projeto — mande o diretório PEDIDO
`GET /api/location` **canonifica qualquer subpasta para `/home/thiago`**. Se o payload usar esse
valor canônico, a sessão importada cai no projeto home (`cb6b4716`) com `directory=/home/thiago`
e some do escopo da subpasta. Enviando `location.directory` igual ao pedido, o servidor:
- grava `session_v2.directory` = pedido; **cria o projeto** se não existir (`e120cb5f…` para
  `Documentos/codesnippets`); e a sessão aparece em `opencode session list` rodado de lá.
`info.projectID` é exigido pelo schema mas **ignorado** na atribuição real do projeto.

### 18.3 Dedupe Devin↔OpenCode é por `(título, diretório)`
O importador histórico gerou `ses_devin<hash de 24 hex>`, **não** `ses_devin<slug>` — a hipótese do
slug (seção 3.2) estava errada. Títulos e diretórios batem 39/39 entre `sessions` e `session_v2`;
o fallback é título puro quando o diretório diverge.

### 18.4 Identidade do freebuff precisa do projeto
`id = <projeto>/<pasta>`: só o nome da pasta (`2026-10-05T20-53-05.352Z`) colidiu entre os projetos
`codesnippets` e `thiago`. O `--continue` continua recebendo só a pasta. `cwd` sai do
`run-state.json` (`sessionState.fileContext.cwd`), com fallback no `recent-projects.json`.

### 18.5 Leitura por CLI — detalhes de formato
| CLI | Detalhe que quebrava |
|---|---|
| opencode | `part` **não tem coluna `type`**; o tipo está em `json_extract(data,'$.type')` |
| codex | contexto injetado (`<environment_context>`, `The following is the Codex agent history`) vem com `role:user` → tratado como `system` e omitido da prévia |
| devin | cadeia principal = caminhar `main_chain_id` → `parent_node_id` até a raiz (3.112 nós → 19 reais); `idx_message_nodes_session` existe, 2 ms |
| freebuff | fala do agente em `blocks[].content` (não `text`), `type:'text'`, raciocínio em `textType:'reasoning'` (omitido) |
| gemini | papel vem em `type`, assistente se chama **`gemini`**; `content` é lista de `{text}` |
| agy | `steps.metadata` é protobuf sem schema → `carregar()` devolve `[]` |

### 18.6 `opencode api --data` só aceita JSON inline
`--data @arquivo.json` responde `Expected a valid JSON body` (HTTP 400). O importador monta o JSON
e passa direto no argv; payload > 8 MB é recusado antes de tentar.

### 18.7 Idempotência por ledger
`~/.local/share/chats/imports.json` (`{"<key>": "<session id>"}`). Ordem: marcador do dedupe →
ledger (confirmando que a sessão ainda existe) → `(título, cwd)`. Sem ledger a importação se repetia
às vistas largas, porque o `directory` gravado era o canônico.

### 18.8 Testabilidade do picker
- o comando do fzf saiu para `picker.comando_fzf(binpath)` (testável sem TTY)
- fzf dá pra testar sem UI com `fzf --filter=<texto>` — valida payload de 5 campos e o parse da key
- o fallback numerado é coberto passando `io.StringIO` no `sys.stdin`
- `script -qec` **não** serve de pty aqui: o filho não nasce com TTY e a CLI cai no modo tabela

### 18.9 Limitações conhecidas (documentadas na UI)
- agy: leitura/exportação completa indisponível (protobuf); prévia usa a coluna `preview`
- gemini: retomada indisponível (CLI inativo); o menu mostra o motivo em vez da opção
- freebuff: 17 das 24 conversas têm só `log.jsonl` (chats abortados) → entram sem conteúdo
- sem índice, o scan custava 262 ms warm / 2 290 ms cold (páginas do banco de 1,5 GB fora do
  cache); com a Fase 4 caiu para 77 ms / 93 ms (ver 18.10)

### 18.10 Índice incremental (Fase 4) — fingerprint por fonte
Cada fonte expõe `fingerprint()` barata; a fonte inteira só é relida quando ela muda.
Banco próprio `~/.local/share/chats/index.db` (gravação livre; os de terceiros seguem `mode=ro`).

| fonte | fingerprint | custo medido |
|---|---|---|
| opencode | `COUNT(*)+MAX(time_updated)` de `session_v2 WHERE parent_id IS NULL` | 0,8 ms |
| devin | `COUNT(*)+MAX(last_activity_at)` de `sessions` | 2,5 ms |
| agy | `COUNT(*)+MAX(last_user_input_time)` de `conversation_summaries` | 1,7 ms |
| codex | nº de arquivos + `mtime_ns` de `sessions/**` + os 2 índices | 2,2 ms |
| freebuff | nº de arquivos + `mtime_ns` de `projects/**` + `recent-projects.json` | 1,6 ms |
| gemini | nº de arquivos + `mtime_ns` de `tmp/**` (inclui `.project_root`) | 0,9 ms |
| **total** | | **~10 ms** |

- escrita = `DELETE` da fonte + `executemany` + linha de `fonte` **numa transação só**
- `ler()` devolve `None` (nunca dado pela metade) quando falta a linha de `fonte` ou o JSON está
  corrompido → força rescan
- as marcas `⇄`/`≡` são pós-processamento em memória e **nunca são persistidas**
- `CHATS_SEM_INDICE=1` lê tudo da fonte (serve de toggle de diagnóstico)

### 18.11 Prévia do devin: `ORDER BY rowid`, nunca `created_at`
Tres rotas para achar o 1º prompt de `message_nodes`, medidas nas 39 sessões:
- `... AND chat_message LIKE '%"role":"user"%' ORDER BY created_at` → **48 s**
- `... AND parent_node_id IS NULL ORDER BY created_at` (raiz) → **11 s** e a raiz é `system`
- `... ORDER BY rowid LIMIT 8` → **40 ms (1 ms/sessão)**, 39/39 com prompt ✅

### 18.12 Free tier do Zen valida o FORMATO do id da sessão (2026-10-07)
Desde ~2026-09-17 o Zen barra requests cujo `x-opencode-session` não é um id canônico
(`ses_<12 hex: timestamp ms invertido><14 base62>`, 30 chars — o que `Identifier.create` emite).
Sintoma: `FreeTierError: OpenCode's free tier can only be used from within OpenCode`.
Ids inventados (`ses_devin<...>`, `ses_`+24 base62 do `_id` antigo) reprovavam mesmo com UA correto.

- **correção:** `import_opencode._id()` gera `Identifier.create` de verdade (timestamp invertido
  do `created` da conversa, clamp em ~330 dias — a janela de plausibilidade do gate)
- **migração:** as 38 sessões `ses_devin*` foram reimportadas com id canônico via
  `export`→troca de ids→`import`→`delete` (backups em `~/.local/share/chats/migration-*`)
- **incidente:** `DELETE /api/session/<pai>` faz cascata para filhas — 19 sub-sessões de
  `ses_devindf74175b17ad0b401a8b` (transcripts de subagente) foram apagadas sem export prévio;
  irrecuperáveis (backup de 10-06 anterior à criação). Lição: exportar filhos ANTES do delete.
- **`opencode api` trunca exports grandes** — a sessão de 27 MB só saiu via HTTP direto
  (`curl -u opencode:<service.json.password> http://127.0.0.1:49374/...`); `import` com body >128 KB
  também não cabe em argv do `--data` — usar HTTP direto igualmente.

Sem índice de `(session_id, created_at)`: ordenar leria os blobs gigantes de `chat_response`.
O texto do prompt está em **`content`** (`text` é `null`); o papel em `role`. O scan agora lê
no máximo 8 nós por sessão e devolve `preview` — antes vinha vazio.

### 18.12 Dedupe fino por (cwd, 1ª frase, dia) — o que ele achou
- chave = diretório + 1ª frase normalizada (**≥ 30 caracteres**) + dia de início; corta só em
  `.`, `!`, `?` **seguidos de espaço** (cortar no primeiro ponto quebrava `revisa o ADR.md`)
- agrupa só quando cruza **2+ CLIs** — repetição dentro do mesmo CLI é repetição, não duplicata
- resultado em dados reais: **13 grupos / 26 marcas, 100% devin↔opencode**, todos com título idêntico
  → **0 falso positivo e 0 duplicata nova** além do dedupe por título (18.3)
- serve de sinal independente na linha `opencode`: `⇄` só aparece no lado de origem, então `≡` é o
  único marcador de "essa sessão tem gêmeo no devin" do lado opencode — e é a regra que pegaria um
  import cujo título divergiu do original

### 18.13 O fzf morria e a CLI morria junto (tela em branco) — v2 da Fase 4
Sintoma: `chats` num terminal real → **tela vazia**, `rc=141`, nada no stderr. Três defeitos
encadeados, nenhum visível sem um terminal de verdade (relato "not working" de 06/10 17h):

1. `--header-lines-position=top` **não existe no fzf 0.74.3** → `unknown option`, rc=2 logo no argv.
2. `subprocess.run(..., capture_output=True)` **capturava o stderr do fzf** → a mensagem de erro
   (e a UI) ficavam presas num pipe descartado; na tela só se via um piscar.
3. O entry point instala `SIGPIPE → SIG_DFL` (pra `chats … | head` limpo). O payload de 797 linhas
   passa de 64 KB, o fzf já tinha morrido, o `write` devolve EPIPE → **SIGPIPE com ação padrão
   mata o processo em silêncio** (141 = 128+13), antes de qualquer `except`.

Correções:
- `comando_fzf()` → `--header-first` (existe nesta versão e mantém o cabeçalho no topo);
- `stderr` do fzf **não** é capturado — só o `stdout`, que carrega a seleção;
- SIGPIPE ignorado só durante o spawn e restaurado (`picker._roda_fzf`);
- rc ∉ {0, 1, 130} → aviso no stderr + lista numerada, em vez de sair calado;
- `chats doctor` valida o argv do picker contra o fzf instalado (`status_fzf()`);
- testes: `test_opcoes_passam_na_validacao_do_fzf_instalado` — falha com o comando antigo
  (rc=2) e passa com o novo — mais `tests/test_doctor.py`.

Validação em terminal real (**tmux**, 180×45): fzf abre com cabeçalho e painel de preview,
busca filtra (797 itens), ENTER abre o menu, `0` volta e sai com `rc=0`; sem fzf no PATH a lista
numerada abre, escolhe e sai com `rc=0`; `chats --format json | head -3` continua limpo.

**Harness que não serve:** `script -qec` (o filho não nasce com TTY) e `pty.fork` (o fzf manda
queries de terminal — `\x1b[6n`, DA, DECRQM — e o pty sintético não responde, então ele não
chega a desenhar). **Só o tmux reproduziu o bug**, que é justamente por isso que as Fases 1–3
passaram nos testes e ainda assim falhavam na mão do usuário.
