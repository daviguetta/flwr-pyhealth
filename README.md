# PyHealth Federated Learning

Arcabouço de referência para **aprendizado federado em saúde**, aplicado ao
**alerta antecipado de deterioração clínica**. Construído sobre
[Flower](https://flower.ai/) (federação), [PyHealth](https://pyhealth.readthedocs.io/)
(pipeline clínico) e PyTorch.

O objetivo é treinar um modelo de alerta sem centralizar prontuários: cada
instituição treina localmente e apenas **pesos de modelo** e **métricas
agregadas** trafegam.

```
Pesos + métricas  →→→  agregação  →→→  novo modelo global
       ↑                                        ↓
   hospital A                              hospital B
   (dados ficam aqui)                  (dados ficam aqui)
```

## Sumário

- [Estado atual](#estado-atual)
- [Início rápido](#início-rápido)
- [Estrutura do repositório](#estrutura-do-repositório)
- [Os dois runtimes](#os-dois-runtimes)
- [Conceitos e referências](#conceitos-e-referências)
- [Dados](#dados)
- [Documentação](#documentação)
- [Limitações](#limitações)
- [Licença](#licença)

## Estado atual

| Capacidade | Situação |
| --- | :---: |
| Pipeline PyHealth ponta a ponta (MIMIC-IV demo) | ✅ |
| Federação real com partições distintas por nó | ✅ |
| Agregação **FedAvg** / **FedProx** | ✅ |
| Particionamento IID e **non-IID** (`label-skew`) | ✅ |
| **Privacidade diferencial** (DP central, mecanismos oficiais do Flower) | ✅ |
| **Explicabilidade** (suíte `pyhealth.interpret`) | ✅ |
| Simulação local (**Ray**) e deployment em **contêineres** | ✅ |
| Baseline centralizado para comparação | ✅ |
| Suíte de testes (51 testes) | ✅ |
| Agregação segura | ❌ |
| Split Learning | ❌ |
| TLS habilitado no deployment (hoje `--insecure`) | ⚠️ |

Detalhamento honesto do que não está pronto: [Limitações](#limitações).

## Início rápido

```bash
# 1. Ambiente (uma vez). Requer Python 3.13 e uv.
uv sync

# 2. Federação simulada, com 2 nós e 2 rodadas
scripts/simulate.sh

# 3. Testes
scripts/test.sh all
```

Nenhum dado credenciado é necessário: o **MIMIC-IV Clinical Database Demo** está
versionado em `data/` e é de redistribuição livre (ODbL v1.0).

### O que você deve ver

```text
[client] node 0/2 scheme=uniform train=43 val=2 test=21
[client] node 1/2 scheme=uniform train=36 val=6 test=21
[server] strategy=fedavg dp=none clients=2 rounds=2
```

Duas leituras importantes:

* `train` **diferente** entre os nós → as partições são distintas, a federação é
  real e não um exercício em que todos treinam sobre os mesmos dados;
* `test` **igual** em todos → é o hold-out compartilhado, nunca treinado, que
  torna comparáveis o modelo federado e o centralizado.

## Estrutura do repositório

```text
.
├── flower_app/                    # A aplicação Flower (o comportamento)
│   ├── server_app.py              #   ServerApp: estratégia + DP
│   ├── client_app.py              #   ClientApp: treino/avaliação local
│   ├── task.py                    #   Dados PyHealth + particionamento por paciente
│   ├── model.py                   #   Arquitetura + termo proximal do FedProx
│   ├── strategies.py              #   FedAvg / FedProx
│   ├── privacy.py                 #   DP (mecanismos oficiais do Flower)
│   └── explain.py                 #   XAI (suíte do PyHealth)
├── libs/
│   └── federation_contracts/      # O que as instituições acordam (versionado)
├── env/                           # Onde cada componente roda
│   ├── podman/                    #   TLS e material do runtime de deployment
│   └── incus/                     #   Topologia de unidades + inventário de portas
├── docs/                          # Arquitetura, simulação, deployment, governança
├── scripts/                       # Pontos de entrada para operação
├── tests/                         # Suíte de testes
├── data/                          # MIMIC-IV demo (ODbL) — ver governança
├── podman-compose.yml             # Topologia de deployment
├── Containerfile.superexec        # Imagem dos ServerApp/ClientApps
└── pyproject.toml                 # Dependências, entrypoints e configuração Flower
```

A separação é deliberada: `flower_app/` é o **comportamento**, `libs/` é o
**acordo** e `env/` é a **execução**. Mudar a estratégia de agregação não toca em
`libs/` nem em `env/`.

## Os dois runtimes

O mesmo código roda de duas formas. Isso é possível porque a aplicação usa o
modelo `ServerApp`/`ClientApp` do Flower, cujos objetos são idênticos nos dois
casos.

| | Simulação (Ray) | Deployment (contêineres) |
| --- | --- | --- |
| Comando | `scripts/simulate.sh` | `scripts/deploy_containers.sh up` + `run` |
| Nós | Processos Ray locais | SuperLink + SuperNodes + SuperExecs |
| Uso | Experimentos, varredura de configuração | Validar comunicação; base do rollout |
| Custo | Baixo | Requer Podman |
| Guia | [`docs/SIMULATION.md`](docs/SIMULATION.md) | [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) |

### Exemplos de experimento

```bash
# Baseline: FedAvg sobre partições IID
scripts/simulate.sh

# Heterogeneidade patológica (cada nó vê uma classe só)
ROUNDS=5 SCHEME=label-skew scripts/simulate.sh

# FedProx contra essa heterogeneidade
ROUNDS=5 SCHEME=label-skew STRATEGY=fedprox MU=0.1 scripts/simulate.sh

# DP central
DP_MODE=server-fixed-clipping DP_NOISE=1.0 scripts/simulate.sh

# Comparação com o treino centralizado, no mesmo hold-out
scripts/central_baseline.py --epochs 5
```

## Conceitos e referências

| Conceito | Onde | Referência |
| --- | --- | --- |
| **FedAvg** | `flower_app/strategies.py` | McMahan et al., *Communication-Efficient Learning of Deep Networks from Decentralized Data*, AISTATS 2017 — [arXiv:1602.05629](https://arxiv.org/abs/1602.05629) |
| **FedProx** | `flower_app/model.py`, `strategies.py` | Li et al., *Federated Optimization in Heterogeneous Networks*, MLSys 2020 — [arXiv:1812.06127](https://arxiv.org/abs/1812.06127) |
| **DP** | `flower_app/privacy.py` | McMahan et al., *Learning Differentially Private Recurrent Language Models*, ICLR 2018 — [arXiv:1710.06963](https://arxiv.org/abs/1710.06963) |
| **PyHealth** | `flower_app/task.py` | [Documentação](https://pyhealth.readthedocs.io/) |
| **Flower** | `flower_app/*_app.py` | [Documentação](https://flower.ai/docs/framework/) |

## Dados

| Fonte | Situação | Onde |
| --- | --- | --- |
| **MIMIC-IV Demo** (100 pacientes) | Versionado, ODbL v1.0, redistribuição livre | `data/` |
| **MIMIC-IV completo** | Credenciado — **nunca** versionar | `PYHEALTH_EHR_ROOT` |
| **SESA-CE** | Proprietário (LGPD/HIPAA/GDPR) — **nunca** sai da unidade | fora do repositório |

Nunca cruza a fronteira do nó: amostras, `visit_id`, `patient_id`, mapas de
atribuição de XAI e checkpoints. Apenas `ArrayRecord` (pesos) e `MetricRecord`
(escalares) são serializados.

Regras completas e o procedimento de auditoria:
[`docs/DATA_GOVERNANCE.md`](docs/DATA_GOVERNANCE.md).

## Documentação

| Documento | Conteúdo |
| --- | --- |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Topologia, round federado, fronteira de dados, decisões e justificativas |
| [`docs/SIMULATION.md`](docs/SIMULATION.md) | Simulação Ray: comandos, escala, cluster multi-nó, armadilhas |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Deployment em contêineres: topologia, portas, TLS, diagnóstico |
| [`docs/DATA_GOVERNANCE.md`](docs/DATA_GOVERNANCE.md) | O que pode entrar no repositório e o que pode trafegar |
| [`docs/STAKEHOLDERS.md`](docs/STAKEHOLDERS.md) | Guia para quem decide e usa, sem detalhe de implementação |
| [`env/incus/PORTS.md`](env/incus/PORTS.md) | Inventário de serviços e portas expostas |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Como contribuir e o que o CI verifica |
| [`COMMIT_POLICY.md`](COMMIT_POLICY.md) | Formato de commit, regras específicas do projeto e hooks de verificação |
| [`SECURITY.md`](SECURITY.md) | Como reportar vulnerabilidades e segredos |

## Limitações

Declaradas explicitamente, porque um framework de pesquisa que esconde limites
não é utilizável:

1. **O demo tem 100 pacientes.** Após o split, o pool de validação tem 4
   pacientes e o hold-out, 5. As métricas são ruidosas **por construção**: o demo
   exercita o pipeline, não sustenta conclusão estatística.
2. **DP é central.** O servidor vê as atualizações individuais antes de agregar.
   Um cenário que não confie no servidor exige recorte no cliente mais agregação
   segura — não implementada.
3. **O deployment roda `--insecure`.** O material TLS é gerado por
   `env/podman/certs.yml`, mas ainda não está em uso.
4. **Sem Split Learning**, apesar de estar no plano de trabalho.
5. **Sem validação clínica.** A engenharia foi exercitada; a utilidade clínica,
   não.
6. **Sem agregação segura**, então o servidor é um ponto de confiança.

## Licença

Apache-2.0 — ver [`LICENSE`](LICENSE) e [`NOTICE`](NOTICE).

O MIMIC-IV Demo em `data/` é distribuído sob **ODbL v1.0**
([`data/LICENSE.txt`](data/LICENSE.txt)), não sob a Apache-2.0.
