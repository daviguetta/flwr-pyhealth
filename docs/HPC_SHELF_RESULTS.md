# HPC Shelf — resultados

O que foi **provado**, com número e comando. As decisões que levaram até aqui
estão em [`HPC_SHELF_DECISIONS.md`](HPC_SHELF_DECISIONS.md); como reproduzir, em
[`HPC_SHELF_WORKLOAD_GUIDE.md`](HPC_SHELF_WORKLOAD_GUIDE.md).

> Regra deste arquivo: **nunca declarar mais do que a prova estabelece.** Cada
> resultado vem com o comando que o produziu e, quando há, o controle negativo.

## Baseline verde (atual)

Re-verificado em 2026-10-03, sem mudança de código. É o que uma mudança precisa
manter para não regredir.

| Prova | Resultado | Comando |
| --- | :---: | --- |
| Desenho aceito pela plataforma (braço 1) | **28/28** | `scripts/validate_hpcshelf.sh` |
| Imagens do braço 1 funcionam | **16/16** | `scripts/smoke_hpcshelf_images.sh` |
| Conformidade com o modelo de componentes | **2/2** | `python -m libs.federation_components` |
| Suíte do projeto | **64 passed, 11 deselected** | `scripts/test.sh` (sem argumento) |
| Braço 2 — descritores + plano + custo | **39/39** | `scripts/validate_hpcshelf_three_level.sh` |
| Braço 2 — unidades, sem plataforma | **22/22** | `scripts/smoke_hpcshelf_three_level.sh` |
| Braço 2 — build + guarda de papéis | **9/9** | `scripts/build_hpcshelf_three_level.sh` |
| Braço 2 — publicação ensaiada | **31/31** | `scripts/publish_hpcshelf_three_level.sh --registry localhost:5000 --insecure` |

> **Ressalva do `test.sh`.** O script não remove `${1}`, então o pytest recebe a
> seleção como caminho: `test.sh fast`, `test.sh slow` e `test.sh all` resultam
> em `no tests ran`. Só a invocação **sem argumento** produz o 64 acima.

## Resultados por fase

### Fase 0-C — Reconciliação

`python -m libs.federation_components`:

```text
model agrees with itself (provides/requires vs bindings)
env/hpcshelf/arms/grouped (project descriptors) conforms
catalog_data/components/federated-learning (platform catalogue) conforms
Result: 2 realizations, all conforming
```

- Modelo versionado em `libs/federation_components/model.py`
  (`COMPONENT_MODEL_VERSION = "1.0.0"`): 2 componentes, 4 unidades, 3 interfaces
  (`appio`, `fleet`, `control`), 3 ligações.
- Verificador em `libs/federation_components/conformance.py`, com o invariante
  `M103` (`appio` não cruza fronteira) e a fronteira de dados `M105`.
- **Os dois artefatos conformam**: `env/hpcshelf` (`hub`/`hospital`) e o catálogo
  da plataforma (`aggregator`/`client`) reduzem ao **mesmo** modelo.
- `pytest tests/test_federation_components.py` → **16 passed**, um controle
  negativo por código (`M001`–`M003`, `M101`–`M106`).
- `./scripts/test.sh` → **56 passed, 11 deselected** (40 antes, +16).

### Fase 1 — Modelo lógico congelado

Satisfeita pela 0-C. Evidência: modelo em `model.py`, diagrama Mermaid em
`docs/ARCHITECTURE.md` §2.1, distinção lógico × físico registrada com as duas
grafias de realização nomeadas (`hub`/`hospital` e `aggregator`/`client`).

### Fase 2 — Identidade por réplica

- `HPCSHELF_UNIT_PLAN` → `/etc/hpcshelf/unit-plan.pb` legível dentro das nossas
  imagens: `/opt/hpcshelf/venv` traz `common_pb2.UnitPlan`
  (`hpcshelf.control.v1.UnitPlan`), protobuf 7.36.1.
- Plano sintético (`replica=1`) lido de volta → `partition-id=1` derivado **sem
  patch**.
- Plano (`replica=1`) + `PYHEALTH_PARTITION_ID=0` conflitante → venceu o plano:
  `node-config='partition-id=1'`.
- `scripts/smoke_hpcshelf_images.sh` → **10 passed, 0 failed** (antes 8/8). Os
  dois checks novos:

  ```text
  ✓ a hospital derived its partition from its own unit plan
  ✓ the plan beat the conflicting PYHEALTH_PARTITION_ID override
  ```

