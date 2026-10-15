# Guia do workload — como modificar a federação na HPC Shelf

**Objetivo (1 frase):** saber, em 2 minutos, *quais arquivos* mexer quando você
quer mudar algo na camada de federação, sem decorar nada.

**Próximo micro-passo (2 min):** leia só a tabela da seção 3 ("Qual camada eu
mexo?") e pare. O resto fica aqui para quando precisar.

**Como voltar:** abra este arquivo e leia a seção 3.

| | |
| --- | --- |
| **Este documento** | Onde cada coisa vive e **como executar** |
| **Decisões** | [`HPC_SHELF_DECISIONS.md`](HPC_SHELF_DECISIONS.md) — limitações e o porquê |
| **Resultados** | [`HPC_SHELF_RESULTS.md`](HPC_SHELF_RESULTS.md) — números e evidências |
| **Plano no GCP** | [`HPC_SHELF_GCP_PLAN.md`](HPC_SHELF_GCP_PLAN.md) — o que provisionar e em que ordem |

---

## 1. A regra que resolve a paralisia

O repositório tem **três camadas**, e cada pergunta pertence a **uma** delas.
Você quase nunca cria arquivo novo — quase sempre edita um dos três lugares:

```text
flower_app/     →  COMPORTAMENTO   (o que a federação faz)
libs/           →  ACORDO + MODELO (o que foi combinado, como é a forma)
env/hpcshelf/   →  EXECUÇÃO        (onde e como isso roda na plataforma)
```

A separação é deliberada: mudar a estratégia de agregação **não toca** em `libs/`
nem em `env/`. Se você sentir que precisa tocar nas três ao mesmo tempo, pare —
provavelmente são duas mudanças.

---

## 2. Onde cada coisa vive

| Área | Arquivos | Papel |
| --- | --- | --- |
| Comportamento | `flower_app/server_app.py`, `client_app.py` | ServerApp / ClientApp |
| Dados e non-IID | `flower_app/task.py` | Partição por paciente (`uniform`, `label-skew`), hold-out |
| Modelo | `flower_app/model.py` | Arquitetura + termo proximal FedProx |
| Agregação | `flower_app/strategies.py` | FedAvg / FedProx |
| Privacidade | `flower_app/privacy.py` | DP com mecanismos oficiais do Flower |
| Explicabilidade | `flower_app/explain.py` | XAI (suíte `pyhealth.interpret`) |
| Contrato | `libs/federation_contracts/contracts.py` | `RunManifest`, `FederationContract`, `PrivacyPolicy` |
| Modelo lógico | `libs/federation_components/model.py` | Unidades, interfaces, ligações, realizações |
| Verificador | `libs/federation_components/conformance.py` | Códigos `M001`–`M106` |
| **Braço 1** (default) | `env/hpcshelf/arms/grouped/` | Descritores, imagens, validador, publicador |
| **Braço 2** (`3 níveis`) | `env/hpcshelf/arms/three-level/` | Mesma federação, 1 processo por unidade |
| Hosts (compartilhado) | `env/hpcshelf/hosts.yaml` | Inventário sintético |
| Runtime local | `podman-compose.yml`, `env/incus/`, `env/podman/`, `Containerfile.superexec` | Pré-plataforma, uma máquina |

Dentro de cada braço: `components/` (descritores), `applications/` (placement),
`images/` (Containerfile + supervisores), `validate.py` (roda o validador/planner
**da plataforma**).

---

## 3. Qual camada eu mexo?

| Você quer mudar… | Arquivos | Prova que fecha |
| --- | --- | --- |
| Modelo (arquitetura / XAI) | `flower_app/model.py`, `task.py` | `scripts/test.sh` |
| Estratégia de agregação | `flower_app/strategies.py`, `server_app.py` | `tests/test_fedavg_identity.py` |
| Partição non-IID | `flower_app/task.py` | `tests/test_partitioning.py` |
| DP | `flower_app/privacy.py` + `dp-mode` no config | `tests/test_strategies_privacy.py` |
| Contrato / manifesto | `libs/federation_contracts/contracts.py` | `tests/test_contracts.py` |
| **Topologia lógica** (unidades, interfaces) | `libs/federation_components/model.py` | `python -m libs.federation_components` |
| **Descritores** (nº de hospitais, ocupação, portas, env) | `env/hpcshelf/arms/grouped/components/*/component.yaml`, `applications/*.yaml`, `hosts.yaml` | `scripts/validate_hpcshelf.sh` |
| Imagem da unidade | `env/hpcshelf/arms/grouped/images/*` | `scripts/build_hpcshelf_images.sh` + `smoke_…` |
| Publicação | `env/hpcshelf/arms/grouped/publish.py` | `scripts/publish_hpcshelf_images.sh` |
| Run local (sem plataforma) | `scripts/simulate.sh` | `scripts/test.sh` |

### Criar uma arquitetura nova — o caminho curto

"Arquitetura nova" aqui = **uma realização física diferente** do mesmo modelo
lógico, ou um modelo lógico novo. São no máximo 4 arquivos:

1. `libs/federation_components/model.py` — some uma `Realization` (ou um `Unit`).
2. `env/hpcshelf/arms/grouped/components/<nome>/0.1/component.yaml` — as unidades.
3. `env/hpcshelf/arms/grouped/applications/<nome>.yaml` — placement e réplicas.
4. `env/hpcshelf/hosts.yaml` — hosts (se mudar o número).

Depois: `scripts/validate_hpcshelf.sh`. Se ele fica verde, a plataforma aceita.

---

## 4. Estado atual: os três braços

A federação é **um modelo lógico** realizado de **três** formas possíveis — os
braços. Eles existem para medir o custo de separar o processo Flower do processo
de transporte. O conceito e o trade-off completos estão em
[`HPC_SHELF_DECISIONS.md`](HPC_SHELF_DECISIONS.md) §4; aqui fica só o operacional:

| Braço | Diretório | Estado | Como provar |
| --- | --- | --- | --- |
| **1. agrupado** (default) | `env/hpcshelf/arms/grouped/` | construído | `validate_hpcshelf.sh` (28) + `smoke_hpcshelf_images.sh` (16) |
| **2. 3 níveis** | `env/hpcshelf/arms/three-level/` | construído e medido | `validate_hpcshelf_three_level.sh` (39) + `smoke_hpcshelf_three_level.sh` (22) |
| **3. 3 níveis + `scope: parent`** | — | bloqueado na plataforma | — (depende do conceito de serviço interno) |

O **braço 1 é o default**: mantém o `appio` (9091/9094) em loopback, e só o
`fleet` (9092) cruza a fronteira da instituição. O braço 2 é a alternativa
medida: um processo por unidade, mas **publica o `appio` na VPN**. O braço 3 é o
que zeraria esse custo, e não pode ser construído enquanto `ServiceDefinition`
não tiver `scope: parent`.

---

## 5. O que eu nunca toco

| Nunca | Por quê |
| --- | --- |
| `hpcshelf-model` (plataforma) | Importado **read-only** via `HPCSHELF_MODEL_ROOT`. O patch foi retirado. |
| `data/` (dados de paciente) | Só o MIMIC-IV Demo. **SESA-CE nunca entra em imagem nem em commit.** |
| `build/`, `output/` | Candidatos e resultados, gitignored. Não versionar. |
| `flower_app/` para mudar topologia | Topologia vive em `env/`; o comportamento é reusado como está. |

---

## 6. Limitações que causam dor (decore estas)

As regras da plataforma que **decidem** o desenho. A lista completa (R1–R9) com a
evidência no código está em
[`HPC_SHELF_DECISIONS.md`](HPC_SHELF_DECISIONS.md) §2.

| Regra | O que ela proíbe |
| --- | --- |
| **R9 — uma unidade = um `application.command`** | É por isso que existem os supervisores e o agrupamento do braço 1. Não dá para ter 2 comandos numa unidade. |
| **R3 — dependência só dentro do mesmo componente** | `hospital → hub` só funciona porque os dois estão em `flower-federation`. |
| **R6 / C017** | Uma réplica interna por réplica de host, dentro de uma composição. O `overlap` é 1:1. |
| **R7 / C007** | Toda unidade filha precisa de `overlap`. |
| **R8 / D004** | `placement` só referencia unidade **raiz**. |
| **C002** | Dependência apontando para fora do componente = inválido. |
| **M103** | `appio` (9091 / 9094) **nunca** cruza fronteira — invariante defendida. |
| **Porta** | Só `fleet` (9092) cruza unidade. Não publique 9091/9093/9094/9095. |
| **Digest** | Base 1.4 reusada **por digest exato**; imagem reconstruída ganha hash novo. |

---

## 7. As 3 superfícies de configuração

Configuração não está num lugar só. São três, e cada uma tem um dono:

| Superfície | Arquivo | O que muda ali |
| --- | --- | --- |
| Config do run | `pyproject.toml` → `[tool.flwr.app.config]` | Nº de partições, estratégia, `dp-mode`, rounds, épocas |
| Env da unidade | `component.yaml` → `application.environment` | `FLWR_NUM_ROUNDS`, `PYHEALTH_STRATEGY`, `PYHEALTH_DP_MODE`, `PYHEALTH_PARTITION_SCHEME` |
| Placement | `applications/*.yaml` + `hosts.yaml` | Réplicas e host de cada unidade |

Identidade por réplica (`partition-id`) **não** se configura: vem do plano da
unidade (`plan.replica`), lido pelo supervisor. Nunca ponha isso no descritor —
o binding é compartilhado e daria a mesma partição a todos.

---

## 8. O loop de validação (isto *é* a definição de "pronto")

Rode na ordem. Cada comando responde uma pergunta diferente:

```bash
python -m libs.federation_components        # a forma lógica está consistente? (2/2)
scripts/validate_hpcshelf.sh                # a plataforma aceita os descritores? (28 checks)
scripts/build_hpcshelf_images.sh            # as imagens constroem?
scripts/smoke_hpcshelf_images.sh            # as unidades funcionam? (16 checks)
scripts/publish_hpcshelf_images.sh --registry localhost:5000 --insecure   # ensaio
scripts/test.sh                             # a suíte do projeto passa?

# O braço `3 níveis` (mesma federação, 1 processo por unidade) tem os seus:
scripts/build_hpcshelf_three_level.sh              # 4 imagens + guarda de papéis (9)
scripts/validate_hpcshelf_three_level.sh           # descritores + plano + custo (39)
scripts/smoke_hpcshelf_three_level.sh              # unidades, sem plataforma (22)
```

`validate_hpcshelf.sh` e o `smoke` **precisam** do checkout da plataforma e de
um venv com `pydantic==2.13.5` + `PyYAML==6.0.3` (não o `.venv` do projeto).
Para reproduzir exatamente os números, ver
[`HPC_SHELF_RESULTS.md`](HPC_SHELF_RESULTS.md) — inclusive a ressalva do
`scripts/test.sh` (só a invocação **sem argumento** funciona).

---

## 9. Regras de commit que vão te pegar

De `COMMIT_POLICY.md`, as que valem para trabalho de arquitetura:

1. **Mudança arquitetural atualiza o diagrama Mermaid** em `docs/ARCHITECTURE.md`
   **no mesmo commit.**
2. **Nova/alteração de estratégia cita a referência** (FedAvg: McMahan 2017;
   FedProx: Li 2018/2020).
3. **Mudança de privacidade declara o impacto** no rodapé (`Privacy: …`).
4. **Resultado reportado traz o `RunManifest`.**
5. Um commit = uma mudança lógica.

## Referências

- [`HPC_SHELF_DECISIONS.md`](HPC_SHELF_DECISIONS.md) — limitações (R1–R9), os três
  braços e as decisões.
- [`HPC_SHELF_RESULTS.md`](HPC_SHELF_RESULTS.md) — números e evidências.
- [`HPC_SHELF_ORIENTADOR_REQUEST.md`](HPC_SHELF_ORIENTADOR_REQUEST.md) — o que
  falta para publicar.
- [`HPC_SHELF_GCP_PLAN.md`](HPC_SHELF_GCP_PLAN.md) — execução do braço 2 em VMs
  no GCP: requisitos, ordem, custo e as rotas para o round.
- `env/hpcshelf/README.md` — artefatos dos dois braços.
- `env/incus/PORTS.md` — inventário de serviços e portas.
