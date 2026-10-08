# HPC Shelf — o que falta para publicar, e um conceito que pedimos

Rascunho de mensagem para o orientador. O detalhamento técnico está nos arquivos
referenciados ao final; aqui ficam só o contexto e os pedidos.

## Contexto em três linhas

A camada de federação (Flower + PyHealth) está descrita como componentes do HPC
Shelf e passa no validador da plataforma. As imagens de unidade estão construídas
e testadas funcionalmente. Falta publicá-las no catálogo — o que depende de três
confirmações — e há **um** pedido de plataforma, na Parte 3: um conceito de
**serviço interno**. Nada de patch para a identidade por réplica: ela passou a ser
lida do próprio plano da unidade, e aquele pedido foi retirado.

> **Ordem de leitura.** A Parte 1 é operacional (publicar). A Parte 2 está
> **resolvida** e fica como registro do raciocínio. A Parte 3 é a única mudança de
> plataforma que ainda pedimos.

## Parte 1 — três confirmações para publicar

O caminho de publicação está pronto e foi ensaiado de ponta a ponta contra um
registry local: empurra as imagens, lê o digest que o **registry** reporta, monta
o `artifact.json` e o valida com o `FilesystemCatalog` e o `DeploymentPlanner` da
própria plataforma. Foram 18 verificações, sem falha. O que falta é apenas o
destino.

**1. Autorização e credenciais de escrita no registry do catálogo.** O
`deploy/catalog/DEVELOPER_WORKFLOW.md` do repositório de vocês é explícito que
escrita em registry exige escopo aprovado pelo operador. Não presumi nada, e
nada foi enviado.

**2. O caminho de projeto.** Os descritores declaram:

```text
catalog.hpcshelf.org/pyhealth/flower-hub:0.1.0
catalog.hpcshelf.org/pyhealth/flower-hospital:0.1.0
```

`pyhealth` é suposição minha. Se o namespace for outro, a referência muda e, com
ela, o `descriptor_digest`.

**3. Confirmação da base da unidade raiz.** O componente `federation-root` usa
`hpcshelf-unit-base` e reusa, por digest exato, o artefato já publicado no
release 1.4 — incluindo o arquivo Incus unificado de 501 MB
(`sha256:a17c7d8d…`), lido de
`catalog_data/components/root-two-host/1.4/artifact.json`. Reuso de imagem
inalterada por digest é o que o workflow de vocês prescreve; confirmar que essa
segue sendo a base correta, ou indicar a versão certa, resolve o item.

Com essas três respostas, a publicação é um comando:

```bash
scripts/publish_hpcshelf_images.sh --registry catalog.hpcshelf.org --project pyhealth
```

### Um comportamento que vale conhecer

`CatalogComponentArtifact` recusa um artefato cuja referência de imagem divirja
do campo `image` do descritor. Publicar em outro registry, portanto, **reescreve
o descritor publicado** e altera o digest. O script avisa em voz alta quando isso
acontece — e o ensaio ficou marcado como ensaio, não como catálogo de produção.
No registry declarado acima o descritor permanece intacto, e o digest é o já
registrado no repositório:

```text
flower-federation:0.1    sha256:2f7772db5a9b236dfa3d6cd707e2929f38db7ae6f091f961d70b1e7837e96d93
```

## Parte 2 — identidade da réplica: RESOLVIDO, patch retirado

> **Retirado em 2026-09-25. Não há pedido nesta seção.** A premissa abaixo
> estava errada: a plataforma já entrega a identidade por réplica. O UnitAgent
> grava o `UnitPlan` da própria unidade e injeta
> `HPCSHELF_UNIT_PLAN=/etc/hpcshelf/unit-plan.pb` no processo da aplicação, para
> unidades raiz **e** aninhadas (`hostagent/incus_bootstrap.py`,
> `unitagent/server.py`, `unitagent/real_podman_runtime.py`) — e `plan.replica`
> **é** o `partition-id`. O próprio `fl_unit/plan_identity.py` da plataforma o lê
> assim.
>
> O supervisor do hospital agora lê o mesmo plano
> (`env/hpcshelf/arms/grouped/images/supervise-hospital.sh`), então a lacuna #1 fecha **sem
> tocar na plataforma**. Verificado por `scripts/smoke_hpcshelf_images.sh` →
> **10 passed, 0 failed**, incluindo "a hospital derived its partition from its
> own unit plan" — e com um `PYHEALTH_PARTITION_ID` conflitante de propósito,
> para provar que o plano vence um binding compartilhado.
>
> O texto abaixo fica como registro do raciocínio. O patch foi **removido da
> árvore** na reorganização de `env/` (a proveniência fica no histórico git); a
> reserva só voltaria a fazer sentido caso `HPCSHELF_UNIT_PLAN` deixe de existir.