### Fase 3 — Descritores do modelo-alvo (2026-09-25)

`scripts/validate_hpcshelf.sh` → **28 passed, 0 failed** (25 antes).

| Variante | Co-localização | Dependência | Resultado |
| --- | :---: | :---: | --- |
| 4 unidades num componente | recusada (R6) | resolve | `C017` ×3 |
| 2 componentes, composições separadas | permitida | recusada (R3) | `C002` ×2 |
| `comunicacao` {link, node} sozinho | — | resolve | **válido** |

Duas conclusões que a execução produziu e o argumento não produzia:

1. **O bloqueio é especificamente `appio`.** `fleet` sobrevive à fronteira de
   componente quando as duas pontas estão dentro dele — `comunicacao` valida
   sozinho. Só `appio` não passa.
2. **A separação obriga o AppIO a sair do loopback.** Isso não infringe
   `env/incus/PORTS.md`, que enuncia a regra no nível da **instituição** (Incus),
   não do contêiner.

### Fase 3 reaberta — braço 2 (`3 níveis`) (2026-10-05)

`env/hpcshelf/arms/three-level/`: 3 descritores (`comunicacao`, `exec`,
`three-level-root`), a aplicação, 4 imagens de unidade e dois provadores. O plano
materializa **9 unidades em 3 níveis** — `institution[i]` (Incus) → `exec-*`
(Podman) → `link`/`node` (Podman). A medição é feita pelo **mesmo**
`EndpointPublisher` nos dois braços, no mesmo processo:

| Braço | Unidades | `appio` publicado | Endereço | Imagem de transporte |
| --- | :---: | :---: | --- | --- |
| `agrupado` (braço 1) | 6 | **0** | loopback dentro do contêiner | n/a (mesma imagem) |
| `3 níveis` (braço 2) | 9 | **3** | `10.201.0.{1,2,3}:30000` | sem corpus, sem stack de ML (~1,1 GB vs ~7,3 GB) |

Três conclusões que a execução produziu:

1. **A ligação vertical não é declarável, e isso agora é um controle negativo.**
   Declarar `exec-server -> link.appio` como `dependencies` falha com **C002**. O
   endereço só existe porque o pai lê o próprio plano
   (`UnitPlan.children[].services[]`) e disca `127.0.0.1:<published_port>` —
   mecanismo exercitado pelo smoke, inclusive o caso de não haver filho (falha em
   vez de ficar ocioso).
2. **O que a separação compra é verificável no artefato.** `flower-link` /
   `flower-node` não contêm `data/`, `flower_app`, torch nem pyhealth: as
   unidades de transporte não conseguem ler um registro. No braço 1 isso é
   impossível por construção.
3. **Uma federação inteira num só host não é expressável neste braço.** A
   composição aninhada comporta uma réplica interna por réplica de host, então
   `exec-server` e `exec-client` no mesmo `institution` é recusado com **C017**.
   Um host = um papel = uma fronteira de dados.

Provas: build + guarda de papéis **9/9**, `validate_hpcshelf_three_level.sh`
**39/39**, `smoke_hpcshelf_three_level.sh` **22/22**. O braço **não** é registrado
como `Realization` em `libs/federation_components`: ele gasta `M103` por
construção, e um verificador com exceção para o caso que ele existe para pegar
seria mais fraco.

### Fase 4 — Imagens das unidades (2026-09-25)

- Ambas as imagens do braço 1 constroem a **7,1 GiB**:

  ```text
  localhost/flower-hub:0.1.0       sha256:d8900cb086812b898ee3be212b42474591bfb93cdeaf0c0d830e8a1a70ce751f
  localhost/flower-hospital:0.1.0  sha256:d49ec35bfc21e12c446c817c5b7b14f0ccfa6a8b07ef4d040010d05c4f061230
  ```

- `scripts/smoke_hpcshelf_images.sh` → **16 passed, 0 failed** (10 antes). Os
  seis checks novos substituem o que era prosa: dois interpretadores (protobuf
  7.x do UnitAgent vs 6.x do Flower), venv do UnitAgent recriado e não copiado,
  `HPCSHELF_PODMAN_RUNTIME=mock` com ausência do binário podman.

### Fase 5 — Prova (2026-09-25)

- `scripts/validate_hpcshelf.sh` → **28/28**, `scripts/smoke_hpcshelf_images.sh`
  → **16/16**.
- **Nenhum round federado completo ainda** — a ressalva continua de pé.

