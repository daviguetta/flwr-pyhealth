# Política de segurança

## Escopo

Este projeto processa dado clínico sensível. As regras de governança de dados
estão em [`docs/DATA_GOVERNANCE.md`](docs/DATA_GOVERNANCE.md) e são parte da
política de segurança, não documentação separada.

## Como reportar uma vulnerabilidade

**Não abra issue pública.** Uma issue pública em um projeto de federação descreve,
para qualquer leitor, como atacar uma federação em operação.

Use o canal privado do GitHub (*Security* → *Report a vulnerability*) no
repositório. Se o canal não estiver disponível, contate os mantenedores listados
em [`CITATION.cff`](CITATION.cff).

Inclua:

* o que é afetado (componente e versão);
* como reproduzir;
* o impacto, em especial se envolve exposição de dado de paciente;
* mitigação sugerida, se houver.

Prazo de resposta: 5 dias úteis para a primeira resposta.

## Se você commitou um segredo

Considere-o comprometido no instante do commit. Remover o arquivo em um commit
seguinte **não** basta: ele permanece no histórico e em qualquer fork.

1. Revogue e regenere o segredo (chave, token, certificado).
2. Remova do histórico com `git filter-repo` ou BFG.
3. Force-push coordenado com todos os forks conhecidos.
4. Registre o incidente.

`ca.key` e `server.key` são os segredos mais críticos: com eles é possível se
passar pelo servidor de agregação e receber as atualizações de modelo.

## Se dado de paciente foi commitado

1. Trate como incidente de dados, não como bug. Envolva o encarregado de dados
   (DPO) da instituição.
2. Remova do histórico **e** dos forks e caches de CI.
3. Avalie a obrigação de notificação conforme LGPD/HIPAA/GDPR. Um checkpoint é
   dado derivado de paciente: a exposição de pesos também é exposição.
4. Registre o incidente e a avaliação.

## Superfície de risco

| Vetor | Risco | Mitigação atual |
| --- | --- | --- |
| Servidor de agregação | Vê as atualizações individuais; DP central exige confiar nele | DP central; agregação segura **não** implementada |
| Porta `9093` (deployment API) | Quem alcança submete jobs à federação | Manter apenas na rede de administração — ver `env/incus/PORTS.md` |
| `--insecure` no transporte | Interceptação e forja de tráfego | Certificados gerados por `env/podman/certs.yml`, ainda **não** em uso |
| Imagem de contêiner | Imagem adulterada executa código no nó | Construir de `Containerfile.superexec`; registry interno |
| Dependências | Cadeia de suprimentos | `uv.lock` versionado para reprodutibilidade |
| Checkpoints em disco | Dado derivado de paciente | `output/` e `*.ckpt` ignorados pelo git |

As lacunas acima são limitações declaradas, não desconhecidas: ver a seção
[Limitações](README.md#limitações) no README.

## Boas práticas para contribuição

* Nunca use dado real da SESA em teste, exemplo ou fixture. Gere dado sintético.
* Nunca versione credenciais, chaves ou certificados.
* Nunca adicione dependência que exija chamada de rede em tempo de importação.
* Ao alterar a fronteira de serialização, confirme que só `ArrayRecord` e
  `MetricRecord` cruzam o nó.