**O problema.** `application.environment` no descritor carrega **um valor
compartilhado por todas as réplicas**. Não há como uma unidade saber *qual*
réplica ela é. Para um serviço stateless não faz falta; para carga particionada,
faz. Cada hospital desta federação possui um shard disjunto do coorte, e o
SuperNode precisa ser informado disso:

```text
--node-config "partition-id=0 num-partitions=2"
```

Hoje esse valor teria que sair do descritor — que não o expressa — ou ser
adivinhado em tempo de execução. Adivinhar significa dois hospitais treinando no
mesmo shard enquanto o run reporta resultados federados. O cliente do projeto se
recusa a adivinhar, e é por isso que a implantação está bloqueada.

**A mudança.** O UnitAgent já resolve `unit_plan.replica` e já tem `id` e
`unit_name`. O patch os expõe ao processo da aplicação:

| Variável | Valor |
| --- | --- |
| `UNIT_ID` | id lógico da unidade (`…/hospital[1]`) |
| `UNIT_NAME` | nome público da unidade (`hospital`) |
| `UNIT_REPLICA_ID` | índice da réplica, base 0 (`1`) |

Um descritor que tente definir um desses nomes é **rejeitado na inicialização**,
não sobrescrito em silêncio: o binding é compartilhado por todas as réplicas e
poderia fazer duas delas assumirem a mesma identidade.

**Forma.** Uma constante e uma função em `unitagent/application_manager.py`, uma
chamada de três linhas em `unitagent/server.py::serve()`, quatro testes. Sem
mudança no validador, no formato dos descritores nem em qualquer invariante da
plataforma.

As duas cópias do UnitAgent (`unitagent/` e `podman-unit-base/unitagent/`) eram
byte-idênticas antes do patch; a alteração é aplicada em ambas, como o workflow
do repositório exige — e é por isso que o diff toca cinco arquivos para uma
mudança comportamental de três linhas.

**Verificação.**

```text
git apply --check <patch>                   aplica limpo
pytest tests/test_application_manager.py    6 passed
pytest                                      785 passed, 38 errors
```

A mesma suíte **sem** o patch: **781 passed, 38 errors**. Ou seja: +4 testes,
zero regressões. Os 38 erros são pré-existentes e não relacionados —
`AttributeError: module 'os' has no attribute 'pidfd_open'` em
`tests/test_full_lifecycle.py`, uma propriedade da máquina onde a suíte rodou —
idênticos antes e depois. O ambiente foi isolado (Python 3.12,
`pydantic==2.13.5`, `PyYAML==6.0.3`, pytest 9.1.1) e o patch foi desenvolvido em
uma cópia separada, de modo que o checkout da plataforma continua com
`git status` limpo.

**Ponto de desenho em aberto, para decisão.** Rejeitar o binding conflitante é
uma escolha; avisar e sobrescrever seria a alternativa mais branda. Optei por
falhar porque o modo de falha que isso evita é silencioso — mas é decisão de
quem mantém a plataforma, e está a um `raise` de distância de virar uma linha de
log.

## Parte 3 — um conceito que falta: serviço interno

Esta é a única mudança de plataforma que ainda pedimos. Ela não é necessária
para o que está funcionando — é o que dissolve uma escolha que hoje é forçada.