**A propriedade.** Com um passo local por rodada e ponderação por `num-examples`,
uma rodada de FedAvg *é* um passo de SGD centralizado — identidade, não
aproximação:

```text
theta_f = sum_i (n_i/N) (theta_0 - eta grad L(B_i))
        = theta_0 - eta grad L(B) = theta_c
```

- `tests/test_fedavg_identity.py` → **8 passed**.
- Gap medido entre federado e centralizado: **~3e-8** (ruído de float32) contra
  tolerância de `1e-5`; o passo move os parâmetros em ~0.16 — não passa por
  vacuidade.
- Usa código de produção, não reimplementação: o particionamento vem de
  `flower_app.task.shard`, a chave de ponderação de
  `flower_app.strategies.build_strategy` (o teste **consome** a configuração), e
  a agregação é `aggregate_arrayrecords` do Flower.

**Controles negativos — um por coisa que um run federado pode errar:**

| Controle | O que prova | Gap medido |
| --- | --- | --- |
| chave de ponderação constante, partições desiguais | ponderação errada quebra | `2.0e-2` |
| uma partição treinada duas vezes | nó treinando em dado que não é dele quebra | > `1e-5` |
| dois passos locais por rodada | a identidade é por passo; não sobrevive à composição | > `1e-5` |
| learning rate zero | a guarda de movimento não é decorativa | recusa |

O último é um meta-controle: com `lr=0` os dois lados são iguais a `theta_0` e a
identidade vale **por vacuidade**. `MIN_MOVEMENT` existe para recusar isso.

### Publicação — caminho ensaiado (2026-09-25)

`scripts/publish_hpcshelf_images.sh` faz o caminho inteiro contra um registry
local (`registry:2` em `127.0.0.1:5000`): publica as imagens, lê de volta o
digest que o **registry** reporta, escreve a árvore de catálogo e a verifica com
o código da própria plataforma. **18 verificações, 0 falhas.**

- As duas imagens foram publicadas, e o digest foi **conferido de forma
  independente** via `HEAD /v2/…/manifests/…` — não apenas pelo `--digestfile`
  do cliente.
- O `FilesystemCatalog` da plataforma leu os dois componentes, aceitou a
  integridade, confirmou o `descriptor_digest` e fixou cada imagem por digest.
- O `DeploymentPlanner` **planejou a partir do catálogo publicado**: 3 Incus + 3
  Podman, com a imagem raiz amarrada ao digest do arquivo Incus da plataforma.

**Comportamento revelado.** `CatalogComponentArtifact` **recusa** um artefato cuja
referência de imagem divirja do campo `image` do descritor. Publicar em outro
registry, portanto, **reescreve o descritor publicado** e muda o
`descriptor_digest`. No registry declarado (`catalog.hpcshelf.org`) o descritor
não é reescrito, e o digest é o registrado no repositório:

```text
flower-federation:0.1    sha256:2f7772db5a9b236dfa3d6cd707e2929f38db7ae6f091f961d70b1e7837e96d93
```

### Publicação — braço 2 (3 níveis) ensaiado (2026-10-15)

O braço 2 ganhou o seu próprio publicador, e ele **não** é uma cópia do braço 1.
As quatro unidades deste braço vivem em **dois** componentes, então o mapa
unidade → repositório é **por componente**. O `ROLES` global do braço 1 daria
`KeyError` aqui: `link` não existe em `exec`, e `exec-server` não existe em
`comunicacao`. O publicador tem um guarda que compara esse mapa com os
descritores **antes** de qualquer push.

`scripts/publish_hpcshelf_three_level.sh --registry localhost:5000 --insecure`
→ **31 verificações, 0 falhas**, contra o mesmo registry local (`registry:2` em
`127.0.0.1:5000`) usado pelo braço 1:

- as quatro imagens foram publicadas, com o digest conferido de forma
  independente via `HEAD /v2/…/manifests/…`;
- **três** `artifact.json` foram escritos, um por componente:

  ```text
  comunicacao:0.1        sha256:a793b4b40870fc966d0db7d61e0bf0303319006a8154b95f409cf0b1f6187aa5
  exec:0.1               sha256:be3ebea3f6b99950041a0f95ccccdfea7464aba6ddc9dcdcb2d604c8299062fc
  three-level-root:0.1   sha256:b2224a06e05aef5bd8c17d68a503865fcfb575c0c05c341df4e18004ec016316
  ```

