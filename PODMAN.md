# Execucao com Podman

A estrutura segue o runtime de deployment do Flower: um SuperLink, dois SuperNodes e tres processos SuperExec, sendo um ServerApp e dois ClientApps.

## Pre-requisitos

- Podman
- `podman compose` ou `podman-compose`
- MIMIC-IV disponibilizado em `data/`

O ambiente Conda e o `.venv` do uv nao sao copiados para a imagem. As dependencias e os entrypoints sao definidos no `pyproject.toml` e instalados durante o build.

## Executar

```bash
podman compose -f podman-compose.yml build
podman compose -f podman-compose.yml up -d
```

Em outro terminal, configure uma conexao local de deployment no arquivo do Flower:

```toml
[superlink.local-deployment]
address = "127.0.0.1:9093"
insecure = true
```

Execute a aplicacao a partir da raiz do projeto:

```bash
flwr run . local-deployment --stream
```

Para parar os containers:

```bash
podman compose -f podman-compose.yml down
```

## Estrutura Flower

- `flower_app/client_app.py`: treino e avaliacao local nos ClientApps.
- `flower_app/server_app.py`: inicializacao do StageNet e estrategia FedAvg.
- `flower_app/task.py`: schema MIMIC-IV, divisao por paciente e construcao do modelo.
- `pyproject.toml`: dependencias, entrypoints e configuracao Flower.
- `Containerfile.superexec`: imagem comum para ServerApp e ClientApps.
- `podman-compose.yml`: topologia local do deployment runtime.