**O que já existe, e verificamos.** O endereçamento vertical funciona e não
precisa de patch. `_collect_forwarded_services` mantém a `published_port`
constante por todos os níveis (*"the published port propagates through
intermediate namespaces until the service-owning unit is reached"*), então a
unidade pai alcança o serviço da unidade aninhada no próprio namespace. E o pai
descobre o endereço sozinho: `UnitPlan.children` já traz os `ServiceEndpoint` de
todo descendente — demonstramos a leitura do plano devolvendo
`--appio-api-address 127.0.0.1:30000` sem nada injetado no ambiente.

**O que falta.** Não há como declarar que um serviço existe **só** para o pai.
`ServiceDefinition` tem `protocol`, `containerPort` e `environment` — nada de
escopo. E `hostagent/endpoint_publisher.py` publica **todos** os descendentes no
endereço VPN do host, recursivamente e sem filtro:

```python
# EndpointPublisher.build_publications
#   Root-owned service:       VPN:published -> Incus:container_port
#   Descendant-owned service: VPN:published -> Incus:published_port
for child in root_unit.children:
    for (... published_port, ...) in self._collect_services(child):   # recursivo
        publications.append(EndpointPublication(vpn_address=local_vpn_address, ...))
```

Medido nos dois desenhos, no `DeploymentPlanner`:

```text
3 níveis   link[0]  appio 9091 -> publicado:30000 @vpn:10.201.0.1   ← appio no endereço VPN
           node[0]  appio 9094 -> publicado:30000 @vpn:10.201.0.2
agrupado   hub[0]   fleet 9092 -> 30000                             ← appio não é service
```

**Por que isso importa.** A regra que o senhor enunciou é que *a unidade host
orquestra os serviços das unidades aninhadas*. Um serviço que existe só para o
pai orquestrar não deveria ser publicado na federação — e o `appio` não carrega
só tarefas: em Flower, as atualizações de peso viajam SuperExec → SuperNode por
AppIO e só depois pelo `fleet`. Publicá-lo no endereço VPN deixa o canal de peso
alcançável por qualquer host participante.

Isso também é o que obriga o agrupamento. Não é uma preferência de estilo: hoje
"separar as unidades" e "manter `appio` fora da rede" são incompatíveis. Foi por
isso que a Fase 3 concluiu que `M103` (o invariante de que `appio` não cruza
fronteira) estava sendo violado pela separação.

**O pedido.** Uma forma de declarar serviço interno — `scope: parent`, ou
qualquer nome que o senhor prefira — honrada em dois pontos: `EndpointPublisher`
não o publica, e `_collect_forwarded_services` mantém o encaminhamento apenas até
o pai imediato. Com esse conceito:

| | agrupado (hoje) | 3 níveis, sem o conceito | 3 níveis, com `scope: parent` |
| --- | :---: | :---: | :---: |
| `appio` só no namespace do pai | ✅ | ❌ | ✅ |
| Aninhamento `SuperExec → link`/`node` | ❌ | ✅ | ✅ |
| `appio` no endereço VPN | não | **sim** | **não** |

Ou seja: `M103` é um **proxy** do invariante, exato só enquanto a plataforma não
souber declarar serviço interno. Com o conceito, a separação deixa de ser um
trade e passa a ser escolha de conveniência. É uma mudança aditiva, no mesmo
formato do `0001` (campo no modelo + filtro no publicador + testes), e podemos
entregar o patch testado se o senhor concordar com o conceito.

## O que já está pronto e verificado

| Prova | Resultado | Comando |
| --- | :---: | --- |
| Desenho aceito pela plataforma | 28/28 | `scripts/validate_hpcshelf.sh` |
| Imagens funcionando (dois nós registram; identidade vinda do plano da unidade) | 16/16 | `scripts/smoke_hpcshelf_images.sh` |
| Conformidade com o modelo de componentes | 2/2 | `python -m libs.federation_components` |
| Caminho de publicação (registry local) | 18/18 | `scripts/publish_hpcshelf_images.sh --registry localhost:5000 --insecure` |

## Pedidos

1. Autorização e credenciais de escrita no registry do catálogo — ou o nome de
   quem as tem.
2. O caminho de projeto correto (o `pyhealth` está certo?).
3. Confirmação da base da unidade raiz (`hpcshelf-unit-base`, release 1.4).
4. **Decisão sobre a Parte 3:** aceita o conceito de serviço interno
   (`scope: parent`)? Se sim, entregamos o patch testado; se não, a decisão de
   agrupamento da Fase 3 volta a valer como estava, com o raciocínio preservado.

## Referências neste repositório

* [`docs/HPC_SHELF_DECISIONS.md`](HPC_SHELF_DECISIONS.md) — limitações, decisões e fases.
* [`docs/HPC_SHELF_RESULTS.md`](HPC_SHELF_RESULTS.md) — resultados das fases.
* ~~`env/hpcshelf/patches/`~~ — removido na reorganização de `env/`; o patch
  retirado (`0001-unit-identity-environment.patch`) e sua justificativa ficam no
  histórico git (`docs/HPC_SHELF_DECISIONS.md`, Fase 2).
* [`env/hpcshelf/arms/grouped/images/README.md`](../env/hpcshelf/arms/grouped/images/README.md) — como as
  imagens são construídas e o que a publicação exige.