- o `FilesystemCatalog` da plataforma leu os três, aceitou a integridade,
  confirmou cada `descriptor_digest` e fixou **todas as cinco** unidades de
  imagem por digest;
- o `DeploymentPlanner` planejou a partir do catálogo publicado: **3 Incus + 6
  Podman**, com os 6 descendentes resolvendo exatamente as 4 imagens empurradas —
  a asserção que separa este braço do braço 1;
- o componente raiz **reusa** `hpcshelf-unit-base` por digest exato, incluindo o
  arquivo Incus de 501 MB — nada foi reconstruído.

Como no braço 1, publicar no registry de ensaio **reescreve o descritor**
(retarget para `localhost:5000`) e muda o `descriptor_digest`; o script avisa em
voz alta. Os digests acima são **do ensaio**, não do catálogo de produção.

### Contagem de hosts do braço 2 (2026-10-15)

Pergunta de custo para o GCP: o braço precisa de 3 hosts, ou duas instituições
cabem numa máquina? O planner da plataforma foi rodado sobre o catálogo
publicado, offline:

| Configuração | Resultado |
| --- | :---: |
| 3 hosts, uma instituição cada | **aceito** — 9 unidades, 3 hosts distintos |
| 2 hosts, `institution[1]` e `institution[2]` no mesmo host | **aceito** — 9 unidades, 2 hosts distintos |

`C017` **não** dispara na segunda linha: cada `institution` é uma raiz separada,
com composição aninhada própria, então os escopos de ocupação são independentes.
A separação em 3 hosts **não é exigência da plataforma** — é exigência do braço:
com 2 hosts, as duas `exec-client`, as únicas unidades que leem prontuário, ficam
na mesma máquina física, e a contenção de dano que justifica a separação deixa de
valer. Decisão proposta e o resto do plano em
[`HPC_SHELF_GCP_PLAN.md`](HPC_SHELF_GCP_PLAN.md) §5.

## O que a prova NÃO estabelece

- **Não prova que isso implanta.** O inventário de hosts é sintético e nada foi
  rodado contra o control plane da plataforma. É prova de desenho e de fiação,
  não de deploy.
- **Nenhum round federado completo.** O teste prova registro, fiação e álgebra da
  agregação — não um run de ponta a ponta. Só cai quando a Fase 6 fechar.
- **O braço 2 não é registrado como conforme** — ele viola `M103` por construção.

## Log de progresso

Comando e saída, não opinião.

