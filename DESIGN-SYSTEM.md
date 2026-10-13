# DESIGN-SYSTEM.md — Material Design 3 no ITAM Make

> **Este arquivo manda.** O `DESIGN.md` (marca) e o `DESIGN-PRO.md` (acabamento)
> valem no que não conflitar; onde conflitarem, vale este.
>
> Implementação: `static/css/make-m3.css`, carregado por último.

---

## 1. O que é M3, em cinco frases

Material Design 3 (Material You) é o sistema atual do Google. As cinco ideias
que decidem tudo:

1. **Elevação é superfície tonal, não sombra.** Um cartão "sobe" ficando um tom
   mais denso (`surface-container-low` → `container` → `high`), não ganhando
   sombra. Sombra só no que realmente flutua: menu, diálogo, FAB.
2. **Cor não é paleta, é papel.** Existe `primary` e existe `on-primary` — o par
   com contraste garantido. Você nunca escolhe "um verde": escolhe o papel
   (`primary`, `secondary-container`, `error`…) e o par `on-` vem junto.
3. **Forma é escala:** 4 · 8 · 12 · 16 · 28px, e pílula (`999px`) para botão e
   seleção. Nada de raio inventado.
4. **Interação é *state layer*.** Hover é a cor `currentColor` a **8%** por cima;
   pressionado, **12%**. Não se troca a cor de fundo do componente.
5. **Tipografia é a escala do Google** — display · headline · title · body ·
   label, cada um em L/M/S — em **Roboto**.

O resultado é minimalista por construção: quase nenhuma borda, quase nenhuma
sombra, hierarquia por tom e por tamanho de texto.

---

## 2. Papéis de cor (`make-m3.css` §1)

Paleta tonal derivada do verde da Make (`#00a651`). **Escreva o papel, nunca o
hex.** Todos têm par no escuro automaticamente.

| Papel | Para quê |
|---|---|
| `--md-primary` / `--md-on-primary` | ação principal, botão preenchido, links |
| `--md-primary-container` / `--md-on-primary-container` | destaque calmo, FAB, chip de número |
| `--md-secondary-container` / `--md-on-secondary-container` | **seleção** (item de menu ativo, aba ativa) |
| `--md-tertiary` / `--md-tertiary-container` | acento raro (o lima da marca) |
| `--md-error` / `--md-error-container` | erro de formulário, exclusão |
| `--md-surface` | o fundo da página |
| `--md-surface-container-low` | **cartão / painel** (o padrão) |
| `--md-surface-container` / `-high` / `-highest` | um nível "acima" cada, para aninhar |
| `--md-on-surface` | texto principal |
| `--md-on-surface-variant` | texto secundário, rótulo, ícone inativo |
| `--md-outline` | borda de campo |
| `--md-outline-variant` | divisor de tabela e de lista |

**Status do domínio** (fora do M3, mas necessário): `--md-st-crit`, `--md-st-warn`,
`--md-st-attn`, `--md-st-ok` — cada um com o seu `-cont` (contêiner tonal). Use
sempre o par: texto na cor, fundo no `-cont`. Há a classe pronta `.md-st--crit`
etc.

### Tokens antigos (`--ui-*`)
As telas escritas antes deste sistema usam `var(--ui-…)`. A §13 do
`make-m3.css` faz esses nomes **apontarem** para os papéis do M3, então nada
quebrou. Em tela **nova ou que você esteja migrando, use `--md-*`.**

---

## 3. Escala tipográfica

Classes prontas em `make-m3.css` §2 — `.md-headline-small`, `.md-title-medium`,
`.md-body-medium`, `.md-label-large`…

| Papel na tela | Estilo M3 | Valor |
|---|---|---|
| título de página | headline-small | 24/32 · 400 |
| título de seção | title-medium | 16/24 · 500 |
| rótulo de campo, coluna, overline | label-medium/small | 12/16 · 500 · `letter-spacing:.5px` |
| corpo | body-medium | 14/20 · 400 |
| texto de campo | body-large | 16/24 · 400 |
| botão, item de menu, aba | label-large | 14/20 · 500 |
| número grande de KPI | headline-medium ou display-small | 28/36 ou 36/44 · **400** |

**Peso 400 no número grande.** M3 não usa 800 — o destaque vem do tamanho, não
da gordura. Número em coluna leva `tabular-nums`.

