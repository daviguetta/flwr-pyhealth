# Simulação (Simulation Runtime, backend Ray)

Este é o modo de desenvolvimento e de reprodução de experimentos. Ele roda a
federação inteira em uma máquina, sem contêineres, e é o motivo de existir a
pasta raiz do projeto: o mesmo `ServerApp`/`ClientApp` do deployment.

## Por que Ray

O *Simulation Runtime* do Flower é construído sobre o [Ray](https://www.ray.io/).
O backend padrão é o **`RayBackend`** — na versão instalada (Flower 1.34) o
`--backend-name` aceita apenas `ray`, ou seja, não há escolha a fazer. Cada worker
do backend é um ator Ray capaz de executar um `ClientApp`.

Consequência prática: **a simulação é o modo padrão de `flwr run`**. Se você tem
uma Flower App, não precisa de mais nada para simulá-la.

## Pré-requisitos

```bash
uv sync              # instala o grupo dev e as dependências do pyproject
```

O projeto declara `flwr[simulation,dp]`, então o `ray` e o `dp-accounting` vêm
junto. Sem o extra `simulation`, o `flwr run` falha ao subir o SuperLink local —
esse é o erro mais comum em uma instalação limpa.

Confirme:

```bash
.venv/bin/python -c "import ray; print(ray.__version__)"
```

## Execução

### Caminho direto

```bash
export PATH="$PWD/.venv/bin:$PATH"   # o CLI sobe flower-superlink como subprocesso
flwr run . --stream
```

### Caminho com o wrapper (recomendado)

`scripts/simulate.sh` cuida do `PATH`, fixa os padrões e imprime o que vai rodar:

```bash
scripts/simulate.sh
```

Tudo é sobrescrevível por variável de ambiente, o que torna um experimento
descritível em uma linha:

```bash
# FedAvg / IID — baseline
scripts/simulate.sh

# FedProx contra heterogeneidade patológica
ROUNDS=5 SCHEME=label-skew STRATEGY=fedprox MU=0.1 scripts/simulate.sh

# FedAvg com DP central
DP_MODE=server-fixed-clipping DP_NOISE=1.0 scripts/simulate.sh
```

Variáveis aceitas: `ROUNDS`, `EPOCHS`, `LR`, `BATCH_SIZE`, `PARTITIONS`,
`SCHEME`, `STRATEGY`, `MU`, `DP_MODE`, `DP_NOISE`, `DP_CLIP`,
`PYHEALTH_VENV`, `PYHEALTH_EHR_ROOT`.

## Escala

O número de nós simulados é configurado na federação, não no código:

```bash
flwr run . --federation-config "num-supernodes=16" --stream
```

`scripts/simulate.sh` já faz isso: `PARTITIONS=16` ajusta simultaneamente o número
de SuperNodes e a variável `num-partitions` da run, para que os dois não
divirjam.

Para fixar o padrão de forma permanente:

```bash
flwr federation simulation-config \
    --num-supernodes 100 \
    --client-resources-num-cpus 2
```

Recursos por `ClientApp` são alocados de forma **branda**: servem para controlar
o grau de paralelismo, não para restringir uso. Ajuste `--client-resources-*`
conforme o maior `ClientApp` que você espera executar em paralelo.

## Cluster multi-nó (2× A100)

O `RayBackend` simula através de vários nós se você interligá-los antes:

```bash
# no nó head
ray start --head

# nos demais nós, com o endereço impresso pelo head
ray start --address='<head>:6379'

# a partir do head, como em uma máquina só
scripts/simulate.sh

# ao terminar
ray stop   # em todos os nós
```

Requisitos do guia oficial: mesmo ambiente Python, mesmo código e **os mesmos
dados** em todos os nós — a i-ésima partição precisa ser idêntica em todo lugar.
Com o demo MIMIC-IV versionado isso é automático; com dados credenciados, é
responsabilidade do operador.

Se as simulações usarem GPU, isole-as com `CUDA_VISIBLE_DEVICES` por simulação.

## Duas armadilhas encontradas na prática

### 1. `flower-superlink` não está no `PATH`

Sintoma:

```text
Unable to launch `flower-superlink` for local simulation:
[Errno 2] No such file or directory: 'flower-superlink'
```

O binário existe em `.venv/bin/`, mas o CLI do Flower o procura no `PATH`.
Ative o ambiente ou exporte o caminho:

```bash
export PATH="$PWD/.venv/bin:$PATH"
```

`scripts/simulate.sh` faz isso automaticamente.

### 2. O log esconde que a federação é real

O Ray agrupa mensagens de log semelhantes entre workers. Com dois nós, as linhas

```text
[client] node 0/2 scheme=uniform train=43 val=2 test=21
[client] node 1/2 scheme=uniform train=36 val=6 test=21
```

podem aparecer como **uma só**, anotada `[repeated Nx across cluster]`. Isso
sugere, incorretamente, que todos os nós usaram a mesma partição.

Para ver cada nó:

```bash
RAY_DEDUP_LOGS=0 flwr run . --stream
```

`scripts/simulate.sh` já define `RAY_DEDUP_LOGS=0`, porque o tamanho da coorte por
nó é a primeira evidência de que a execução é de fato federada.

## O que checar em uma execução

O `ClientApp` imprime a identidade e a coorte de cada nó:

```text
[client] node 0/2 scheme=uniform train=43 val=2 test=21
[client] node 1/2 scheme=uniform train=36 val=6 test=21
```

Leitura correta:

* `train` e `val` **diferem** entre nós → partições distintas, federação real;
* `test` é **igual** em todos → é o hold-out compartilhado, nunca treinado;
* `n/num_partitions` bate com o número de SuperNodes.

Se `train` for igual em todos os nós, a execução não é federada. Nesse caso o
`ClientApp` teria levantado erro por falta de `partition-id`; se você vir números
iguais com partições distintas, o `partition-id` chegou trocado — verifique o
`--node-config` no deployment.

O `ServerApp` imprime a configuração efetiva:

```text
[server] strategy=fedavg dp=none clients=2 rounds=2
```

## Comparar com o baseline centralizado

```bash
scripts/central_baseline.py --epochs 5
```

O script treina a mesma arquitetura de forma centralizada e avalia no hold-out
compartilhado. Ele **verifica** que o hold-out usado é exatamente o mesmo que os
nós federados recebem, então os dois números são comparáveis por construção.
