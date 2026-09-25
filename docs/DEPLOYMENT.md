# Deployment (Deployment Runtime em contêineres)

Este modo exercita a pilha real de comunicação do Flower dentro de contêineres.
É a base sobre a qual o rollout multi-instituição (Incus + Podman) é construído.

Ele **não** é necessário para reproduzir experimentos — para isso use
`docs/SIMULATION.md`, que é muito mais barato.

## Topologia

```mermaid
graph LR
    CLIENT["flwr CLI<br/>(sua máquina)"] -->|":9093 deployment API"| SL
    subgraph POD["podman-compose.yml"]
        SL["superlink<br/>:9091 :9092 :9093"]
        SN1["supernode-1<br/>partition-id=0"]
        SN2["supernode-2<br/>partition-id=1"]
        SES["superexec-serverapp"]
        SEC1["superexec-clientapp-1"]
        SEC2["superexec-clientapp-2"]
        SL --> SES
        SN1 --> SL
        SN2 --> SL
        SEC1 --> SN1
        SEC2 --> SN2
    end
```

Cinco processos: um `SuperLink`, dois `SuperNode` e três `SuperExec` (um
ServerApp, dois ClientApps). A imagem dos SuperExec é a mesma para os três;
o que muda é `--plugin-type`.

## Pré-requisitos

* Podman e um provider de compose: `podman compose` ou `podman-compose`;
* os dados MIMIC-IV em `data/`, versionados no repositório (demo ODbL).

## 1. Construir e subir

```bash
scripts/deploy_containers.sh up
```

Equivalente a:

```bash
podman build -f Containerfile.superexec -t pyhealth-flower-superexec:0.1.0 .
podman compose -f podman-compose.yml up -d --build
```

> A `Containerfile.superexec` remove a linha de dependência do Flower antes do
> `pip install`, porque a imagem base `flwr/superexec:1.34.0` já traz o Flower.
> Como o projeto declara `flwr[simulation,dp]`, o `sed` casa o prefixo `"flwr[`.
> Se você adicionar outra linha de dependência do Flower, ajuste o `sed` junto.

## 2. Configurar a conexão de deployment

O CLI precisa saber onde está o SuperLink. Confira:

```bash
flwr config list
```

Se `local-deployment` não aparecer, adicione em `~/.flwr/config.toml`:

```toml
[superlink.local-deployment]
address = "127.0.0.1:9093"
insecure = true
```

## 3. Submeter a aplicação

```bash
scripts/deploy_containers.sh run
```

Equivalente a:

```bash
flwr run . local-deployment --stream
```

Os `partition-id` vêm do `--node-config` de cada SuperNode no compose, então o
`ClientApp` não precisa adivinhar nada.

## 4. Acompanhar e encerrar

```bash
scripts/deploy_containers.sh logs
scripts/deploy_containers.sh down
```

## Portas

| Porta | Serviço | Cruza fronteira de unidade? |
| ---: | --- | --- |
| `9091` | SuperLink AppIO | Não |
| `9092` | Conexão da frota SuperNode → SuperLink | **Sim**, apenas de unidades cliente |
| `9093` | API de deployment do CLI | Não — somente rede de administração |
| `9094` | SuperNode-1 AppIO | Não |
| `9095` | SuperNode-2 AppIO | Não |

### Invariante de porta (AppIO)

Cada SuperNode escuta o seu AppIO na porta `9094` por **default**, e cada
`superexec-clientapp-N` disca `supernode-N:<porta>`. As duas pontas precisam
casar, e o default só serve para o *primeiro* SuperNode. Por isso o
`podman-compose.yml` declara `--clientappio-api-address` explicitamente nos dois
SuperNodes, incluindo aquele que já cairia no default: um SuperNode que escuta
numa porta diferente da que o seu SuperExec disca deixa o ClientApp em
`Connection attempt failed` perpétuo e o round nunca fecha — sem erro fatal,
apenas parado. Verifique com:

```bash
podman exec pyhealth_supernode-1_1 netstat -tlnp   # deve listar 9094
podman exec pyhealth_supernode-2_1 netstat -tlnp   # deve listar 9095
```