---

## 4. Componentes

`make-m3.css` já reestiliza globalmente: **gaveta de navegação, top app bar,
cartão, tabela, campo, botão, chip** e os `.mkpro-*`. Não reescreva isso por tela.

### Gaveta de navegação
Item de 56px, pílula completa, ícone de 24px, `label-large`. Ativo =
`secondary-container` preenchido. É o elemento mais reconhecível do M3 —
não mexa.

### Botões
| Tipo | Quando | Como |
|---|---|---|
| **Filled** (`.pvx-btn--ok`) | a ação principal da tela — **uma** por tela | `primary` + `on-primary` |
| **Tonal** (`.pvx-btn--soft`) | ação secundária de peso | `secondary-container` |
| **Outlined** (`.pvx-btn--ghost`) | alternativa, cancelar | 1px `outline`, texto `primary` |
| **Text** | ação terciária, em lista/cartão | sem contêiner, texto `primary` |

40px de altura, pílula, `label-large`, *state layer* no hover. Sem sombra.

### Cartão
Padrão **filled**: `surface-container-low`, raio 12px, **sem borda e sem
sombra**. Para aninhar cartão dentro de cartão, suba um nível de tom
(`container` → `high`). Só use borda (`outlined`) quando o cartão for
selecionável e precisar de foco visível.

### Campo (outlined text field)
56px, raio 4px, borda 1px `outline`, 2px `primary` no foco. Rótulo **acima** em
`label-medium`, ajuda embaixo em `body-small`/`on-surface-variant`, erro em
`error` com ícone. Uma coluna até 640px.

### Tabela (data table)
Linha de 52–56px, divisor `outline-variant`, cabeçalho grudento em
`label-medium`/`on-surface-variant`, **sem zebra**, hover como *state layer* de
8%, números à direita.

### Chip
32px, raio 8px, borda `outline-variant`. Filtro aplicado vira chip com "×".

### Diálogo
`surface-container-high`, raio **28px**, sombra nível 3. Título `headline-small`,
corpo `body-medium`, ações no rodapé à direita (confirmar por último, cancelar
como *text button*).

### FAB
56px, raio 16px, `primary-container`. Uma por tela, para a ação mais frequente.

---

## 5. Como deixar minimalista (o que TIRAR)

O ganho de M3 vem mais de remover que de adicionar. Nesta ordem:

1. **Borda que só separa** → tire. Use um tom de superfície diferente ou um
   divisor `outline-variant` de 1px. Borda em volta de tudo é o oposto de M3.
2. **Sombra em cartão** → tire. Elevação é tom.
3. **Degradê** → tire. M3 é chapado.
4. **Peso 700/800 em texto pequeno** → 500 é o máximo em rótulo; corpo é 400.
5. **Maiúsculas em botão e em título** → só em overline/rótulo (`label-small`).
6. **Mais de uma cor de destaque na mesma tela** → uma ação principal, o resto
   tonal ou texto.
7. **Raio fora da escala** (10px, 13px, 14px, 20px) → 4 · 8 · 12 · 16 · 28.

---

## 6. Anatomia de uma tela

```html
<header class="mkpro-head">
  <p class="mkpro-head__eyebrow">Parque de máquinas · Tabela</p>   <!-- label-small -->
  <h1 class="mkpro-head__title">Computadores</h1>                  <!-- headline-small -->
  <p class="mkpro-head__sub">25 máquinas · clique numa linha para editar</p>
  <div class="mkpro-head__actions"><!-- filled por último --></div>
</header>

<!-- barra de filtros: chips, sem cartão em volta -->
<!-- conteúdo: tabela, quadro, mapa ou formulário -->
```

---

## 7. O que NÃO pode mudar

- **Regra de negócio.** Nenhuma. Nada de alterar o que a tela calcula, valida,
  grava ou decide.
- **Hooks de JavaScript**: `id`, `data-*` (`data-tf-open`, `data-ver`,
  `data-cal-cell`, `data-chart-*`…), `name`, `onclick`, `x-data`/`x-on`, e
  qualquer classe citada em `static/js/make-admin.js`. **`grep` antes de remover
  qualquer classe.**
- **URLs, formulários, campos, `csrf_token`, método.**
- **Ilustrações do parque** (mesa, monitor, prateleira, caminhão, avatar) e o
  zoom da máquina — identidade do produto.
