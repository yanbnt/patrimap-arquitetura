/* =============================================================================
   make-assistente.js — Assistente de ajuda do ITAM (widget flutuante).

   Monta o botão e o painel por JavaScript, sem tocar em nenhum template: assim
   o assistente aparece em TODA tela do sistema e some tirando esta linha do
   UNFOLD["SCRIPTS"].

   Conversa com /ajuda/assistente/?q=… (só leitura, exige login).
   A base de conhecimento fica em apps/parque/assistente.py.
   ========================================================================== */

(function () {
  "use strict";

  // O unfold injeta os SCRIPTS no <head> SEM defer: aqui o <body> ainda não
  // existe. Por isso a montagem espera o DOM (mesmo cuidado do make-admin.js).
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else {
    iniciar();
  }

  function iniciar() {
  // Fora do sistema (login, recuperar senha) o assistente não aparece.
  if (document.body.classList.contains("login")) return;
  if (document.getElementById("mkasst")) return;

  var ENDPOINT = "/ajuda/assistente/";
  var ABERTO = "mkasst--aberto";

  function svg(d, tam) {
    return '<svg viewBox="0 0 24 24" width="' + (tam || 18) + '" height="' + (tam || 18) +
      '" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
      'stroke-linejoin="round" aria-hidden="true"><path d="' + d + '"/></svg>';
  }
  var ICO = {
    balao: "M21 11.5a8.4 8.4 0 0 1-9 8.4 9 9 0 0 1-3.6-.7L3 21l1.9-5.1A8.4 8.4 0 0 1 12 3a8.4 8.4 0 0 1 9 8.5z",
    fechar: "M18 6 6 18M6 6l12 12",
    seta: "M5 12h14M13 6l6 6-6 6",
    voltar: "M19 12H5M11 18l-6-6 6-6",
    busca: "M11 3a8 8 0 1 1 0 16 8 8 0 0 1 0-16zM21 21l-4.3-4.3",
    livro: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z",
    sino: "M10.3 21a2 2 0 0 0 3.4 0M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9",
    chevron: "m6 9 6 6 6-6",
    envia: "M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z"
   };

  // Ícone por SEÇÃO do índice. Pedido do dono: "bota uns ícones ilustrativos
  // de cada categoria respectiva" — o índice era uma pilha de títulos em
  // caixa alta, todos iguais. As chaves são os nomes que a base de
  // conhecimento usa (apps/parque/assistente.py); o que não casar cai no
  // ponto de interrogação.
  var ICO_SECAO = {
    "acesso":         "M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3",
    "assistência":    "M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z",
    "avisos":         "M10.3 21a2 2 0 0 0 3.4 0M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9",
    "chamados":       "M22 11.08V12a10 10 0 1 1-5.93-9.14M9 11l3 3L22 4",
    "desempenho":     "M3 3v18h18M7 15l3-3 3 2 4-6",
    "dicas":          "M9 18h6M10 22h4M12 2a7 7 0 0 1 4 12.7V17H8v-2.3A7 7 0 0 1 12 2z",
    "estoque":        "M3 9V5a1 1 0 0 1 1-1h16a1 1 0 0 1 1 1v4M3 9h18l-1.2 10.1a1 1 0 0 1-1 .9H5.2a1 1 0 0 1-1-.9zM9 13h6",
    "notebooks":      "M3 4h18v12H3zM2 20h20",
    "orçamentos":     "M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7zM14 2v5h6M9 13h6M9 17h4",
    "parque":         "M2.5 4h19v13h-19zM8 21h8",
    "permissões":     "M12 2 4 6v6c0 5 3.5 7.5 8 10 4.5-2.5 8-5 8-10V6zM9 12l2 2 4-4",
    "preventiva":     "M3 4.5h18v17H3zM8 2v5M16 2v5M3 10h18M9 15l2 2 4-4",
    "telemetria":     "M5 12.5a10 10 0 0 1 14 0M8.5 15.5a5.5 5.5 0 0 1 7 0M12 19h.01",
    "transferências": "M4 8h16M16 4l4 4-4 4M20 16H4M8 12l-4 4 4 4",
    "_": "M12 17h.01M9.1 9a3 3 0 0 1 5.8 1c0 2-3 2.5-3 4M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18z"
  };
  function icoSecao(nome) {
    var k = String(nome || "").trim().toLowerCase();
    return svg(ICO_SECAO[k] || ICO_SECAO._, 15);
  }

  function esc(t) {
    return String(t == null ? "" : t)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  // **negrito** e *itálico* nos passos — o resto vai escapado.
  function fmt(t) {
    return esc(t)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>");
  }

  /* ------------------------------------------------------------- montagem */

  var raiz = document.createElement("div");
  raiz.id = "mkasst";
  raiz.innerHTML =
    '<button type="button" class="mkasst__abrir" aria-expanded="false"' +
    ' aria-controls="mkasst-painel" title="Ajuda do sistema (Alt+H)">' +
      svg(ICO.balao, 20) + '<span>Ajuda</span>' +
      // O contador de nao lidas das CONVERSAS mora aqui, na bolha que fica a'
      // vista o tempo todo. Se a pessoa nao tem acesso ao chat, ninguem nunca
      // acende este numero.
      '<span class="mkasst__n" hidden></span>' +
    '</button>' +
    // Minimizar: o dono reclamou que o botao fica "encima de tudo o tempo
    // todo". Fechado ele encosta na borda direita e some; passar o mouse o
    // traz de volta para clicar. O estado fica no localStorage — se ele
    // minimizou, e' para continuar minimizado nas outras telas.
    '<button type="button" class="mkasst__min" aria-label="Minimizar a ajuda"' +
    ' title="Minimizar (a ajuda volta ao encostar o mouse na borda)">' +
      svg(ICO.fechar, 12) +
    '</button>' +
    // A ALCA: fica na borda direita e NAO se move. E' ela que revela o botao
    // quando minimizado — ver o comentario do `mkasst--espia` no CSS.
    '<span class="mkasst__alca" aria-hidden="true"></span>' +
    '<section class="mkasst__painel" id="mkasst-painel" role="dialog" aria-modal="false"' +
    ' aria-label="Assistente de ajuda" hidden>' +
      '<header class="mkasst__topo">' +
        // A seta so' aparece quando alguma aba precisa de um "voltar" (a de
        // conversas usa, para sair de uma conversa e ver a lista).
        '<button type="button" class="mkasst__volta" hidden aria-label="Voltar">' +
          svg(ICO.voltar, 16) + '</button>' +
        '<div class="mkasst__marca">' + svg(ICO.balao, 16) +
          '<b class="mkasst__titulo">Assistente</b></div>' +
        '<button type="button" class="mkasst__x" aria-label="Fechar ajuda">' + svg(ICO.fechar, 16) + '</button>' +
      '</header>' +
      // A tira de abas nasce escondida: com uma aba so' ela nao tem o que
      // dizer. Aparece quando o chat se registra.
      '<nav class="mkasst__abas" role="tablist" hidden></nav>' +
      // A ajuda e' uma CONVERSA, com a mesma forma da aba de conversas: o
      // fio de baloes em cima, o campo de escrever embaixo.
      '<div class="mkasst__pane mkasst__pane--on" data-pane="ajuda">' +
        '<div class="mkasst__fio" role="log" aria-live="polite"></div>' +
        '<div class="mkasst__esc">' +
          '<textarea rows="1" class="mkasst__campo" placeholder="Pergunte o que você quer fazer…"' +
          ' aria-label="Sua dúvida" autocomplete="off" spellcheck="false"></textarea>' +
          '<button type="button" class="mkasst__enviar" disabled aria-label="Perguntar">' +
          svg(ICO.envia, 17) + '</button>' +
        '</div>' +
      '</div>' +
    '</section>';
  document.body.appendChild(raiz);

  var btnMin = raiz.querySelector(".mkasst__min");
  var CHAVE_MIN = "mkasstMinimizado";
  // COMECA MINIMIZADO — pedido do dono: "o ajuda enorme me atrapalhando, ele
  // deve comecar no sistema minimizado". Antes o padrao era aberto e ele tinha
  // de minimizar em cada tela. Agora o botao nasce encostado na borda e a alca
  // o traz quando precisa; quem guardou "0" (trouxe de volta de proposito)
  // continua com ele a vista.
  var minimizado = true;
  try {
    if (localStorage.getItem(CHAVE_MIN) === "0") minimizado = false;
  } catch (e) {}
  if (minimizado) raiz.classList.add("mkasst--min");
  if (btnMin) btnMin.addEventListener("click", function (e) {
    e.stopPropagation();
    raiz.classList.add("mkasst--min");
    raiz.classList.remove("mkasst--espia");
    try { localStorage.setItem(CHAVE_MIN, "1"); } catch (err) {}
  });

  // Espiada: entrar na alca (ou no proprio botao) traz ele de volta; sair de
  // ambos esconde depois de um respiro. O `:hover` do CSS nao serve aqui —
  // ele estava no elemento que se move, e o alvo fugindo do cursor fazia o
  // botao tremer. Aqui quem manda e' o evento, e o timer da a folga para o
  // cursor atravessar o vao entre a alca e o botao.
  var alca = raiz.querySelector(".mkasst__alca");
  var timerEspia = null;
  function espiar(on) {
    if (timerEspia) { clearTimeout(timerEspia); timerEspia = null; }
    if (on) {
      raiz.classList.add("mkasst--espia");
      return;
    }
    timerEspia = setTimeout(function () {
      raiz.classList.remove("mkasst--espia");
      timerEspia = null;
    }, 280);
  }
  if (alca) {
    alca.addEventListener("mouseenter", function () { espiar(true); });
    alca.addEventListener("mouseleave", function () { espiar(false); });

    // ---------------------------------------------------------------------
    // CLIQUE LONGO — só em aparelho sem mouse
    //
    // No telefone o gatilho minimizado é uma alça de 20px na borda, e não
    // existe "passar o mouse por cima": eu tinha deixado dois toques (um
    // revela, outro abre), o que o dono resumiu como "difícil". Aqui o toque
    // longo abre direto.
    //
    // O gesto é medido por `pointerdown`/`pointerup` e cancelado se o dedo
    // andar mais de 12px — senão a rolagem da página abriria o chat sem
    // querer. O `preventDefault` acontece só quando o gesto COMPLETA, para
    // não bloquear o toque curto nem a rolagem.
    var semMouse = window.matchMedia && window.matchMedia("(hover: none)").matches;
    var relogioLongo = null, xIni = 0, yIni = 0, abriuNoLongo = false;

    function cancelarLongo() {
      if (relogioLongo) { clearTimeout(relogioLongo); relogioLongo = null; }
      alca.classList.remove("is-pressionando");
    }

    if (semMouse) {
      alca.addEventListener("pointerdown", function (e) {
        if (e.pointerType === "mouse") return;
        abriuNoLongo = false;
        xIni = e.clientX; yIni = e.clientY;
        alca.classList.add("is-pressionando");
        relogioLongo = setTimeout(function () {
          relogioLongo = null;
          alca.classList.remove("is-pressionando");
          abriuNoLongo = true;
          espiar(true);
          if (!raiz.classList.contains(ABERTO)) abrir();
          // Vibração curta quando o aparelho permite: confirma o gesto sem
          // depender de o dedo estar tampando a tela.
          try { if (navigator.vibrate) navigator.vibrate(18); } catch (err) {}
        }, 450);
      });
      alca.addEventListener("pointermove", function (e) {
        if (!relogioLongo) return;
        if (Math.abs(e.clientX - xIni) > 12 || Math.abs(e.clientY - yIni) > 12) cancelarLongo();
      });
      alca.addEventListener("pointerup", function (e) {
        cancelarLongo();
        if (abriuNoLongo) { e.preventDefault(); abriuNoLongo = false; }
      });
      alca.addEventListener("pointercancel", cancelarLongo);
      alca.addEventListener("pointerleave", cancelarLongo);
    }

    // Toque curto (e clique de mouse) continua revelando o botão.
    alca.addEventListener("click", function () {
      if (abriuNoLongo) { abriuNoLongo = false; return; }
      espiar(true);
    });
  }
  raiz.addEventListener("mouseenter", function () {
    if (raiz.classList.contains("mkasst--min")) espiar(true);
  });
  raiz.addEventListener("mouseleave", function () {
    if (raiz.classList.contains("mkasst--min")) espiar(false);
  });
  // Chegar por teclado tambem revela — Tab no botao nao pode cair no vazio.
  raiz.addEventListener("focusin", function () {
    if (raiz.classList.contains("mkasst--min")) espiar(true);
  });

  var btnAbrir = raiz.querySelector(".mkasst__abrir");
  var painel = raiz.querySelector(".mkasst__painel");
  var campo = raiz.querySelector(".mkasst__campo");
  var corpo = raiz.querySelector(".mkasst__fio");     // o fio da conversa
  var btnEnviar = raiz.querySelector(".mkasst__enviar");

  /* Os avisos NÃO moram mais aqui. O dono pediu uma área de notificação no
     topo do sistema, com calendário — quem adota o bloco `_avisos.html` agora
     é o `initAgendaTopo()` do make-admin.js. Aqui ficou só a ajuda. */

  /* --------------------------------------------------------- apresentação */

  /* Um balão no fio. `meu` = escrito pela pessoa (vai para a direita, verde);
     senão é a resposta da ajuda (esquerda). As classes sao as MESMAS da aba
     de conversas — e' assim que as duas abas nao divergem de estilo. */
  function dizer(html, meu) {
    var d = document.createElement("div");
    d.className = "mkchat__m" + (meu ? " mkchat__m--meu" : "");
    d.innerHTML = '<div class="mkchat__bolha">' + html + "</div>";
    corpo.appendChild(d);
    corpo.scrollTop = corpo.scrollHeight;
    return d;
  }

  /* A resposta chega uma de cada vez: a anterior fica no fio, como numa
     conversa de verdade. So' o "pensando…" e' descartavel. */
  var pensando = null;
  function pensar(sim) {
    if (pensando) { pensando.remove(); pensando = null; }
    if (sim) pensando = dizer('<span class="mkasst__pensando">pensando…</span>', false);
  }

  function pintarSugestoes(lista) {
    if (!lista || !lista.length) return;
    dizer('<p class="mkasst__dica">Comece por uma destas — ou escreva a sua dúvida:</p>' +
      '<ul class="mkasst__sug">' +
      lista.map(function (s) {
        return '<li><button type="button" data-pergunta="' + esc(s.titulo) + '">' +
          esc(s.titulo) + svg(ICO.seta, 14) + '</button></li>';
      }).join("") + '</ul>', false);
  }

  function pintarTopicos(dados) {
    var t = dados.topicos || [];
    if (!t.length) {
      dizer('<p><b>Não encontrei isso na ajuda.</b></p>' +
        '<p>Tente com outras palavras — ou fale com a TI, que registra a dúvida ' +
        'e ela vira um tópico aqui.</p>', false);
      pintarSugestoes(dados.sugestoes);
      return;
    }
    var principal = t[0];
    var outros = t.slice(1);
    dizer(
      '<article class="mkasst__resp">' +
        '<p class="mkasst__secao">' + esc(principal.secao) + '</p>' +
        '<h3>' + esc(principal.titulo) + '</h3>' +
        '<ol class="mkasst__passos">' +
          // O <span> NAO e' decoracao: o <li> do passo e' `display: grid`
          // (rotulo redondo | texto). Em um container grid, CADA pedaco do
          // conteudo em linha vira um item proprio — "Abra o", <b>mapa</b>,
          // "da loja de origem." foram para celulas diferentes, e o que caiu
          // na coluna de 24px do numero saiu uma palavra por linha. Foi o que
          // o dono viu ("formatacao de texto toda errada"). Embrulhado, o
          // texto e' UM item e ocupa a coluna certa.
          (principal.passos || []).map(function (p) {
            return '<li><span class="mkasst__passo-txt">' + fmt(p) + "</span></li>";
          }).join("") +
        '</ol>' +
        (principal.url
          ? '<a class="mkasst__ir" href="' + esc(principal.url) + '">Ir para a tela' + svg(ICO.seta, 14) + '</a>'
          : "") +
        // A Central de Ajuda morreu: nao ha mais pagina para onde mandar.
        // A resposta do assistente E' a ajuda agora.
        (false
          ? ''
          : "") +
      '</article>' +
      (outros.length
        ? '<p class="mkasst__dica">Talvez seja isto:</p><ul class="mkasst__sug">' +
          outros.map(function (o) {
            return '<li><button type="button" data-pergunta="' + esc(o.titulo) + '">' +
              esc(o.titulo) + svg(ICO.seta, 14) + '</button></li>';
          }).join("") + "</ul>"
        : ""), false);
  }

  function pintarIndice(secoes) {
    dizer('<p class="mkasst__dica">Todos os assuntos</p>' +
      (secoes || []).map(function (s) {
        // `mkasst__sec` no lugar do <h4> solto: o título da seção fica
        // grudado no alto enquanto a lista rola, então o índice deixa de ser
        // um paredão de texto no meio da conversa.
        return '<div class="mkasst__grupo"><p class="mkasst__sec">' +
          '<span class="mkasst__sec-ic">' + icoSecao(s.secao) + '</span>' +
          esc(s.secao) + '</p><ul class="mkasst__sug">' +
          s.itens.map(function (i) {
            return '<li><button type="button" data-pergunta="' + esc(i.titulo) + '">' +
              esc(i.titulo) + svg(ICO.seta, 14) + '</button></li>';
          }).join("") + '</ul></div>';
      }).join(""), false);
  }

  /* -------------------------------------------------------------- consulta */

  var emVoo = null;
  function perguntar(texto) {
    if (emVoo) { emVoo.abort(); }
    var ctrl = new AbortController();
    emVoo = ctrl;
    pensar(true);
    fetch(ENDPOINT + "?q=" + encodeURIComponent(texto || ""), {
      signal: ctrl.signal,
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin"
    })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (d) {
        pensar(false);
        if (!texto) { pintarSugestoes(d.sugestoes); } else { pintarTopicos(d); }
      })
      .catch(function (e) {
        if (e && e.name === "AbortError") return;
        pensar(false);
        dizer('<p><b>Não consegui buscar agora.</b></p>' +
          '<p>Tente de novo daqui a pouco.</p>', false);
      });
    emVoo = null;
  }

  /* ------------------------------------------------------------- interação */

  var temporizador = null;
  function abrir() {
    painel.hidden = false;
    raiz.classList.add(ABERTO);
    btnAbrir.setAttribute("aria-expanded", "true");
    // Foco na busca da ajuda so' quando a ajuda e' a aba aberta — senao o
    // cursor pularia para ca' no meio de uma conversa.
    if (abaAtiva === "ajuda") campo.focus();
    else if (abas[abaAtiva] && abas[abaAtiva].aoEntrar) abas[abaAtiva].aoEntrar();
    // NADA de lista antes de digitar (pedido do dono: "corrija o chat pros
    // textos aparecerem só quando eu digitar"). Antes o painel abria já com
    // seis sugestões e o índice inteiro atrás de um clique — parede de texto
    // sem ninguém ter perguntado nada.
    // O fio comeca com uma fala da ajuda — e nao com uma parede de texto:
    // ate' hoje o painel abria despejando seis sugestoes e o indice inteiro
    // sem ninguem ter perguntado nada.
    if (!corpo.children.length) {
      dizer('Oi! Pergunte o que você quer fazer no sistema.<br>' +
        '<span class="mkasst__ex">Ex.: abrir chamado, transferir máquina, ' +
        'imprimir etiqueta.</span>' +
        '<button type="button" class="mkasst__indice">' + svg(ICO.livro, 14) +
        ' Ver todos os assuntos</button>', false);
    }
  }
  function fechar() {
    painel.hidden = true;
    raiz.classList.remove(ABERTO);
    btnAbrir.setAttribute("aria-expanded", "false");
    btnAbrir.focus();
  }

  /* ----------------------------------------------------------------- abas
     O painel deixou de ser so' da ajuda. Quem quiser morar aqui dentro se
     registra por `window.MkAsst.addAba()` — hoje e' o chat do time
     (make-chat.js), e so' para quem tem acesso a ele. */

  var tira = raiz.querySelector(".mkasst__abas");
  var elTitulo = raiz.querySelector(".mkasst__titulo");
  var btnVolta = raiz.querySelector(".mkasst__volta");
  var contador = raiz.querySelector(".mkasst__n");
  var abas = {
    ajuda: {
      rotulo: "Ajuda",
      pane: raiz.querySelector('[data-pane="ajuda"]'),
      aoEntrar: function () { campo.focus(); }
    }
  };
  var abaAtiva = "ajuda";
  var voltarDaVez = null;

  function pintarAbas() {
    var ids = Object.keys(abas);
    // Uma aba sozinha nao e' uma escolha. E dentro de uma conversa a tira sai
    // da frente (`voltarDaVez`): trocar de aba ali seria perder o lugar.
    // Esta funcao e' chamada tambem pelo contador, entao ela TEM de respeitar
    // o estado do titulo — senao reacende a tira que o titulo acabou de
    // apagar, que foi exatamente o que aconteceu.
    tira.hidden = ids.length < 2 || !!voltarDaVez;
    if (tira.hidden) return;
    tira.innerHTML = ids.map(function (id) {
      var a = abas[id];
      return '<button type="button" role="tab" class="mkasst__aba' +
        (id === abaAtiva ? " mkasst__aba--on" : "") + '" data-aba="' + id +
        '" aria-selected="' + (id === abaAtiva) + '">' + a.rotulo +
        (a.n ? '<span class="mkasst__aban">' + (a.n > 99 ? "99+" : a.n) +
               "</span>" : "") + "</button>";
    }).join("");
  }

  function irPara(id) {
    if (!abas[id]) return;
    abaAtiva = id;
    Object.keys(abas).forEach(function (k) {
      abas[k].pane.classList.toggle("mkasst__pane--on", k === id);
    });
    titulo(abas[id].rotulo === "Ajuda" ? "Assistente" : abas[id].rotulo, null);
    pintarAbas();
    if (abas[id].aoEntrar) abas[id].aoEntrar();
  }

  function titulo(texto, aoVoltar) {
    elTitulo.textContent = texto;
    voltarDaVez = aoVoltar || null;
    btnVolta.hidden = !voltarDaVez;
    pintarAbas();   // a regra de esconder a tira mora la', num lugar so'.
  }

  tira.addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-aba]");
    if (b) irPara(b.getAttribute("data-aba"));
  });
  btnVolta.addEventListener("click", function () {
    if (voltarDaVez) voltarDaVez();
  });

  window.MkAsst = {
    /* cfg: {id, rotulo, pane, aoEntrar} */
    addAba: function (cfg) {
      abas[cfg.id] = { rotulo: cfg.rotulo, pane: cfg.pane,
                       aoEntrar: cfg.aoEntrar, n: 0 };
      painel.appendChild(cfg.pane);
      cfg.pane.classList.add("mkasst__pane");
      pintarAbas();
    },
    irPara: irPara,
    titulo: titulo,
    /* o numero na aba e o numero na bolha sao a mesma noticia */
    contador: function (id, n) {
      if (abas[id]) abas[id].n = n || 0;
      var total = 0;
      Object.keys(abas).forEach(function (k) { total += (abas[k].n || 0); });
      contador.textContent = total > 99 ? "99+" : String(total);
      contador.hidden = !total;
      pintarAbas();
    },
    abrir: abrir,
    fechar: fechar,
    estaAberto: function () { return raiz.classList.contains(ABERTO); }
  };

  btnAbrir.addEventListener("click", function () {
    if (raiz.classList.contains(ABERTO)) { fechar(); } else { abrir(); }
  });
  raiz.querySelector(".mkasst__x").addEventListener("click", fechar);

  /* Mandar a pergunta: ela entra no fio como fala da pessoa, e a resposta
     vem em seguida. NAO busca mais enquanto se digita — o fio viraria uma
     pilha de respostas pela metade, uma por letra. */
  function mandarPergunta() {
    var v = campo.value.trim();
    if (!v) return;
    dizer(esc(v), true);
    campo.value = "";
    campo.style.height = "auto";
    btnEnviar.disabled = true;
    perguntar(v);
  }

  campo.addEventListener("input", function () {
    btnEnviar.disabled = !campo.value.trim();
    campo.style.height = "auto";
    campo.style.height = Math.min(110, campo.scrollHeight) + "px";
  });
  campo.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); mandarPergunta(); }
  });
  btnEnviar.addEventListener("click", mandarPergunta);

  /* Um clique so' para tudo que nasce dentro do fio: os atalhos de pergunta
     e o "ver todos os assuntos" (que agora vive dentro da saudacao, e por
     isso nao da' para prender o ouvinte nele na montagem). */
  corpo.addEventListener("click", function (e) {
    var b = e.target.closest("button[data-pergunta]");
    if (b) {
      var q = b.getAttribute("data-pergunta");
      dizer(esc(q), true);
      perguntar(q);
      campo.focus();
      return;
    }
    if (e.target.closest(".mkasst__indice")) {
      pensar(true);
      fetch(ENDPOINT + "?todos=1", { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (d) { pensar(false); pintarIndice(d.indice); })
        .catch(function () { pensar(false); });
    }
  });

  // O "?" da barra superior abria a Central de Ajuda. Como o menu Ajuda saiu do
  // sistema, ele passa a abrir o assistente — a porta única da ajuda.
  var ajudaTopo = document.getElementById("page-help-btn");
  if (ajudaTopo) {
    ajudaTopo.setAttribute("title", "Ajuda do sistema (Alt+H)");
    ajudaTopo.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopImmediatePropagation();
      abrir();
    }, true);
  }

  document.addEventListener("keydown", function (e) {
    if (e.altKey && (e.key === "h" || e.key === "H")) { e.preventDefault(); abrir(); }
    if (e.key === "Escape" && raiz.classList.contains(ABERTO)) fechar();
  });
  }
})();
