/* =============================================================================
   make-chat.js — o CHAT do time, em toda tela do sistema.

   NÃO tem bolha própria: é uma ABA dentro do painel do assistente, ao lado
   de "Ajuda". Teve bolha por um tempo, e o canto ficou com três coisas
   empilhadas (assistente, chat, "ao topo"). O dono olhou e disse: "ficou
   feio, mais fácil fazer um chatzão supremo com os dois". Um painel, duas
   abas — o canto volta a ter um dono só.

   Conversa continua sendo interrupção: "a movimentação da baia 12 pode?"
   acontece ENQUANTO a pessoa faz outra coisa. Por isso o painel é flutuante
   e está em toda tela — o que mudou foi a porta de entrada, não o lugar.

   ACESSO
   Pergunta ao servidor se pode existir (`/parque/mural/conversas/`). Quem não
   abre o Mural recebe `pode: false` e a ABA NÃO É CRIADA — o painel fica só
   com a ajuda, como era antes. A porta é a mesma da tela: o chat não inventa
   acesso.

   O servidor é quem decide tudo o mais: só as duas pessoas leem uma conversa,
   e não há parâmetro nesta página que mude isso.
   ========================================================================== */
(function () {
  "use strict";

  var URL_LISTA = "/parque/mural/conversas/";
  var URL_CONVERSA = "/parque/mural/conversa/";
  var URL_MANDAR = "/parque/mural/mandar/";

  var ICO = {
    balao: "M21 12a8 8 0 0 1-8 8H8l-5 3 1.4-4.2A8 8 0 1 1 21 12z",
    fechar: "M6 6l12 12M18 6L6 18",
    volta: "M15 18l-6-6 6-6",
    busca: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-3.5-3.5",
    envia: "M4 20l17-8L4 4l3 8z",
    seta: "M5 12h13l-4-4M18 12l-4 4"
  };

  function svg(d, t) {
    return '<svg viewBox="0 0 24 24" width="' + (t || 20) + '" height="' + (t || 20) +
      '" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" ' +
      'stroke-linejoin="round" aria-hidden="true"><path d="' + d + '"/></svg>';
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function iniciais(nome) {
    var p = String(nome || "").split(" ").filter(Boolean);
    if (!p.length) return "?";
    return (p[0][0] + (p.length > 1 ? p[p.length - 1][0] : "")).toUpperCase();
  }

  function csrf() {
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    if (m) return m[1];
    var i = document.querySelector("[name=csrfmiddlewaretoken]");
    return i ? i.value : "";
  }

  function pedir(url, campos, entao, falhou) {
    var fd = new FormData();
    fd.append("csrfmiddlewaretoken", csrf());
    Object.keys(campos || {}).forEach(function (k) { fd.append(k, campos[k]); });
    fetch(url, { method: "POST", body: fd, credentials: "same-origin" })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (d) {
        if (d && d.ok) { entao(d); } else if (falhou) { falhou(d || {}); }
      })
      .catch(function () { if (falhou) falhou({}); });
  }

  // ------------------------------------------------------------- o estado
  var est = { conversas: [], naoLidas: 0, com: null, mensagens: [], busca: "" };
  var raiz, lista, msgs, campoBusca, campoMsg;

  /* Monta a ABA, nao um widget. O canto ja' tem dono: o assistente. Duas
     bolhas no mesmo canto era o que estava feio — agora e' um painel so',
     com "Ajuda" e "Conversas" lado a lado. */
  function monta() {
    raiz = document.createElement("div");
    raiz.id = "mkchat";
    raiz.innerHTML =
      '<div class="mkchat__busca">' + svg(ICO.busca, 16) +
      '<input type="search" placeholder="Buscar pessoa…" autocomplete="off"></div>' +
      '<div class="mkchat__lista"></div>' +
      '<div class="mkchat__msgs"></div>' +
      '<div class="mkchat__esc"><textarea rows="1" ' +
      'placeholder="Escreva uma mensagem…"></textarea>' +
      '<button type="button" class="mkchat__enviar" disabled>' +
      svg(ICO.envia, 17) + "</button></div>";

    window.MkAsst.addAba({
      id: "conversas",
      rotulo: "Conversas",
      pane: raiz,
      aoEntrar: function () {
        carregarLista();
        setTimeout(function () { campoBusca.focus(); }, 60);
      }
    });

    lista = raiz.querySelector(".mkchat__lista");
    msgs = raiz.querySelector(".mkchat__msgs");
    campoBusca = raiz.querySelector(".mkchat__busca input");
    campoMsg = raiz.querySelector(".mkchat__esc textarea");

    campoBusca.addEventListener("input", function () {
      est.busca = campoBusca.value;
      pintarLista();
    });
    campoMsg.addEventListener("input", function () {
      campoMsg.style.height = "auto";
      campoMsg.style.height = Math.min(110, campoMsg.scrollHeight) + "px";
      raiz.querySelector(".mkchat__enviar").disabled = !campoMsg.value.trim();
    });
    campoMsg.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); mandar(); }
    });
    raiz.querySelector(".mkchat__enviar").addEventListener("click", mandar);
    // O Escape e' do painel, e quem cuida dele e' o assistente. Dois
    // ouvintes para a mesma tecla so' dariam briga.
  }

  /* Sair de uma conversa e voltar para a lista de pessoas. A seta que dispara
     isto fica no topo do painel do assistente — ver MkAsst.titulo(). */
  function voltarParaLista() {
    est.com = null;
    raiz.classList.remove("mkchat--conversa");
    window.MkAsst.titulo("Conversas", null);
    pintarLista();
  }

  function pintarContador() {
    window.MkAsst.contador("conversas", est.naoLidas);
  }

  function carregarLista() {
    pedir(URL_LISTA, {}, function (d) {
      if (!d.pode) return;
      est.conversas = d.conversas || [];
      est.naoLidas = d.nao_lidas || 0;
      pintarContador();
      if (!est.com) pintarLista();
    });
  }

  function pintarLista() {
    var q = est.busca.trim().toLowerCase();
    var quais = est.conversas.filter(function (c) {
      return !q || c.nome.toLowerCase().indexOf(q) >= 0;
    });
    if (!quais.length) {
      lista.innerHTML = '<p class="mkchat__vazio">Ninguém com esse nome.</p>';
      return;
    }
    lista.innerHTML = quais.map(function (c) {
      return '<button type="button" class="mkchat__p" data-com="' + c.id + '">' +
        '<span class="mkchat__av">' + esc(iniciais(c.nome)) +
        (c.faixa === "agora" ? '<span class="mkchat__on"></span>' : "") + "</span>" +
        '<span class="mkchat__t"><span class="mkchat__nome">' + esc(c.nome) +
        "</span>" +
        '<span class="mkchat__u">' + (c.ultima
          ? (c.ultima_minha ? "você: " : "") + esc(c.ultima)
          : "conversar") + "</span></span>" +
        (c.nao_lidas ? '<span class="mkchat__b">' + c.nao_lidas + "</span>"
                     : '<span class="mkchat__q">' + esc(c.quando || "") + "</span>") +
        "</button>";
    }).join("");
    Array.prototype.forEach.call(lista.querySelectorAll("[data-com]"), function (b) {
      b.addEventListener("click", function () {
        abrirConversa(+b.getAttribute("data-com"));
      });
    });
  }

  function abrirConversa(id) {
    var c = est.conversas.filter(function (x) { return x.id === id; })[0];
    est.com = id;
    raiz.classList.add("mkchat--conversa");
    // O topo e' do painel do assistente: e' la' que entra o nome de quem eu
    // estou falando, e a seta de voltar para a lista.
    window.MkAsst.titulo(c ? c.nome : "Conversa", voltarParaLista);
    msgs.innerHTML = '<p class="mkchat__vazio">carregando…</p>';
    pedir(URL_CONVERSA, { com: id }, function (d) {
      est.mensagens = d.mensagens || [];
      est.naoLidas = d.nao_lidas || 0;
      if (c) c.nao_lidas = 0;
      pintarContador();
      pintarMensagens();
      setTimeout(function () { campoMsg.focus(); }, 60);
    }, function () {
      msgs.innerHTML = '<p class="mkchat__vazio">Não deu para abrir a conversa.</p>';
    });
  }

  function pintarMensagens() {
    if (!est.mensagens.length) {
      msgs.innerHTML = '<p class="mkchat__vazio">Nenhuma mensagem ainda.<br>' +
        "Diga o primeiro.</p>";
      return;
    }
    msgs.innerHTML = est.mensagens.map(function (m) {
      var h = '<div class="mkchat__m' + (m.meu ? " mkchat__m--meu" : "") + '">' +
        '<div class="mkchat__bolha">' + esc(m.texto || "");
      if (m.alvo_titulo) {
        h += '<span class="mkchat__cita">' + svg(ICO.seta, 12) +
          esc(m.alvo_titulo) + "</span>";
      }
      if (m.arquivo) {
        h += m.e_imagem
          ? '<img src="' + esc(m.arquivo) + '" alt="' + esc(m.arquivo_nome) + '">'
          : '<span class="mkchat__cita"><a href="' + esc(m.arquivo) +
            '" target="_blank" rel="noopener" style="color:inherit">' +
            esc(m.arquivo_nome) + "</a></span>";
      }
      return h + "</div>" + '<span class="mkchat__h">' + esc(m.quando) +
        (m.meu && m.lida ? " · lida" : "") + "</span></div>";
    }).join("");
    msgs.scrollTop = msgs.scrollHeight;
  }

  function mandar() {
    var txt = campoMsg.value.trim();
    if (!txt || !est.com) return;
    var bt = raiz.querySelector(".mkchat__enviar");
    bt.disabled = true;
    pedir(URL_MANDAR, { com: est.com, texto: txt }, function (d) {
      est.mensagens.push(d.mensagem);
      campoMsg.value = "";
      campoMsg.style.height = "auto";
      pintarMensagens();
      var c = est.conversas.filter(function (x) { return x.id === est.com; })[0];
      if (c) {
        c.ultima = d.mensagem.texto;
        c.ultima_minha = true;
        c.quando = d.mensagem.quando;
      }
    }, function (d) {
      bt.disabled = false;
      if (d && d.erro) window.alert(d.erro);
    });
  }

  // ------------------------------------------------------------- partida
  // Pergunta primeiro: se esta pessoa não abre o Mural, a bolha nem nasce.
  var esperas = 0;

  function comecar() {
    var fd = new FormData();
    fd.append("csrfmiddlewaretoken", csrf());
    fetch(URL_LISTA, { method: "POST", body: fd, credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.ok || !d.pode) return;
        if (document.getElementById("mkchat")) return;
        // A aba mora dentro do assistente. Ele carrega antes (a ordem esta'
        // em UNFOLD["SCRIPTS"]), mas nao custa esperar: se um dia a ordem
        // mudar, o chat some em silencio em vez de estourar.
        if (!window.MkAsst) {
          if (esperas++ < 40) { setTimeout(comecar, 100); }
          return;
        }
        monta();
        est.conversas = d.conversas || [];
        est.naoLidas = d.nao_lidas || 0;
        pintarContador();
        pintarLista();
      })
      .catch(function () { /* sem chat, e sem barulho no console */ });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", comecar);
  } else {
    comecar();
  }
})();