- **Permissões**: nada de mostrar botão que a view bloqueia.

---

## 8. Checklist por tela

- [ ] Cor só por `var(--md-*)` (ou `--ui-*` legado); nenhum hex solto
- [ ] Nenhuma borda que só separava — virou tom ou divisor
- [ ] Nenhuma sombra em cartão
- [ ] Raio na escala 4/8/12/16/28
- [ ] Tipografia na escala M3; número grande com peso 400
- [ ] Uma única ação *filled* por tela
- [ ] Tabela sem zebra, cabeçalho grudento, hover de 8%
- [ ] Campo outlined com rótulo acima e ajuda embaixo
- [ ] Claro **e** escuro conferidos
- [ ] 1280px e 1024px sem rolagem horizontal na página
- [ ] `manage.py test apps` verde

---

## 9. Pegadinhas deste repositório

1. **`{# … #}` no Django é comentário de UMA linha.** Multi-linha tem de ser
   `{% comment %}…{% endcomment %}` — senão o texto vaza para o HTML e qualquer
   `{% tag %}` dentro dele **executa** (já causou recursão infinita aqui).
2. **`make-admin.css` (5,3 mil linhas) usa `!important` em quase tudo.** Para
   vencer sem apagar, ponha um id a mais no seletor (`#page #nav-sidebar …`).
3. **A rede de fumaça é obrigatória:** `manage.py test apps` abre ~40 telas e
   exige 200. É ela que pega `{% if %}` sem `{% endif %}`.
4. **Nunca aponte para o banco de produção.** Revisão visual roda com
   `DATABASE_URL` num SQLite de rascunho.
5. **A logo da Make é branca** com o símbolo em lima: precisa de contêiner
   escuro nos dois temas (`primary` no claro, `primary-container` no escuro).
6. **`static/css/make-ui.css` é o sistema anterior** (hairline, Figtree),
   mantido no disco e **fora** do `STYLES`. Trocar uma linha em
   `config/settings/base.py` volta para ele.

---

## 10. Camada m3.material.io (04/09/2026)

Referência dada pelo dono: **https://m3.material.io/styles/icons/overview**, com o
pedido de "copiar na cara dura esse estilo desse site" e "essas animações eu quero".
Implementada em `static/css/make-m3.css` §19. Onde discordar da §18 (Midbox),
**vale a §19** — ela é a mais recente e é a que o dono está olhando.

### 10.1 Borda é elemento de design, não sujeira

Era a queixa direta ("está faltando uns detalhes de borda"). O site do M3 usa a
variante **outlined** em quase tudo; a §18 tinha ido de *filled* (só tom, sem borda).

| Peça | Antes (§18) | Agora (§19) |
|---|---|---|
| Cartão | tom, sem borda | `1px solid var(--md-outline-variant)`, raio 16px |
| Bloco grande | raio 12px | raio 28px, padding 24px |
| Campo | preenchido, sem borda | **contornado**, fundo transparente, raio 8px |
| Foco do campo | anel interno 2px | borda `primary` + anel interno 1px |
| Botão | raio 8px | **pílula** (`--md-shape-full`) |
| Chip / badge | fundo tonal | contorno de 1px, raio 8px |
| Tabela | divisor fraco | `outline` no cabeçalho, `outline-variant` nas linhas |
| Cartão clicável (hover) | subia de tom | **contorno vira `primary`** |

O que **não** mudou: a paleta (verde/lima da Make é marca), a ação em lima com
texto escuro, a pílula de seleção da gaveta, a fonte Figtree.

### 10.2 O ícone que se preenche

Assinatura da página de ícones do M3. Material Symbols é **fonte variável** com
quatro eixos — `opsz`, `wght`, `FILL`, `GRAD` — e o site anima o `FILL` de 0
(contorno) a 1 (sólido). Até agora o eixo estava parado em 0.

- Repouso: `'FILL' 0, 'wght' 300` — contorno, leve.
- Hover em algo clicável: `'FILL' .6, 'wght' 500` — engrossa e começa a encher.
- **Item de navegação ativo: `'FILL' 1`** — sólido. É regra do M3: o
  preenchimento diz "você está aqui", junto com a pílula.
- Transição de 260ms na `font-variation-settings` (o Chrome interpola).