| Data | Fase | Evidência | Resultado |
| --- | --- | --- | --- |
| 2026-10-15 | 2 (braço 2) | `env/hpcshelf/arms/three-level/publish.py` + `scripts/publish_hpcshelf_three_level.sh` | **31/31** — 4 imagens publicadas com digest do registry; **3** `artifact.json`; `FilesystemCatalog` aceita os 3; plano 3 Incus + 6 Podman usando exatamente as 4 imagens; raiz reusa `hpcshelf-unit-base` por digest |
| 2026-10-15 | — | planner sobre o catálogo publicado, com 2 inventários | **ambos aceitos** — 3 hosts e 2 hosts dão 9 unidades; `C017` não dispara com duas instituições no mesmo host |
| 2026-10-05 | 3 (reaberta) | `env/hpcshelf/arms/three-level/`: 3 descritores + aplicação + `validate.py` | **39/39** — 9 unidades em 3 níveis; `fleet` injetado; `appio` publicado em `10.201.0.{1,2,3}:30000`; **C002** no controle negativo da ligação vertical declarada; **D012**/**C017** ainda policiam o `overlap` |
| 2026-10-05 | 4 (braço 2) | `Containerfile.flower-comm` + `supervise-{comm,link,node}.sh`; build com guarda de papéis | **9/9** — transporte sem corpus/torch/pyhealth/`data/`, 4 camadas distintas, 1 papel por imagem; `flower-link`/`flower-node` em **1,1 GB** contra **7,3 GB** do `exec` |
| 2026-10-05 | 5 (braço 2) | `scripts/smoke_hpcshelf_three_level.sh` | **22/22** — `appio` em `0.0.0.0` (não loopback); 2 nodes registram no `link` com partição própria; node recusa sem `SUPERLINK_HOST` e sem identidade; pai lê a porta do filho do próprio plano e falha rápido sem filho |
| 2026-10-03 | — | piso do Python: `>=3.13` → `>=3.12`, `.python-version`, ruff `py312` | pré-requisito do braço 2 (o nível do meio aninha Podman e vem de `podman-unit-base`, que é 3.12) |
| 2026-10-03 | — | suíte em 3.12.13 | **64 passed, 11 deselected** e **75 passed** — idêntico ao 3.13 |
| 2026-10-03 | — | `uv lock` + `git diff uv.lock` | re-lock necessário; **nenhuma versão de pacote mudou** (torch 2.7.1, numpy 2.2.6, pyhealth 2.0.1, flwr 1.34.0) |
| 2026-10-03 | — | `scripts/validate_hpcshelf.sh` contra o clone canônico | **28/28** |
| 2026-10-03 | — | `scripts/smoke_hpcshelf_images.sh` | **16/16** |
| 2026-10-03 | 3 | `EndpointPublisher.build_publications` + `client_server_verifier._target` | reabertura da Fase 3 registrada |
| 2026-10-03 | — | re-verificação do baseline, sem mudança de código | **28/28**, **16/16**, **2/2 conformes**, **64 passed** |
| 2026-10-03 | — | defeito em `scripts/test.sh`: `${1}` não é removido | `test.sh fast/slow/all` → `no tests ran`; só a invocação sem argumento funciona |
| 2026-09-25 | 6 | `catalog_server.py` local + `hpcshelf_client.py validate/plan` | **validate ✅ e plan ✅ offline**; `preflight` ❌ em `input_invalid` (falta mTLS) |
| 2026-09-25 | 5 | `tests/test_fedavg_identity.py` | **8 passed** — identidade FedAvg ≡ SGD centralizado, gap `3e-8`; 4 controles negativos + meta-controle |
| 2026-09-25 | 4 | `scripts/smoke_hpcshelf_images.sh` com os 6 checks de invariante de imagem | **16 passed, 0 failed** (10 antes) |
| 2026-09-25 | 3 | decisão: variante 2 não perseguida; invariante fixado no nível contêiner | agrupamento passa a propriedade defendida |
| 2026-09-25 | 3 | `env/hpcshelf/arms/grouped/model_split.py` no validador | 4 unidades num componente → `C017` ×3; 2 componentes → `C002` ×2; `comunicacao` sozinho → **válido** |
| 2026-09-25 | 3 | `scripts/validate_hpcshelf.sh` | **28 passed, 0 failed** (25 antes) |
| 2026-09-25 | 0-C | `python -m libs.federation_components` | modelo auto-consistente; **2 realizations, all conforming** |
| 2026-09-25 | 0-C | `pytest tests/test_federation_components.py` | **16 passed**, um controle negativo por código (`M001`–`M003`, `M101`–`M106`) |
| 2026-09-25 | 0-C | `./scripts/test.sh` | **56 passed, 11 deselected** (40 antes, +16) |
| 2026-09-25 | 1 | `docs/ARCHITECTURE.md` §2.1 + diagrama Mermaid | distinção lógico × físico registrada |
| 2026-09-25 | 2 | `grep HPCSHELF_UNIT_PLAN` no UnitAgent | a plataforma já injeta o plano para toda unidade, raiz **e** aninhada |
| 2026-09-25 | 2 | `podman run … python -c 'import common_pb2'` na nossa imagem | `common_pb2.UnitPlan` legível, protobuf 7.36.1 |
| 2026-09-25 | 2 | plano sintético (`replica=1`) lido de volta | `partition-id=1` derivado sem patch |
| 2026-09-25 | 2 | `scripts/smoke_hpcshelf_images.sh` (imagem do hospital reconstruída) | **10 passed, 0 failed** (antes 8/8) |
| 2026-09-25 | 2 | plano (`replica=1`) + `PYHEALTH_PARTITION_ID=0` conflitante | venceu o plano: `node-config='partition-id=1'` |
| 2026-09-25 | 0 | `scripts/validate_hpcshelf.sh` | 25 passed, 0 failed (baseline reconfirmado) |
| 2026-09-25 | 0 | `git status` em `hpcshelf-model` | **sujo**: `fl_unit/`, `catalog_data/components/federated-learning/`, `root-fl/` não commitados |

## Referências

- [`HPC_SHELF_DECISIONS.md`](HPC_SHELF_DECISIONS.md) — as decisões por trás destes números.
- [`HPC_SHELF_WORKLOAD_GUIDE.md`](HPC_SHELF_WORKLOAD_GUIDE.md) — como rodar cada prova.
- `env/hpcshelf/arms/grouped/images/README.md` — formato do `artifact.json` e digests.
