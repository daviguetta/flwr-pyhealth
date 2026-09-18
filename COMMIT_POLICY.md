# Política de commits

Regras de commit deste repositório e como elas são verificadas
automaticamente.

## Formato

[Conventional Commits](https://www.conventionalcommits.org/), com o **tipo em
inglês** e a **descrição em português no imperativo**:

```
<tipo>(<escopo>): <descrição>

<corpo: por que a mudança existe>

<rodapés>
```

O tipo em inglês mantém a mensagem legível por ferramentas e por quem lê o
repositório de fora; a descrição em português serve a quem decide no projeto.
É a mesma divisão que vale para o código: comentários em inglês, documentação em
português.

## Tipos

| Tipo | Quando usar |
| --- | --- |
| `feat` | Nova capacidade na camada de federação |
| `fix` | Correção de defeito |
| `docs` | Apenas documentação |
| `test` | Apenas testes |
| `refactor` | Reorganização sem mudança de comportamento |
| `perf` | Ganho de desempenho |
| `build` | Dependências, empacotamento, imagem de contêiner |
| `ci` | Automação de integração |
| `chore` | Manutenção que não se encaixa acima |
| `revert` | Reversão de um commit anterior |

## Escopos

Use o menor escopo que descreve a mudança:

| Escopo | Área |
| --- | --- |
| `fed` | `flower_app/` — ServerApp, ClientApp, estratégias |
| `data` | `flower_app/task.py` — pipeline e particionamento |
| `privacy` | DP |
| `xai` | Explicabilidade |
| `contracts` | `libs/federation_contracts/` |
| `env` | `env/`, `podman-compose.yml`, `Containerfile.superexec` |
| `deps` | `pyproject.toml`, `uv.lock` |
| `docs` | `README.md`, `docs/` |
| `repo` | Configuração do repositório |

O escopo é opcional, mas obrigatório quando a mudança afeta apenas uma área.

## Regras

1. **Um commit, uma mudança lógica.** Se a mensagem precisa de "e", provavelmente
   são dois commits.
2. **Imperativo e sem ponto final.** "Corrige o split por paciente", não
   "Corrigi" nem "Corrigido".
3. **Assunto com no máximo 72 caracteres.** Verificado pelo hook.
4. **O corpo explica o porquê, não o quê.** O `git diff` já mostra o quê. Este
   repositório vale pelas decisões.
5. **Referencie o issue** com `Refs: #12` ou `Closes: #12`.
6. **Mudança incompatível** leva `!` depois do escopo e um rodapé
   `BREAKING CHANGE:` explicando o que quebra.

## Regras específicas deste repositório

Estas decorrem dos requisitos do projeto e são verificadas em revisão, não pelo
hook — o hook não lê intenção.

### 1. Dado de paciente

Um commit **nunca** adiciona dados de paciente além do MIMIC-IV Demo já
versionado. Ver `docs/DATA_GOVERNANCE.md`. O hook bloqueia caminhos e extensões
conhecidas, mas ele não sabe distinguir dado sintético de real: isso é
responsabilidade de quem commita.

Se você commitou um dado por engano, não faça um commit seguinte removendo-o —
ele permanece no histórico. Siga `SECURITY.md`.

### 2. Mudança arquitetural atualiza o diagrama

Toda mudança de topologia, fluxo de dados ou fronteira entre componentes
atualiza o diagrama Mermaid correspondente em `docs/ARCHITECTURE.md` **no mesmo
commit**. Diagrama desatualizado é pior que ausente.

### 3. Estratégia de agregação cita a referência

Ao adicionar ou alterar uma estratégia de agregação, o corpo do commit traz a
referência original. Já em uso: FedAvg (McMahan et al., 2017), FedProx (Li et
al., 2020).

### 4. Mudança que afeta privacidade declara o impacto

Qualquer alteração em `flower_app/privacy.py`, no `dp-mode`, ou no que é
serializado em um `Message` exige um rodapé:

```
Privacy: <o que mudou no orçamento ou na fronteira de dados>
```

Se o modo de DP for alterado, o novo ε efetivo (ou `ε não calculado, dp-accounting
ausente`) deve aparecer. Sem isso não se sabe se o resultado publicado tem DP.

### 5. Resultado reportado traz o manifesto

Um commit que adiciona número de resultado (relatório, tabela, figura) inclui o
`RunManifest` correspondente, gerado por `libs/federation_contracts`:

```
Manifest: {"contract_version":"1.0.0","federation":{"num_partitions":2,...},
           "privacy":{"mode":"none",...},"experiment":{...}}
```

Sem o manifesto o número não é reproduzível, e em particular não se sabe se a
federação era real nem se DP estava ativo.

## Exemplos

```
fix(data): corrige partição por paciente para evitar vazamento entre nós

Os subsets de `split_by_patient` não expõem mapeamento de índice utilizável:
`patient_to_index` continua listando todos os pacientes e os índices inteiros
são rebaseados para o subset. O split passa a ser calculado a partir de
`patient_to_index` global, com seed explícita.

Closes: #8
```

```
feat(privacy): aplica DP central com os mecanismos oficiais do Flower

O Flower 1.34 traz DifferentialPrivacyServerSideFixedClipping, então a
estratégia de agregação passa a ser envolvida em vez de reimplementada. DP
segue desligado por padrão: ligar DP muda os números.

Reference: McMahan et al., ICLR 2018, arXiv:1710.06963
Privacy: dp-mode=none por padrão; com server-fixed-clipping e ruído 1.0,
         ε ≈ 17.9 (δ=1e-5, 2 clientes, 10 rodadas)
```

```
docs(env): documenta que só a porta 9092 deve cruzar fronteira de unidade

O compose publica cinco portas no host, o que é correto em uma máquina e
incorreto em multi-unidade, onde 9093 exposta permite submeter jobs à federação.
```

Mensagens ruins:

```
ajustes                      # sem tipo, sem informação
fix: corrigi um bug.         # passado, com ponto final, sem escopo
feat(fed): adiciona FedProx e DP e refatora o particionamento   # três mudanças
```

## Verificação automática

Hooks versionados em `.githooks/`:

| Hook | Verifica |
| --- | --- |
| `commit-msg` | Formato, tipo, escopo, tamanho do assunto |
| `pre-commit` | Segredos, certificados, checkpoints, dados fora do demo, arquivos grandes |

Habilite uma vez por clone (o git não versiona `core.hooksPath`):

```bash
git config core.hooksPath .githooks
```

Para verificar manualmente:

```bash
.githooks/commit-msg .git/COMMIT_EDITMSG
```

Um hook é uma barreira, não uma prova: ele bloqueia o que reconhece como
proibido, e nada mais. A revisão de PR continua sendo a última linha.

## Casos especiais

| Situação | Procedimento |
| --- | --- |
| Merge commit | O hook aceita `Merge ...` e não valida o formato |
| Reversão | `revert: <assunto original>` mais um corpo explicando o motivo |
| Trabalho em andamento | Não commite. Use `git stash`, branch ou `--fixup` |
| Correção de commit anterior | `git commit --fixup <sha>` e `git rebase -i --autosquash` |
| Correção de segredo já commitado | Ver `SECURITY.md`. Reescrever histórico, não empilhar commit |

## Versionamento

O projeto está em `0.1.0` e ainda não publica releases. Quando passar a publicar,
`feat` incrementa `MINOR`, `fix` incrementa `PATCH` e `BREAKING CHANGE` incrementa
`MAJOR` enquanto a versão for `< 1.0.0`.