Nenhuma fonte nova entra: o `make-admin.css:11` já importa a variável com os
quatro eixos. Um `@import` no fim de um CSS seria ignorado pela spec de qualquer
jeito. Verificado na tela que a fonte responde ao eixo (contorno → sólido).

Os ~500 ícones das telas próprias são **SVG de linha** e não têm eixo `FILL`.
Eles recebem o mesmo vocabulário por outro caminho: `stroke-width` 2 → 2.6 no
hover. Não vale reescrever 500 SVG para Material Symbols só por simetria.

### 10.3 O menu tem UM botão

Havia dois, e faziam coisas diferentes: o do unfold, na barra do topo,
**escondia** a barra inteira; um meu, no rodapé dela, **recolhia** para ícones.
Sobrepostos, davam estado quebrado.

Agora é um só, na barra do topo — onde a própria gaveta nunca o cobre:

- **≥ 1280px** → recolhe para a régua de ícones de 76px;
- **< 1280px** → abre/fecha a gaveta sobreposta, clicando no gatilho nativo do
  unfold (o `<span x-on:click="sidebarToggle()">` fica no DOM, escondido). Usar
  o Alpine dele em vez de mexer no estado interno por fora sobrevive a upgrade.
- Ao estreitar a janela, a régua se desfaz sozinha — não existe estado sem saída.

O `X` dentro da gaveta continua, só abaixo de 1280px: com a gaveta aberta ela
cobre o botão do topo, então é o único jeito de fechar por dentro.

> **Armadilha de especificidade (custou o bug):** o recolhimento antigo vivia no
> `make-admin.css` com seletores `body.mkx-side-collapsed #nav-sidebar-apps ol li a`
> — **1 id**. As regras do M3 são `#page #nav-sidebar-apps ol li a` — **2 ids**.
> Dois ids ganham de um: a casca encolhia e os rótulos ficavam, cortados no meio
> da palavra. O estado recolhido foi refeito na §19.9 com
> `body.mkx-side-collapsed #page ...` (2 ids + 1 classe), que ganha das duas.
> **Regra:** ao mexer na barra lateral, confira a especificidade contra as duas
> camadas — não basta `!important`.

O rótulo é escondido pelo que ele é (`span:not(.material-symbols-outlined)`), e
não com `font-size: 0` como antes — Material Symbols é FONTE, e o `font-size: 0`
apagaria o ícone junto.

---

## 11. Consertos de 04/09/2026 (o que o dono apontou na tela)

### 11.1 O menu: um botão, e estado próprio

Havia dois controles com efeitos diferentes (o do tema escondia a barra; o meu
recolhia para ícones). Ficou **um**, na barra do topo, onde a gaveta nunca o cobre.

**A visibilidade da gaveta é NOSSA, não do Alpine do unfold.** O tema guarda
`sidebarOpen` e escreve `display: none` no *estilo em linha* do invólucro.
Acionar o `sidebarToggle()` dele mudava o valor e **não re-executava o `x-show`**
— o `display: none` em linha ficava, a gaveta não voltava e o menu ficava morto.
Pior: `sidebarOpen` nasce como *método*, então `!método` é `false` e o primeiro
toggle nem chegava a abrir.

Regra atual (`make-m3.css` §19.12 + `make-admin.js`):

| Largura | Quem manda | O botão faz |
|---|---|---|
| **> 1280px** | CSS: gaveta **sempre** visível (`!important` ganha do estilo em linha) | alterna gaveta cheia ↔ régua de 76px (`mkx-side-collapsed`) |
| **≤ 1280px** | classe `mk-gaveta-aberta` no `<body>`, e só ela | abre/fecha a gaveta sobreposta (clique fora e Esc fecham) |

O limite de 1280px é **o mesmo do unfold** (`innerWidth <= 1280`). Eu havia
escrito `>= 1280`: em exatamente 1280px — largura de janela comuníssima — os
dois discordavam e o menu morria. **Ao mexer em breakpoint, use o dele.**

Também: `init()` no `make-admin.js` agora roda cada `initXxx()` dentro de
`seguro()`. Eram ~40 chamadas cruas em sequência — uma exceção matava todas as
seguintes, e o controle do menu estava no fim da fila. Ele agora é o primeiro.

**Sem transição de largura na gaveta**, de propósito: a barra é `fixed` e quem
reserva o espaço é outro elemento; animando os dois em paralelo eles saem de
sincronia e a gaveta passa por cima do conteúdo.

