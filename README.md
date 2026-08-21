# PyHealth Federated Learning

Aplicacao experimental de Federated Learning usando [Flower](https://flower.ai/), [PyHealth](https://pyhealth.readthedocs.io/) e PyTorch. A topologia de execucao foi preparada para o runtime de deployment do Flower com Podman.

## Estado atual

Os componentes Flower estao em `flower_app/`:

- `flower_app/server_app.py`: inicializa o modelo global e executa a estrategia `FedAvg`.
- `flower_app/client_app.py`: recebe os pesos globais, treina na particao local e devolve pesos e metricas.
- `flower_app/task.py`: carrega os dados, divide pacientes e constroi o modelo.

Atencao: a implementacao atual de `flower_app/task.py` usa o dataset sintetico MIMIC-III remoto do PyHealth e o modelo `Transformer`. A pasta `data/` deste repositorio contem arquivos MIMIC-IV locais, mas eles nao sao usados pelo codigo atual. Para usar esses CSVs, sera necessario adaptar `task.py` para `MIMIC4Dataset` e para o formato de arquivos existente.

## Estrutura

```text
.
├── flower_app/
│   ├── __init__.py
│   ├── client_app.py
│   ├── server_app.py
│   └── task.py
├── data/
│   ├── hosp/                 # CSVs MIMIC-IV hospitalares
│   └── icu/                  # CSVs MIMIC-IV de UTI
├── output/                   # Saidas e checkpoints locais
├── Containerfile.superexec  # Imagem dos ServerApp/ClientApps
├── podman-compose.yml       # SuperLink, SuperNodes e SuperExecs
├── pyproject.toml            # Dependencias e configuracao Flower
├── uv.lock                  # Lockfile gerado pelo uv, se versionado
└── PODMAN.md                # Referencia detalhada do deployment
```

Arquivos como `.venv/`, `__pycache__/`, `build/`, `dist/` e `output/` sao artefatos locais e nao fazem parte da aplicacao distribuida.

## Configuracao Flower

O `pyproject.toml` define os entrypoints:

```toml
[tool.flwr.app.components]
serverapp = "flower_app.server_app:app"
clientapp = "flower_app.client_app:app"
```

A configuracao padrao e:

| Parametro | Valor | Descricao |
| --- | ---: | --- |
| `num-server-rounds` | `3` | Numero de rodadas FedAvg |
| `local-epochs` | `2` | Epocas locais por rodada |
| `learning-rate` | `0.00001` | Taxa de aprendizado enviada aos clientes |
| `batch-size` | `256` | Tamanho do batch no cliente |
| `num-partitions` | `2` | Numero de particoes esperadas |
| `fraction-train` | `1.0` | Fracao de clientes no treino |
| `fraction-evaluate` | `1.0` | Fracao de clientes na avaliacao |

Esses valores podem ser sobrescritos sem editar arquivos:

```bash
flwr run . --run-config "num-server-rounds=5 local-epochs=1"
```

## Requisitos

- Python `3.13`, conforme `.python-version`.
- Podman.
- Um provider para `podman compose`, como `podman-compose` ou Docker Compose.
- Acesso de rede para baixar as imagens Flower e as dependencias.

O projeto possui dependencias declaradas no `pyproject.toml`: Flower, NumPy, PyHealth e PyTorch.

## Ambiente com uv

Para instalar e validar o ambiente com `uv`:

```bash
uv sync
uv run python -m py_compile flower_app/*.py
uv run flwr build
```

Para executar uma simulacao local do Flower, quando o ambiente local estiver configurado:

```bash
uv run flwr run . --stream
```

## Ambiente com Conda

O Conda pode ser usado como ambiente interativo, mas nao e copiado para os containers. Ative o ambiente e instale o projeto usando o mesmo `pyproject.toml`:

```bash
conda activate <seu-ambiente>
python -m pip install -e .
flwr build
```

Nao misture pacotes instalados no Conda e no `.venv` sem verificar qual interpretador esta ativo:

```bash
python -c "import sys; print(sys.executable)"
```

## Execucao com Podman

### 1. Verifique os arquivos de dados

O dataset anexado esta organizado como MIMIC-IV:

```text
data/hosp/*.csv
data/icu/*.csv
```

O `Containerfile.superexec` copia `data/` para `/app/data` dentro da imagem. Entretanto, no estado atual, `flower_app/task.py` usa o MIMIC-III sintetico remoto, portanto esses CSVs locais ainda nao entram no treinamento.

### 2. Construa a imagem

```bash
podman build \
	-f Containerfile.superexec \
	-t pyhealth-flower-superexec:0.1.0 \
	.
```

### 3. Inicie a topologia Flower

```bash
podman compose -f podman-compose.yml up -d --build
```

A composicao inicia:

- um `SuperLink`;
- dois `SuperNode`, com `partition-id=0` e `partition-id=1`;
- um `SuperExec` para o `ServerApp`;
- dois `SuperExec` para os `ClientApp`.

### 4. Configure a conexao local

No arquivo de configuracao do Flower, adicione uma conexao para o SuperLink:

```toml
[superlink.local-deployment]
address = "127.0.0.1:9093"
insecure = true
```

Depois submeta a aplicacao:

```bash
flwr run . local-deployment --stream
```

### 5. Acompanhe e encerre

```bash
podman compose -f podman-compose.yml logs -f
podman compose -f podman-compose.yml down
```

## Portas

| Porta | Uso |
| ---: | --- |
| `9091` | API de runtime do SuperLink |
| `9092` | Conexao SuperNode-SuperLink |
| `9093` | API de deployment usada pelo CLI Flower |
| `9094` | Runtime do primeiro SuperNode |
| `9095` | Runtime do segundo SuperNode |

## Diagnostico

Verifique os containers:

```bash
podman ps -a
podman compose -f podman-compose.yml logs superlink
podman compose -f podman-compose.yml logs supernode-1 supernode-2
```

Se `podman compose` informar que nenhum provider foi encontrado, instale `podman-compose` ou configure Docker Compose como provider.

Se o treinamento reclamar de arquivos MIMIC-IV ausentes, confira se os arquivos estao em `data/hosp/` e `data/icu/`. A configuracao atual ainda espera o dataset sintetico MIMIC-III remoto definido em `flower_app/task.py`.

## Limitacoes conhecidas

- O `ClientApp` monitora `pr_auc`, mas o `Trainer` foi configurado com `roc_auc`, `f1` e `accuracy`. Antes de uma execucao de treino completa, alinhe esse monitor com uma metrica configurada ou adicione `pr_auc` a lista de metricas.
- O valor `learning-rate` e enviado pelo `ServerApp`, mas o `ClientApp` atual nao passa explicitamente `optimizer_params` ao `Trainer`. Se a taxa definida no `pyproject.toml` precisar ser aplicada, ajuste o treino local.
- O dataset MIMIC-IV local esta presente no container, mas ainda nao esta conectado ao pipeline atual. O uso do MIMIC-IV exige configurar `MIMIC4Dataset`, as tabelas `hosp/` e `icu/`, e as extensoes `.csv` reais.

## Documentacao relacionada

- [PODMAN.md](PODMAN.md): passos detalhados do deployment.
- [Flower Framework](https://flower.ai/docs/framework/main/en/index.html).
- [Flower Quickstart PyTorch](https://flower.ai/docs/framework/main/en/tutorial-quickstart-pytorch.html).
- [PyHealth](https://pyhealth.readthedocs.io/en/latest/).