O `podman-compose.yml` publica todas as cinco no host. Isso está **correto para
desenvolvimento em uma máquina só** e está **errado para multi-unidade**: nesse
caso somente `9092` deve ser alcançável entre unidades e `9093` apenas pela rede
de administração. O detalhamento e os trechos a alterar estão em
`env/incus/PORTS.md`.

## Transporte seguro

O compose roda com `--insecure`. Para gerar o material TLS:

```bash
podman compose -f env/podman/certs.yml run --rm gen-certs
```

A saída vai para `env/podman/superlink-certificates/`, que é ignorado pelo git.
**`ca.key` e `server.key` são segredos de federação**: quem os tiver pode se
passar pelo servidor de agregação e receber as atualizações de modelo.

Sair do `--insecure` é pré-requisito para qualquer deployment em que a federação
atravesse uma rede que a instituição não controla integralmente.

## Diferenças em relação ao Simulation Runtime

| | Simulation | Deployment |
| --- | --- | --- |
| Nós | Processos Ray locais | SuperNodes registrados no SuperLink |
| `partition-id` | Preenchido pelo Flower em `node_config` | Definido por `--node-config` |
| Transporte | Em processo | gRPC sobre a rede |
| Dados | Compartilham o mesmo diretório | Cada unidade tem os seus |
| Uso | Experimentos | Validar a comunicação; base do rollout |

## Diagnóstico

| Sintoma | Causa provável |
| --- | --- |
| `no such file or directory: 'flower-superlink'` | `.venv/bin` fora do `PATH` |
| `neither 'podman compose' nor 'podman-compose'` | Provider de compose ausente |
| `ClientApp` reclama de `partition-id` | `--node-config` do SuperNode sem `partition-id` |
| `ClientApp` reclama de split vazio | `num-partitions` maior que o número de pacientes disponíveis; reduza os nós ou use um coorte maior |
| `superexec-clientapp-N` em loop de `Connection attempt failed` **e** o round 1 nunca fecha | `supernode-N` escuta numa porta diferente da que o seu SuperExec disca. O default do SuperNode é `0.0.0.0:9094`, portanto todo SuperNode além do primeiro precisa de `--clientappio-api-address 0.0.0.0:<porta>`, casando com o `--appio-api-address` do seu `superexec`. Confirme com `podman exec pyhealth_supernode-N_1 netstat -tlnp`. Sintoma associado no SuperNode: `Receiving: train message ... Received successfully` e nenhum `Sending` depois |
| `flwr run` não encontra a conexão | Falta a seção `[superlink.local-deployment]` |
| Treino com arquivos MIMIC ausentes | `PYHEALTH_EHR_ROOT` apontando para o lugar errado |
| `flwr log` mostra `aggregate_train: Received 1 results and 1 failures` e o run termina "com sucesso" | Um nó caiu no meio do round. O `FedAvg` do *ServerApp* (Flower 1.34) **não tem** `accept_failures`: ele sempre tolera falhas, agrega o que chegou e loga em `INFO`. `min_train_nodes` guarda apenas a **amostragem**, não a queda durante o round. Confira a contagem de resultados de cada round **antes** de reportar métricas como federadas |

```bash
podman ps -a
podman compose -f podman-compose.yml logs superlink
podman compose -f podman-compose.yml logs supernode-1 supernode-2
```

### Onde ficam os logs do ServerApp

O `flwr-serverapp` roda no contêiner `superexec-serverapp`, mas tem `stdout` e
`stderr` apontados para `/dev/null`: **`podman logs superexec-serverapp` nunca
mostra a estratégia, o round nem a agregação**. Não é bufferização — o
`PYTHONUNBUFFERED=1` já está setado na imagem; é redirecionamento do processo.

Os logs são recuperados do SuperLink pelo run ID:

```bash
flwr list                              # descobre o run ID
flwr log <run-id> local-deployment --show     # imprime uma vez
flwr log <run-id> local-deployment --stream   # acompanha em tempo real
```

É aí que aparecem as linhas que importam: `strategy=fedavg dp=none clients=2
rounds=3`, `configure_train: Sampled N nodes`, `aggregate_train: Received N
results and M failures`, e o bloco `Final results`. Ao diagnosticar um run
parado, comece por aqui — não pelos logs dos contêineres.
