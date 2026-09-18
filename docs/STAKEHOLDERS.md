# Guia para stakeholders

Para quem precisa usar, avaliar ou decidir sobre o sistema — não para quem vai
alterar o código.

## O que é

Um arcabouço de aprendizado federado para alerta antecipado de deterioração
clínica. Cada hospital treina localmente; só pesos de modelo e métricas agregadas
trafegam. Nenhum prontuário sai da instituição.

## O que já funciona

| Capacidade | Situação |
| --- | --- |
| Pipeline PyHealth ponta a ponta sobre o MIMIC-IV demo | Funcional, validado por testes |
| Federação com 2 nós, partições reais e distintas | Funcional, verificado em execução |
| Simulação Ray local | Funcional |
| Deployment em contêineres (SuperLink/SuperNode/SuperExec) | Funcional, `--insecure` |
| Agregação FedAvg | Funcional |
| Agregação FedProx (non-IID) | Funcional |
| Particionamento IID e non-IID (`label-skew`) | Funcional |
| Privacidade diferencial (DP central) | Funcional, desligada por padrão |
| Explicabilidade (XAI) | Integrada à suíte do PyHealth |
| Baseline centralizado para comparação | Funcional |
| Agregação segura | Não implementada |
| Split Learning | Não implementado |
| TLS (`--insecure` desligado) | Material gerado, ainda não em uso |

## Os três comandos que importam

```bash
# 1. Preparar o ambiente (uma vez)
uv sync

# 2. Rodar uma federação simulada
scripts/simulate.sh

# 3. Rodar os testes
scripts/test.sh all
```

Nada mais é necessário para uma demonstração funcional. Os dados de exemplo já
estão no repositório e são de redistribuição livre.

## O que observar na saída

O `ClientApp` imprime, para cada nó, a identidade e o tamanho da coorte:

```text
[client] node 0/2 scheme=uniform train=43 val=2 test=21
[client] node 1/2 scheme=uniform train=36 val=6 test=21
```

Interpretação:

* `train` **diferente** entre nós → as partições são distintas, a federação é
  real e não um exercício em que todos treinam sobre os mesmos dados;
* `test` **igual** em todos → é a base comum de comparação, nunca treinada;
* `node i/2` → identificador da partição e total de partícipes.

O `ServerApp` imprime a configuração efetiva:

```text
[server] strategy=fedavg dp=none clients=2 rounds=2
```

## Perguntas que o sistema responde

| Pergunta | Como responder |
| --- | --- |
| Federar custa acurácia? | `scripts/simulate.sh` e depois `scripts/central_baseline.py`; os dois avaliam no mesmo hold-out |
| O que acontece com dados heterogêneos? | `SCHEME=label-skew scripts/simulate.sh` contra `SCHEME=uniform scripts/simulate.sh` |
| FedProx ajuda no regime heterogêneo? | `SCHEME=label-skew STRATEGY=fedprox MU=0.1` e compare com FedAvg no mesmo esquema |
| Qual o custo em utilidade da privacidade? | `DP_MODE=server-fixed-clipping DP_NOISE=...` variando o ruído |
| Por que o modelo decidiu isso? | `flower_app/explain.py`, que expõe a suíte de atribuição do PyHealth |

## Cenário de decisão: quando federar vale a pena

O sistema não decide isso; ele mede. O protocolo é:

1. rode o baseline centralizado, que é o teto;
2. rode o federado no mesmo hold-out;
3. compare `holdout_pr_auc`.

Se a diferença for pequena ante o ganho de não mover dados, a federação se
justifica. Se for grande, o problema é heterogeneidade e o próximo passo é
FedProx com `label-skew` para quantificar. Com o demo de 100 pacientes esse
número **não** sustenta decisão clínica — serve para validar o método. Com o
MIMIC-IV completo ou com dados da SESA, passa a sustentar.

## O que o sistema ainda não garante

Diga isto antes que alguém pergunte:

* **DP é central**, então exige confiar no servidor de agregação. Agregação
  segura não está implementada.
* **O transporte ainda é `--insecure`** no deployment. Certificados são gerados
  por `env/podman/certs.yml`, mas não estão em uso.
* **O demo é pequeno.** O pool de validação tem 4 pacientes, o hold-out, 5. As
  métricas são ruidosas por construção.
* **Não há Split Learning**, apesar de estar no plano de trabalho.
* **Não há validação clínica.** O sistema foi exercitado quanto a engenharia, não
  quanto a utilidade clínica.

## Onde ler mais

| Assunto | Documento |
| --- | --- |
| Topologia, decisões e porquês | `docs/ARCHITECTURE.md` |
| Rodar experimentos | `docs/SIMULATION.md` |
| Subir a topologia em contêineres | `docs/DEPLOYMENT.md` |
| O que pode entrar no repositório | `docs/DATA_GOVERNANCE.md` |
| Expor serviços e portas | `env/incus/PORTS.md` |