### 11.2 A gaveta encosta no topo e tem borda

Sobra do "painel de vidro" antigo: `make-admin.css:4561` a tratava como cartão
flutuante (`top: 12px; bottom: 12px; border-radius: 0 20px 20px 0`). E a §3 do M3
tinha `border: 0`, que matou junto o `border-r` do unfold. Agora é gaveta de
verdade: colada no topo e no rodapé, altura cheia, uma linha de 1px em
`outline-variant` que sobe até o topo da página (§19.10).

### 11.3 Curvas da gaveta = 16px

Item de menu, pílula de seleção e caixa de busca em `--md-shape-lg`, não em
pílula. O raio já era o mesmo dos botões; o que muda é a **largura** — um item de
38×250 em pílula lê como comprimido, não como botão (§19.11).

### 11.4 As telas de autenticação saíram do M3

Decisão do dono: *"a tela de bloqueio tava bonita antes com aquele tema espelhado
escuro. Deixa só ela daquele jeito"*.

- O bloco M3 e o bloco Midbox foram **removidos** do `make-auth.css`.
- O `make-m3.css` **não é mais linkado** em `registration/_auth_base.html`. As
  regras genéricas dele (campo, `input[type=submit]`, cor de texto) pintavam por
  cima e o painel de marca ficava com texto escuro sobre verde — ilegível.
- Os `.mkauth*` foram tirados do `make-m3.css` para ninguém achar que o M3 manda
  ali.
- O tema **claro** ganhou o mesmo vocabulário de vidro do escuro (chão tingido +
  painel translúcido + brilho no topo + malha), preso a `html:not(.dark)`.

**Consequência aceita:** as quatro telas de entrada ficam fora do sistema M3.
Mexer no M3 não toca nelas, e vice-versa.

### 11.5 A armadilha de cache que fez tudo parecer não funcionar

Duas causas somadas, e valem para qualquer mudança de CSS/JS daqui em diante:

1. **O servidor serve o `staticfiles/`, não o `static/`.** Editar a origem sem
   `collectstatic` entrega arquivo velho. Pior: o `?v=` vinha do mtime da
   **origem**, então a URL anunciava versão nova servindo conteúdo velho — e o
   navegador guardava o conteúdo VELHO sob a URL NOVA, sem saída sem limpar
   cache à mão. **Foi assim que o botão de menu ficou morto na máquina do dono.**
   `_asset_versionado` agora lê o mtime do arquivo **servido**.
2. **Link sem versão.** O `make-auth.css` era linkado com `{% static %}` puro.
   Existe agora `{% mkstatic %}` (`apps/parque/templatetags/mkassets.py`) com a
   mesma regra. **Todo link de CSS/JS próprio deve usar `mkstatic` ou entrar no
   `UNFOLD["STYLES"]`.**

E duas armadilhas de *medição*, que me fizeram perseguir fantasmas:

- **Aba em segundo plano não avança quadros.** Uma transição de `width` nunca
  termina e a largura fica travada no valor inicial — o que faz uma regra
  `!important` correta *parecer* não funcionar. Confira layout com a aba visível.
- **Template compilado em cache.** Com `runserver --noreload` (e o
  `cached.Loader`), editar template não muda o HTML servido. Reinicie o processo.

## 12. Rodada de 04/09/2026 — tarde (o que quebrou e por quê)

### 12.1 Ícone de 300×150px: NÃO mova botão de tela para a barra de cima

O `initTopoUnico()` levava `.mkpro-head__actions` para dentro da barra do topo.
Cada tela dimensiona o próprio ícone num seletor **escopado no bloco dela** —
`.rkb .pvx-btn svg { width: 18px }` em `reparos_kanban.html`, e o equivalente em
mais de vinte telas. Tirando o botão de dentro de `.rkb`, esse seletor deixa de
casar e o `<svg>` volta ao **tamanho padrão de substituição do navegador:
300×150px**. Resultado: topo estourado e página mais larga que a janela.

Regra: **mover nó entre containers só é seguro se o CSS dele não depender do
container.** A relocação foi removida; sobrou a trava `§22` da make-m3.css, que
limita SVG na barra do topo a 22px caso algum navegador ainda tenha o JS antigo
em cache.

### 12.2 `{# … #}` de novo

