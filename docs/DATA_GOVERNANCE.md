# Governança de dados

Este documento define o que pode e o que não pode entrar no repositório, e o que
pode cruzar a fronteira de um nó durante a federação. Ele é a referência para
revisão de PR e para auditoria.

## Regra central

> Dado de paciente **nunca** sai do ambiente federado que o produziu.
> O que trafega é peso de modelo e escalar de métrica. Nada mais.

Isso vale para o repositório, para o gRPC entre unidades, para os logs e para os
checkpoints.

## O que cruza a fronteira do nó

Exaustivo:

| Item | Formato Flower | Contém dado de paciente? |
| --- | --- | --- |
| Pesos do modelo | `ArrayRecord` | Não — é o ponto do FL |
| Escalares | `MetricRecord` | Não — `loss`, `pr_auc`, `num-examples` |
| Configuração de treino | `ConfigRecord` | Não — `lr`, `proximal-mu`, épocas |

O que **nunca** cruza:

* amostras, `visit_id`, `patient_id`;
* **mapas de atribuição (XAI)** — apontam para códigos e internações
  individuais, logo são dado derivado de paciente e ficam dentro do nó;
* checkpoints intermediários;
* logs de treino com identificadores.

`tests/test_pipeline.py` verifica os invariantes de particionamento; a fronteira
de serialização é garantida por construção, já que apenas `ArrayRecord` e
`MetricRecord` são construídos nos handlers.

## Dados no repositório

Este repositório é **público**. Só entram dados redistribuíveis.

### MIMIC-IV Clinical Database Demo — incluído

* Local: `data/hosp/` e `data/icu/` (100 pacientes, ~129 MB).
* Licença: **ODbL v1.0** (`data/LICENSE.txt`), redistribuição permitida.
* Origem: PhysioNet, `https://doi.org/10.13026/07hj-2a80`.
* Contém apenas registros desidentificados e **não** contém notas clínicas em
  texto livre.

Atribuição obrigatória pela ODbL: está em `NOTICE` e o arquivo de licença
upstream é preservado em `data/LICENSE.txt`. Não remova nenhum dos dois.

### MIMIC-IV completo — proibido

O MIMIC-IV completo é **credenciado**. Redistribuí-lo viola o acordo de uso do
PhysioNet. Nunca faça commit dele.

Para usar localmente, sem versionar:

```bash
export PYHEALTH_EHR_ROOT=/caminho/mimic-iv/2.2
```

O caminho é lido por `flower_app/task.py`; nada é copiado para dentro do
repositório.

### SESA-CE — nunca

Dado proprietário da rede estadual, sob LGPD, HIPAA e GDPR. As regras são
diferentes das do MIMIC e mais rígidas:

1. Não entra no `.git`, em nenhuma forma, inclusive anonimizado.
2. Não sai da unidade Incus que o hospeda.
3. Não é copiado para imagem de contêiner.
4. Não é usado em ambiente de desenvolvimento fora da rede da SESA.
5. Não é referenciado por caminho em arquivo versionado — use variável de
   ambiente lida em tempo de execução.

Um `PYHEALTH_EHR_ROOT` apontando para dado da SESA é aceitável **apenas** dentro
da unidade da SESA. Fora dela, não.

## Checkpoints e saídas

`output/` é ignorado pelo git, e a razão é substantiva, não estética: um
checkpoint é derivado de prontuário. Versioná-lo publica algo reconstruído a
partir de dado de paciente, mesmo que os pesos pareçam inócuos. O mesmo vale para
`*.ckpt`, `*.pt`, `*.pth` e logs de treino.

O `Trainer` do PyHealth grava o melhor checkpoint; no `ClientApp` cada nó usa um
diretório próprio derivado do `partition-id`, para que nós simulados que
compartilham o mesmo sistema de arquivos não sobrescrevam o checkpoint uns dos
outros.

## Segredos

Nunca versionar:

* `ca.key`, `server.key`, `*.pem`, `*.csr`;
* `env/podman/superlink-certificates/`, `env/*/state/`;
* credenciais de federação.

`env/podman/.gitignore` cobre o material de certificado. Note que a regra
`!env/podman/certs.yml` no `.gitignore` da raiz é intencional: o *gerador* de
certificados é código e deve ser versionado; o *resultado* não.

## DP e o que ele garante

DP está implementado via mecanismos oficiais do Flower
(`flower_app/privacy.py`), com `dp-mode = "none"` por padrão.

Duas ressalvas que não podem ser omitidas em publicação:

1. **O DP é central.** O servidor vê as atualizações individuais antes de
   agregar e adicionar ruído. Isso exige confiar no servidor. Uma federação que
   não confie nele precisa de recorte no cliente mais agregação segura, ambos
   fora do escopo atual.
2. **Um ε só é reportável se for calculado.** `privacy.epsilon_for` usa o
   `dp-accounting` (extra `flwr[dp]`). Se a biblioteca não estiver instalada, ele
   retorna `None` em vez de estimar. Resultado publicado com DP deve vir
   acompanhado do ε efetivo, do δ e do número de rodadas.

## Publicação de resultados

Um resultado federado só é reportável se vier com o `RunManifest`
(`libs/federation_contracts`) preenchido: número de partições, esquema de
partição, estratégia, `proximal-mu`, modo de DP, ruído, recorte e orçamento.

Sem isso, o número não é reproduzível e, em particular, não se sabe se DP estava
ativo. `RunManifest.summary_lines()` existe para ser colado no relatório.
