# Como contribuir

## Antes de começar

```bash
uv sync          # ambiente com dependências e grupo dev
scripts/test.sh  # deve passar antes e depois da sua mudança
```

## Fluxo

1. Abra uma issue descrevendo o problema antes de um PR grande.
2. Crie um branch a partir de `main`.
3. Faça a mudança com testes.
4. Rode `scripts/test.sh all` (inclui o teste lento sobre dados reais).
5. Verifique a [política de dados](docs/DATA_GOVERNANCE.md) — é o item que mais
   reprova PR.

## Regras de código

| Regra | Motivo |
| --- | --- |
| **Comentários e docstrings em inglês; documentação em português** | O código deve ser legível para quem reutilizar o framework; a documentação, para quem decide no projeto. |
| Toda função pública tem docstring explicando *por que*, não só *o que* | O valor deste repositório está nas decisões, não nas linhas. |
| Não reimplemente o que Flower ou PyHealth já oferecem | FedAvg, FedProx e os mecanismos de DP vêm do Flower; métricas e XAI, do PyHealth. Reimplementar cria divergência silenciosa. |
| Ao propor mudança arquitetural, atualize o diagrama Mermaid em `docs/ARCHITECTURE.md` | Diagrama desatualizado é pior que ausente. |
| Cite a referência original de qualquer estratégia de agregação | FedAvg → McMahan et al. 2017; FedProx → Li et al. 2018/2020. |
| Não introduza outro framework de FL sem justificativa explícita no PR | O projeto é Flower de ponta a ponta. |

## O que o CI verifica

```bash
scripts/test.sh all
```

Equivale a:

| Verificação | Cobre |
| --- | --- |
| Testes rápidos | Invariantes dos contratos, particionamento, estratégias, DP, termo proximal |
| Testes lentos | Pipeline PyHealth real, partições disjuntas entre nós, hold-out compartilhado idêntico, compatibilidade de `state_dict`, penalidade proximal, disponibilidade de XAI |

Os testes lentos carregam o MIMIC-IV demo: custam dezenas de segundos e centenas
de megabytes. Rodam no CI e são obrigatórios antes de um PR.

## Antes de mexer no particionamento

Leia o docstring de `flower_app/task.py`. O split **não** usa
`pyhealth.datasets.split_by_patient`, e a razão está documentada lá: os subsets
retornados não expõem mapeamento de índice utilizável, e as duas propriedades
envolvidas tornam fácil construir um split que vaza um paciente entre nós sem
parecer errado.

Qualquer mudança nessa área precisa manter três invariantes verificados por
teste:

1. pacientes de treino são disjuntos **entre nós**;
2. o pool de teste é **idêntico** em todos os nós e nunca treinado;
3. o split é reprodutível a partir da seed.

## Antes de mexer no `ClientApp`

`partition-id` é lido de `context.node_config` e **não** tem default. Isso é
intencional: em simulação, `node_id` é um identificador de 64 bits, não um
índice, e assumir `0` faria todos os nós treinarem na mesma partição e ainda
reportarem resultado "federado". Um erro alto é melhor que ciência errada
silenciosa.

## Commits

O formato é obrigatório e verificado por hook:

```text
<tipo>(<escopo>): <descrição no imperativo>
```

```text
fix(data): corrige o split por paciente
feat(privacy): aplica DP central sobre a estratégia escolhida
```

Ative a verificação uma vez por clone:

```bash
git config core.hooksPath .githooks
```

Regras completas, escopos, exemplos e o que é verificado automaticamente:
[`COMMIT_POLICY.md`](COMMIT_POLICY.md). Além do formato, a política exige que
mudança arquitetural atualize o diagrama Mermaid no mesmo commit e que mudança
em privacidade declare o impacto no orçamento.

## Dúvidas

Abra uma issue com a etiqueta `question`. Se a dúvida for sobre uma decisão de
arquitetura, `docs/ARCHITECTURE.md` provavelmente já registra o porquê.