O comentário multilinha com `{# #}` **vazou como texto na tela** (o dono viu a
frase inteira impressa acima do conteúdo). Só `{% comment %}…{% endcomment %}`
atravessa mais de uma linha. Já estava escrito na §9 — e aconteceu outra vez.

### 12.3 Inserir função "antes do `def`" pode roubar o decorador

Inserir um helper imediatamente antes de `def preventiva_kanban(request):`
colocou o código **entre o `@staff_member_required` e a view**: o decorador
passou a decorar o helper (`AttributeError: 'list' object has no attribute
'user'`). Ao inserir antes de uma função, ancore **acima dos decoradores**.

### 12.4 Filtro só aparece onde a view sabe filtrar

O grupo "Preventiva vence" foi escrito dentro de `_filtros.html` sem condição e
sem `hidden` — apareceu **aberto em toda tela** que inclui o parcial (inclusive
o quadro de chamados, que não filtra por vencimento). Correção: o grupo é um
dropdown normal (`data-mkdd` + `data-mkdd-btn` + painel `hidden`) e só entra com
`com_data=True`, passado apenas pelo mapa completo.

### 12.5 As três telas fora de esquadro

Medido com a animação de entrada já terminada (medir durante ela dá número
errado): Início e Dashboard tinham o cabeçalho 10px mais baixo e 2px à direita
porque embrulham a tela em `.make-dash > .make-dash-inner`, que somam
`padding: 4px 0 24px` + `6px 2px 48px`. O Mapa tinha o título a 103px por causa
do ícone de 44px no cabeçalho. `§23` zera o padding do embrulho e esconde o
ícone: as três passaram a bater com as telas de manutenção (cabeçalho 24/20px,
título a 39px).

### 12.6 Ajuda e avisos moram no Assistente

O `?` e o sino saíram da barra do topo (decisão do dono). A lista de
notificações virou `unfold/helpers/_avisos.html`, renderizada escondida no fim
do `<header>` e **adotada** pelo `make-assistente.js` para dentro do painel. Só
é seguro mover esse nó porque o `x-data="{openNotif}"` do sino foi removido —
Alpine destrói o estado de qualquer subárvore reparentada. O contador de não
lidas virou selo no botão flutuante.

### 12.7 Gráfico no estilo do modelo

O gráfico "Manutenção preventiva por mês" do Dashboard passou a área macia
(`fill: origin`, `tension: .45`, sem grade, sem eixo Y, ponto só no hover) via
`OPCOES_AREA` em `apps/dashboard.py` — os outros gráficos ficaram como estavam.
As telas de preventiva ganharam `parque/_prev_grafico.html`: mesma linguagem,
desenhada no servidor (`_grafico_preventiva()` + `_curva_svg()`), sem JS e sem
biblioteca. A série é conclusão real (`Reparo.concluido_em`): preventivas x
corretivas por semana, com estado vazio próprio enquanto não houver histórico.

## 13. Rodada de 04/09/2026 — noite

### 13.1 Agenda no topo (o que substituiu a faixa vazia)

`unfold/helpers/_agenda_topo.html` + `initAgendaTopo()` + `/agenda/eventos/`.
Sempre visível fica só a pílula pequena e **centralizada** (data + hora + ponto
quando há aviso não lido), como na referência do dono (central do GNOME). O
painel abre com **avisos e solicitações** à esquerda — o bloco `_avisos.html`,
que veio do antigo sino — e o **mês** à direita, com ponto nos dias que têm
evento e a lista do dia embaixo.

Os eventos são buscados **só quando o painel abre**, e sempre de um mês: a barra
aparece em toda tela e `preventiva_vencimento` é propriedade calculada, não
coluna. Fontes: vencimento de preventiva (baias + notebooks), transferências e
movimentações pendentes, chamados com prazo no mês e preventivas concluídas.

### 13.2 A barra do topo não tem fundo

Quem pintava a faixa escura era o `<style>` de `header.html`
(`#main > header.make-header { background: var(--md-surface) !important }`) —
mesma força da regra em make-m3.css e **depois** no documento, então ganhava. A
correção foi no dono da regra, não com mais um `!important` empilhado.

### 13.3 Filtro igual em toda tela

