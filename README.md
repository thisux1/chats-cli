# chats

Lista as conversas de **todos** os CLIs de IA da máquina numa só tela, escopadas à pasta em que
você está, e abre no CLI nativo ou importa pro OpenCode.

| fonte | de onde lê | retomar com |
|---|---|---|
| `opencode` | `session_v2` (SQLite, `mode=ro`) | `opencode -s <id>` |
| `codex` | 1ª linha de cada rollout | `codex resume <id>` |
| `agy` | `conversation_summaries.db` | `agy --conversation <id>` |
| `devin` | `sessions` + 8 nós p/ a prévia | `devin -r <id>` |
| `freebuff` | `chat-meta.json` | `freebuff --continue <pasta>` |
| `gemini` | `~/.gemini/tmp/*/chats` | — (CLI inativo: `IneligibleTierError`) |

Nunca escreve em banco de terceiro: toda abertura de SQLite é `mode=ro` + `busy_timeout`.

## Uso

```sh
chats                     # fzf com as conversas do projeto/pasta atual
chats                     # na home: tudo sob $HOME, agrupado por pasta
chats --all               # ignora o escopo
chats --tree              # agrupa por pasta mesmo fora da home
chats --cli codex,devin   # só algumas fontes
chats --since 7d          # janela temporal (7d, 12h, hoje, 2026-09)
chats --format json       # para script
chats --no-pick           # tabela sem abrir o fzf
chats which               # por que esta pasta mostra estas conversas
chats doctor              # saúde de cada fonte + compatibilidade do fzf
chats sync [--force]      # revalida as fontes e reescreve só o que mudou
chats preview <key>       # o que o fzf mostra no painel da direita
chats export <key> --to md|json [-o arquivo]
chats open <key> --native [--dir <caminho>]
```

`<key>` = `<cli>:<id>`, ex.: `codex:01a10d84-4186-…`, `freebuff:codesnippets/2026-10-05T20-53-05.352Z`.

Duas marcas na linha:

- `⇄` a conversa já existe no OpenCode (dedupe devin, por `(título, diretório)`)
- `≡` mesma conversa em 2+ CLIs — mesma pasta, mesma 1ª frase e mesmo dia

Sem argumento num TTY, `chats` abre o fzf; ENTER abre o menu:

```
1  ▶  Abrir no nativo        codex resume <id>
2  ⇄  Abrir no OpenCode      (importa e abre)
3  👁  Ler no pager
4  ⧉  Copiar id / comando
0  ⬅  Voltar
```

## Escopo por diretório

| onde você está | o que aparece |
|---|---|
| `~` | tudo sob `$HOME`, agrupado por pasta |
| pasta com repositório git | só a raiz do repo e os descendentes |
| pasta comum | ela e os descendentes |

`chats which` imprime a regra aplicada, a raiz resolvida e as contagens por pasta.

## Importar pro OpenCode

`chats open <key> --opencode` manda
`POST /api/experimental/session/import` com `{info, messages, location}` — `location.directory`
**é obrigatório**: sem ele a sessão cai no projeto `global` e some da listagem.

- diretório inexistente (ex.: gemini apontando pra repo apagado) → recusa e pede `--dir <caminho>`
- reimportar é no-op: ledger em `~/.local/share/chats/imports.json` + verificação de existência
- devin já importado (39/39) é detectado por `(título, diretório)` e a sessão existente é aberta

## Índice local (performance)

O que cada fonte devolve fica em `~/.local/share/chats/index.db` e só é relido quando a
**fingerprint** dela muda — contagem + `mtime` (arquivos) ou contagem + `MAX(coluna)` (SQLite),
**~10 ms no total**:

| | fonte direta | com índice |
|---|---|---|
| quente | 262 ms | **77 ms** |
| frio (páginas dos bancos fora da cache) | 2 290 ms | **93 ms** |

- `chats sync` revalida fonte a fonte: `atualizado` · `reescrevido` · `sem mudar` · `erro`
  (`--force` reescreve tudo; `--cli codex,devin` filtra)
- `CHATS_SEM_INDICE=1 chats …` ignora o índice — toggle de diagnóstico
- se o índice falhar (disco cheio, permissão, linha corrompida) o scan lê a fonte direta: ele é
  aceleração, nunca dependência. Bancos de terceiro seguem intocados (`mode=ro`)
- recomeçar do zero: `rm ~/.local/share/chats/index.db`

## Instalar e testar

```sh
ln -sf "$(pwd)/chats" ~/.local/bin/chats      # já feito
python3 -m unittest discover -s tests         # 91 testes, stdlib (sem pytest)
```

Estrutura: `chats_lib/{models,escopo,registry,store,render,picker,openers,cli,doctor,import_opencode}.py`
mais `chats_lib/adapters/{opencode,codex,agy,devin,freebuff,gemini}.py`. Um módulo por CLI expõe
só `CLI`, `FONTES`, `scan()`, `carregar()`, `resolver()`, `fingerprint()`; qualquer fonte que falhe
vira aviso e o resto segue.

Plano completo, decisões e descobertas da implementação: [`PLAN.md`](./PLAN.md).