`initFiltrarPopup` deixou de exigir `.mpa-fbar`: o host agora é o **pai de
`.flt-bar`**, qualquer que seja a classe. Por isso o mapa tinha "Filtrar" e a
Tabela, os Notebooks e os Setores continuavam com dropdowns crus — as "visões
distintas" que o dono apontou. O período de compra da tabela também entra no
popup. Dentro dele: duas colunas, calendário de intervalo, **um** Aplicar.

### 13.4 Assistente com altura fixa

O painel era `bottom: 0` + `max-height`: crescia para cima e **empurrava o campo
de digitar**. Agora tem altura fixa; topo, busca e rodapé param, só o corpo
rola. Os avisos saíram de lá (moraram no assistente por uma hora) e foram para
a agenda do topo.

### 13.5 Duas pegadinhas de especificidade que custaram caro

**`:has()` conta o id de dentro.** `#page #nav-sidebar div:has(> #nav-filter)`
vale 3 ids e ganhava de `#page #nav-sidebar .mksrch-box.mksrch--lupa` (2 ids +
2 classes) mesmo com `!important` dos dois lados — foi o "ícone de pesquisa
estranho".

**`.bloco a` ganha de `.bloco-btn`.** `.mkhome a { color: inherit }` é (0,1,1) e
`.mkhome-head__cta { color: var(--md-on-action) }` é (0,1,0): o botão lima
herdava a tinta clara da tela e ficava com texto branco sobre verde-limão. O
padrão `.bloco a { color: inherit }` existe em quase toda tela, e quase toda
tela tem um botão `--ok` em lima — daí a §35 do make-m3.css resolver de uma vez,
inclusive `-webkit-text-fill-color`.

### 13.6 `seguro("x", x)` não protege contra função inexistente

O wrapper `seguro(nome, fn)` pega exceção **dentro** de `fn`, mas
`seguro("initX", initX)` resolve o identificador ANTES da chamada: apagar uma
função dessas gera `ReferenceError` que escapa do try/catch e **derruba o
`init()` inteiro** — menu, popup, tema e agenda param de montar de uma vez, sem
erro visível na tela. Aconteceu hoje ao reescrever um bloco vizinho.

Verificação: `node scratchpad/checar_init.js static/js/make-admin.js` confere
que toda função chamada na fila existe no arquivo. Rode depois de editar o JS.

### 13.7 Aviso e item ativo não têm contorno

Regra que o dono repetiu o dia inteiro: **fio fininho para destacar bloco
irrita**. Saíram: o anel do item de menu (era `box-shadow: inset 3px 0 0` da
base histórica), a borda do menu da conta (inclusive no hover), a moldura dos
cartões de aviso e a borda do campo de busca das listas. Separação por **tom e
espaço**, sempre.

### 13.8 Telas do admin: barra sem texto, tabela com moldura

Três pedidos do dono nas telas de ADMINISTRAÇÃO (as do Django/unfold, não as
próprias):

1. **Tabela sem laterais.** `#result_list` estava com `border: 0` (a camada M3
   zerou) e as células só com `border-bottom`: as divisórias corriam até o fim
   e a tabela não fechava. A moldura voltou no invólucro (`.tab-wrap`, que é
   quem tem raio e rolagem), a última linha perdeu o filete e o cabeçalho ficou
   com um só. Sem régua vertical entre colunas — no M3 coluna se separa por
   espaço. (§38)
2. **Nada de "caminho".** Saíram a navegação por data do Django (`ul.toplinks`,
   o "← 2026 · 3 de Setembro") e a trilha `nav.mkhdr__trail`. O filtro por data
   continua no painel "Filtros". (§39)
3. **Texto nenhum na barra do topo.** O `h1` do unfold É o caminho
   (`a(app) + chevron + a(tela)`); o dono pediu para não sobrar texto nenhum,
   então o `h1` inteiro sai. A barra fica só com controle: gaveta, voltar,
   agenda e "+". O nome da tela vive no cabeçalho-cartão (telas próprias), na
   aba do navegador e no item marcado do menu.

E `--md-outline-variant` no escuro subiu de `#2b332d` para `#3a443d`: a antiga
ficava a dois pontos do fundo e o contorno dos cartões desaparecia (o dono
pediu mais opacidade na tela do agente). Continua discreta — quem separa por
tom continua separando por tom.

---

## 14. Rodada de 04/09/2026 — a subida da 2.0

Sete armadilhas novas, todas medidas. Estão aqui porque cada uma me fez dar
uma correção por resolvida quando não estava.

### 14.1 `z-index` não atravessa contexto de empilhamento

No celular a pílula da data ficava **por cima** da gaveta aberta. Baixar o
`z-index` da pílula para 30 não mudou nada — e não mudaria nunca: ela mora
dentro de `header.make-header`, que tem `z-index: 600`; a gaveta mora em outro
irmão, com `z-index: 60`. Entre irmãos vale o índice do PAI. Nenhum valor
dentro do header ganha da gaveta.

Quando dois elementos de subárvores diferentes se cruzam, o que resolve é
mexer no ancestral que cria o contexto — ou, como aqui, esconder um enquanto o
outro está aberto.

### 14.2 `transform` no pai captura o `position: fixed` do filho

O painel da agenda abria com **111px** de largura no telefone, mesmo com
`left: 8px; right: 8px`. Motivo: `.mkag` (o pai) tem
`transform: translate(-50%, -50%)` para centralizar — e **um `transform`
transforma o elemento em bloco contêiner de qualquer descendente `fixed`**.
Os 8px passaram a ser medidos contra a pílula de 127px: 127 − 16 = 111.

No desktop funcionava por coincidência aritmética. O mesmo defeito escondia o
botão Ajuda inteiro fora da tela (alça em 415px numa janela de 375px), porque
o `translateX` do minimizar arrastava o `fixed` junto. Regra: se um filho é
`fixed`, o pai não pode ter `transform` — centralize com flex.

### 14.3 Em container grid, cada pedaço de texto vira um item

`<li>` com `display: grid` e o passo escrito como `Abra o <b>mapa</b> da loja`
não produz "rótulo | texto": produz **três** itens de grade — "Abra o",
"mapa", "da loja" — que a auto-colocação espalha pelas células. O que caiu na
coluna de 24px do número saiu uma palavra por linha. Foi o "formatação de
texto toda errada" do dono.

Conteúdo em linha dentro de flex/grid precisa de UM elemento que o embrulhe.

### 14.4 `.0` em string vazia derruba a página

`{{ user.get_full_name.0|default:user.get_username.0 }}` funcionou por meses e
dava 500 na `/ajuda/` — a única tela que abre sem login. Com visitante
anônimo os dois métodos devolvem `""`, e `"".0` levanta
`VariableDoesNotExist`. O Django **silencia** essa exceção na variável
principal, mas **não** em argumento de filtro: ali ela sobe e mata o request.

Use `|slice:":1"`, que devolve vazio para vazio.

### 14.5 `max_length` roda antes do validador

Os campos de documento guardam só dígitos, e a limpeza estava no `save()`.
Resultado: colar `529.982.247-25` — o formato em que o CPF existe em toda nota
e planilha — devolvia "certifique-se de que o valor tenha no máximo 11
caracteres (ele possui 14)". Mensagem que não diz nada e culpa quem digitou
certo.

`max_length` é conferido em `_clean_fields()`, antes de qualquer `clean()`
nosso. Para aceitar máscara é preciso folgar o limite **no campo do
formulário** (e tirar o `maxlength` do widget, senão o navegador corta a
digitação) e só então normalizar.

### 14.6 Toda tela que estende `admin/base_site.html` precisa do `each_context`

A tela nova de Cadastros abriu **sem menu, sem cabeçalho e sem o painel de
avisos** — e, por consequência, mensagem de ação nenhuma aparecia nela: ia
para a fonte escondida e ninguém adotava. A causa era uma linha ausente:
`**dj_admin.site.each_context(request)` no contexto.

É o `each_context` que traz navegação, título e os parciais do topo. As outras
39 views chamam; a nova, não. Se for tela de admin, chame.

### 14.7 Regra que mira classe inexistente não avisa nada

Três blocos do `make-m3.css` (§36 e §43.4) corrigiam a lupa de Fora de uso, de
Peças e do Agente mirando `.fu-busca`, `.tp-busca` e `.agx-busca`. **Nenhuma
das três existe** em template algum — os nomes reais são `.fu-search`,
`.tp-search` e `.agx-filtros`. A folha carregou, o navegador não reclamou, e
por duas rodadas eu li a regra como prova de que o defeito estava resolvido.

CSS morto é pior que CSS ausente: parece conserto. Ao escrever regra para uma
tela, confirme o nome da classe **no template**, não na memória.
