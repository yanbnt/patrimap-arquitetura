/* =========================================================================
   ITAM Make — ações da lista como BOTÕES FLUTUANTES (canto inferior):
     • Alterar (verde)  → abre o formulário de edição na MESMA tela
     • Excluir (vermelho) → tela de confirmação do Django ("confirma X?")
   Os botões só aparecem quando há linha(s) selecionada(s).
   Também adiciona o botão "mostrar/ocultar senha" nos campos de senha.
   ========================================================================= */
// Tema padrão na 1ª visita = ESCURO (a vitrine é o dark). Roda ANTES do Alpine
// (nossos scripts não têm defer). Mantém o toggle e respeita a escolha salva:
// só age quando o usuário ainda não escolheu tema (localStorage vazio).
try {
  if (localStorage.getItem("adminTheme") === null) {
    localStorage.setItem("adminTheme", JSON.stringify("dark"));  // Alpine $persist lê JSON
    document.documentElement.classList.add("dark");              // aplica já (sem flash)
  }
} catch (e) { /* localStorage indisponível — ignora */ }

/* ---------------------------------------------------------------------------
   Ícones de linha para o HTML que este arquivo injeta (barra flutuante, toasts,
   modais). Regra do DESIGN-PRO.md §3: SVG de linha, nunca emoji na interface.
   Uso:  botao.innerHTML = mkIco("wrench") + " Abrir chamado";
   --------------------------------------------------------------------------- */
var MK_ICO = {
  wrench: 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z',
  recycle: 'M7 19H4.8a2 2 0 0 1-1.7-3l2.6-4.3M9.3 4.9 8 7M12 3l3.7 6.3M16.6 6.5 19.9 12a2 2 0 0 1-1.7 3H16M13 21l-3.7-6.3M8.2 15H5.6',
  tag: 'M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8zM7.5 7.5h.01',
  send: 'M5 12h14M13 6l6 6-6 6',
  truck: 'M10 17h4V5H2v12h3M20 17h2v-3.34a4 4 0 0 0-1.17-2.83L19 9h-5v8h3',
  box: 'M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16zM3.3 7l8.7 5 8.7-5M12 22V12',
  pencil: 'M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z',
  trash: 'M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6',
  check: 'M20 6 9 17l-5-5',
  doc: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M9 15h6',
  monitor: 'M2 3h20v14H2zM8 21h8M12 17v4',
  laptop: 'M4 5h16v11H4zM2 20h20',
  user: 'M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2M12 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8z',
  pin: 'M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0zM12 7a3 3 0 1 1 0 6 3 3 0 0 1 0-6z',
  swap: 'M7 4 3 8l4 4M3 8h13a4 4 0 0 1 0 8h-1M17 20l4-4-4-4',
  close: 'M18 6 6 18M6 6l12 12',
  alert: 'M12 2 1.7 20h20.6zM12 9v4M12 17h.01',
  block: 'M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20zM5 5l14 14',
  stethoscope: 'M4 3v6a5 5 0 0 0 10 0V3M9 14v2a5 5 0 0 0 10 0v-1M19 10a2 2 0 1 1 0 4 2 2 0 0 1 0-4z',
  dot: 'M12 7a5 5 0 1 1 0 10 5 5 0 0 1 0-10z'
};
function mkIco(nome) {
  var d = MK_ICO[nome] || MK_ICO.dot;
  return '<svg class="mk-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor"' +
         ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round"' +
         ' aria-hidden="true"><path d="' + d + '"/></svg>';
}

(function () {
  "use strict";


  // ------------------------------------------------------------------------
  // AVISO ÚNICO — todo retorno de ação vai para o painel do topo
  //
  // Regra do dono, dita mais de uma vez: "garanta que TODAS as notificações de
  // ações de usuários vão aparecer na parte superior que criamos". As mensagens
  // do Django já iam (o parcial `messages.html` as entrega escondidas e o
  // `initAgendaTopo()` as adota). Faltava o que este arquivo fazia por conta:
  // toast no canto do mapa, na tabela e na transferência — quatro fábricas de
  // aviso diferentes, todas desenhando DENTRO da página.
  //
  // Aqui é o caminho único: cartão na coluna de avisos, ponto aceso no objeto
  // do topo e painel aberto — retorno de ação que não se vê é pior do que não
  // ter retorno.
  //
  // Sem painel na tela (documento de impressão, tela de login) cai no alerta
  // do navegador: feio, mas nunca engole a resposta de um envio.
  function mkAvisar(texto, nivel) {
    texto = String(texto == null ? "" : texto).trim();
    if (!texto) return;
    var col = document.getElementById("mk-agenda-avisos");
    var raiz = document.getElementById("mk-agenda");
    if (!col || !raiz) { window.alert(texto); return; }

    var cartao = document.createElement("div");
    cartao.className = "mkag__msg mkag__msg--" + (nivel || "info");
    cartao.textContent = texto;
    col.insertBefore(cartao, col.firstChild);

    var ponto = document.getElementById("mk-agenda-n");
    if (ponto) ponto.hidden = false;
    raiz.classList.add("mkag--tem");

    var pop = document.getElementById("mk-agenda-pop");
    var btn = document.getElementById("mk-agenda-btn");
    if (pop && pop.hidden) {
      pop.hidden = false;
      raiz.classList.add("mkag--aberto");
      if (btn) btn.setAttribute("aria-expanded", "true");
    }
  }
  window.mkAvisar = mkAvisar;

  // ---------- Mostrar/ocultar senha (ícone Material Symbols) ----------
  // Glifo Material: visibility_off (oculta, padrão) ⇄ visibility (mostrando).
  var EYE_ICON =
    '<span class="material-symbols-outlined" aria-hidden="true">visibility_off</span>';

  function initPasswordToggles() {
    var inputs = document.querySelectorAll('input[type="password"]');
    Array.prototype.forEach.call(inputs, function (inp) {
      if (inp.dataset.makeEye) return;
      inp.dataset.makeEye = "1";
      var wrap = document.createElement("span");
      wrap.className = "make-pass-wrap";
      inp.parentNode.insertBefore(wrap, inp);
      wrap.appendChild(inp);
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "make-pass-eye";  // sem "is-open" => olho fechado (senha oculta)
      btn.setAttribute("aria-label", "Mostrar senha");
      btn.innerHTML = EYE_ICON;
      wrap.appendChild(btn);
      btn.addEventListener("click", function () {
        var mostrando = inp.type === "text";
        inp.type = mostrando ? "password" : "text";
        btn.classList.toggle("is-open", !mostrando);
        var ic = btn.querySelector(".material-symbols-outlined");
        if (ic) ic.textContent = mostrando ? "visibility_off" : "visibility";
        btn.setAttribute("aria-label", mostrando ? "Mostrar senha" : "Ocultar senha");
      });
    });
  }

  // ---------- Botões flutuantes ----------
  function initFab() {
    var form = document.getElementById("changelist-form");
    if (!form) return;

    function selecionados() {
      return form.querySelectorAll('input[name="_selected_action"]:checked');
    }

    // Só no changelist de Baias mostramos as ações de máquina crítica.
    var ehBaia = /\/parque\/baia\//.test(window.location.pathname);
    // No Estoque de Computadores oferecemos a geração de etiqueta.
    var ehComputador = /\/parque\/computador\//.test(window.location.pathname);
    // No estoque de Peças: transferir (1) e montar caixa (vários).
    var ehPeca = /\/parque\/peca\//.test(window.location.pathname);

    var bar = document.createElement("div");
    bar.className = "make-fab-bar";
    bar.innerHTML =
      '<span class="make-fab-count"></span>' +
      '<a class="make-fab make-fab--reparo" hidden>'+mkIco('wrench')+' Abrir chamado</a>' +
      '<a class="make-fab make-fab--troca" hidden>'+mkIco('recycle')+' Desativar p/ troca</a>' +
      '<a class="make-fab make-fab--reativar" hidden>'+mkIco('recycle')+' Reativar</a>' +
      '<button type="button" class="make-fab make-fab--etiqueta" hidden>'+mkIco('tag')+' Etiqueta(s)</button>' +
      '<a class="make-fab make-fab--transferir" hidden>'+mkIco('send')+' Transferir</a>' +
      '<a class="make-fab make-fab--caixa" hidden>'+mkIco('box')+' Montar caixa</a>' +
      '<button type="button" class="make-fab make-fab--alterar">'+mkIco('pencil')+' Alterar</button>' +
      '<button type="button" class="make-fab make-fab--excluir">'+mkIco('trash')+' Excluir</button>';
    document.body.appendChild(bar);

    var btnAlt = bar.querySelector(".make-fab--alterar");
    var btnExc = bar.querySelector(".make-fab--excluir");
    var btnReparo = bar.querySelector(".make-fab--reparo");
    var btnTroca = bar.querySelector(".make-fab--troca");
    var btnEtiqueta = bar.querySelector(".make-fab--etiqueta");
    var btnReativar = bar.querySelector(".make-fab--reativar");
    var btnTransferir = bar.querySelector(".make-fab--transferir");
    var btnCaixa = bar.querySelector(".make-fab--caixa");
    var contador = bar.querySelector(".make-fab-count");

    // URL do form de Reparo derivada do caminho atual (respeita o mount do admin).
    var reparoAdd = window.location.pathname.replace(/baia\/?$/, "reparo/add/");

    function atualizarChamado(sel) {
      // Chamado de reparo / desativação: para QUALQUER baia (lista de Baias) ou
      // para um Computador EM USO (Estoque). Aparece com 1 item selecionado.
      var mostrar = false;
      if (sel.length === 1) {
        var pk = encodeURIComponent(sel[0].value);
        var row = sel[0].closest("tr");
        if (ehBaia) {
          mostrar = true;
          btnReparo.href = reparoAdd + "?baia=" + pk + "&tipo=reparo&titulo=Chamado+de+reparo";
          btnTroca.href = reparoAdd + "?baia=" + pk + "&tipo=desativacao&titulo=Desativacao+para+troca";
        } else if (ehComputador && row && row.textContent.indexOf("Em uso") !== -1) {
          mostrar = true;
          btnReparo.href = "/parque/chamado-computador/" + pk + "/reparo/";
          btnTroca.href = "/parque/chamado-computador/" + pk + "/desativacao/";
        }
      }
      btnReparo.hidden = !mostrar;
      btnTroca.hidden = !mostrar;
    }

    function atualizar() {
      var sel = selecionados();
      if (sel.length === 0) {
        bar.classList.remove("is-open");
        return;
      }
      bar.classList.add("is-open");
      contador.textContent =
        sel.length + (sel.length > 1 ? " selecionados" : " selecionado");
      btnAlt.disabled = sel.length !== 1;
      btnAlt.title =
        sel.length !== 1 ? "Selecione exatamente 1 para alterar" : "Alterar";
      btnEtiqueta.hidden = !((ehComputador || ehBaia) && sel.length >= 1);
      // Reativar: 1 computador DESATIVADO selecionado no estoque.
      var reativar = false;
      if (ehComputador && sel.length === 1) {
        var rowc = sel[0].closest("tr");
        if (rowc && rowc.textContent.indexOf("Desativado") !== -1) {
          reativar = true;
          btnReativar.href = "/parque/reativar/" + encodeURIComponent(sel[0].value) + "/";
        }
      }
      btnReativar.hidden = !reativar;
      // Peças: Transferir (exatamente 1) e Montar caixa (1+).
      if (ehPeca) {
        var ids = Array.prototype.map.call(sel, function (c) { return c.value; });
        btnTransferir.hidden = sel.length !== 1;
        if (sel.length === 1) btnTransferir.href = "/parque/peca/" + encodeURIComponent(sel[0].value) + "/transferir/";
        // Caixa só faz sentido com 2+ itens.
        btnCaixa.hidden = sel.length < 2;
        btnCaixa.href = "/parque/montar-caixa/?ids=" + ids.join(",");
      }
      atualizarChamado(sel);
    }

    form.addEventListener("change", atualizar);
    form.addEventListener("click", function (e) {
      if (e.target && (e.target.name === "_selected_action" || e.target.id === "action-toggle")) {
        setTimeout(atualizar, 0);
      }
    });

    // Alterar: navega para o formulário de edição na MESMA tela.
    btnAlt.addEventListener("click", function () {
      var sel = selecionados();
      if (sel.length !== 1) return;
      var base = window.location.pathname.replace(/\/+$/, "");
      window.location.href = base + "/" + sel[0].value + "/change/";
    });

    // Excluir: envia para a confirmação do Django.
    btnExc.addEventListener("click", function () {
      var sel = selecionados();
      if (sel.length === 0) return;
      var actionEl = form.querySelector('[name="action"]');
      if (!actionEl) return;
      actionEl.value = "delete_selected";
      var idx = form.querySelector('input[name="index"]');
      if (!idx) {
        idx = document.createElement("input");
        idx.type = "hidden";
        idx.name = "index";
        idx.value = "0";
        form.appendChild(idx);
      }
      if (typeof form.requestSubmit === "function") form.requestSubmit();
      else form.submit();
    });

    // Etiqueta(s): abre a página de impressão das etiquetas dos selecionados.
    // Na lista de Computadores manda os ids; na de Baias manda as baias (a view
    // resolve o computador vinculado de cada uma).
    btnEtiqueta.addEventListener("click", function () {
      var sel = selecionados();
      if (sel.length === 0) return;
      var ids = Array.prototype.map.call(sel, function (c) { return c.value; });
      var param = ehComputador ? "ids" : "baias";
      window.location.href = "/parque/etiquetas/?" + param + "=" + ids.join(",");
    });

    atualizar();
  }

  // ---------- Mapa da loja: clicar na baia "aproxima" do monitor ----------
  // Preenche o bloco "diagnóstico do desempenho" de um zoom (mz- ou nbz-).
  function preencherDiagnostico(prefixo, jsonStr, classe) {
    var box = document.getElementById(prefixo + "-diag");
    var titulo = document.getElementById(prefixo + "-diag-titulo");
    var lista = document.getElementById(prefixo + "-diag-lista");
    if (!box || !lista) return;
    var itens = [];
    try { itens = JSON.parse(jsonStr || "[]"); } catch (e) { itens = []; }
    lista.innerHTML = "";
    if (!itens.length) {
      box.className = "monitor__diag monitor__diag--ok";
      if (titulo) titulo.textContent = "Sem pontos críticos — equipamento em bom estado.";
      box.hidden = false;
      return;
    }
    box.className = "monitor__diag";
    if (titulo) {
      titulo.textContent = "Por que o score está " +
        (classe ? classe.toLowerCase() : "baixo") + " — e como resolver:";
    }
    itens.forEach(function (it) {
      var li = document.createElement("li");
      li.className = "monitor__diag-item monitor__diag-item--" + (it.nivel || "medio");
      var causa = document.createElement("b"); causa.textContent = it.causa;
      var sol = document.createElement("span"); sol.textContent = it.solucao;
      li.appendChild(causa); li.appendChild(sol);
      lista.appendChild(li);
    });
    box.hidden = false;
  }

  function initMapa() {
    var planta = document.getElementById("mapa-planta");
    var zoom = document.getElementById("mapa-zoom");
    // Basta o monitor (#mapa-zoom): a Preventiva reusa o zoom sem ter #mapa-planta.
    if (!zoom) return;

    var baiaAtual = null;  // pk da baia aberta no monitor (p/ finalizar reparo)

    function set(id, valor) {
      var el = document.getElementById(id);
      if (el) el.textContent = valor || "—";
    }

    // Finalizar reparo (fecha a manutenção + tarefa no Bitrix)
    var finalizarBtn = document.getElementById("mz-finalizar");
    if (finalizarBtn) {
      finalizarBtn.addEventListener("click", function () {
        if (!baiaAtual) return;
        var tokenEl = document.querySelector("[name=csrfmiddlewaretoken]");
        finalizarBtn.disabled = true;
        fetch("/parque/finalizar-reparo/" + baiaAtual + "/", {
          method: "POST",
          headers: { "X-CSRFToken": tokenEl ? tokenEl.value : "" },
        }).then(function (r) { return r.json(); }).then(function (j) {
          if (j.ok) { window.location.reload(); }
          else { finalizarBtn.disabled = false; mkAvisar(j.erro || "Não foi possível finalizar.", "error"); }
        }).catch(function () { finalizarBtn.disabled = false; });
      });
    }

    // ---- Helpers de UI (toast + modal de confirmação do sistema, sem popup nativo) ----
    function csrf() { var e = document.querySelector("[name=csrfmiddlewaretoken]"); return e ? e.value : ""; }
    function mzToast(msg, erro) {
      // Delegado ao painel do topo (ver mkAvisar). Antes escrevia no
      // #baia-toast, no canto do mapa.
      mkAvisar(msg, erro ? "error" : "success");
    }
    function mzPost(url, body, onErr) {
      fetch(url, {
        method: "POST",
        headers: { "X-CSRFToken": csrf(), "Content-Type": "application/x-www-form-urlencoded" },
        body: body,
      }).then(function (r) { return r.json(); }).then(function (j) {
        if (j.ok) { window.location.reload(); }
        else if (onErr) { onErr(j.erro || "Não foi possível concluir a ação."); }
      }).catch(function () { if (onErr) onErr("Falha de conexão."); });
    }

    var confirmModal = document.getElementById("baia-confirm");
    var _confirmCb = null;
    function mzConfirm(title, msg, onOk) {
      if (!confirmModal) { if (confirm(msg)) onOk(); return; }
      document.getElementById("baia-confirm-title").textContent = title || "Confirmar";
      document.getElementById("baia-confirm-msg").textContent = msg || "";
      _confirmCb = onOk;
      confirmModal.classList.add("is-open");
    }
    if (confirmModal) {
      var _cClose = function () { confirmModal.classList.remove("is-open"); _confirmCb = null; };
      document.getElementById("baia-confirm-ok").addEventListener("click", function () {
        var cb = _confirmCb; _cClose(); if (cb) cb();
      });
      document.getElementById("baia-confirm-cancel").addEventListener("click", _cClose);
      confirmModal.addEventListener("click", function (e) { if (e.target === confirmModal) _cClose(); });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && confirmModal.classList.contains("is-open")) _cClose();
      });
    }

    // ---- Seletor genérico (busca + lista), reutilizado p/ colaborador, PC e notebook ----
    function wirePicker(botao, modalId, nomeId, itemAttr, bodyKey, erroMsg) {
      var modal = document.getElementById(modalId);
      if (!modal) return;
      var busca = modal.querySelector(".baia-colab__busca");
      var lista = modal.querySelector(".baia-colab__lista");
      var nomeEl = nomeId ? document.getElementById(nomeId) : null;
      var fechar = modal.querySelector(".baia-colab__fechar");
      var alvo = null;
      function open(pk, nome) {
        alvo = pk || (botao && botao.dataset.baia) || null;
        if (!alvo) return;
        if (nomeEl) nomeEl.textContent = (nome != null ? nome : (botao && botao.dataset.baiaNome)) || "";
        if (busca) busca.value = "";
        lista.querySelectorAll(".baia-colab__item").forEach(function (it) { it.hidden = false; it.disabled = false; });
        modal.classList.add("is-open");
        if (busca) busca.focus();
      }
      function close() { modal.classList.remove("is-open"); }
      if (botao) botao.addEventListener("click", function () { open(); });
      if (fechar) fechar.addEventListener("click", close);
      modal.addEventListener("click", function (e) { if (e.target === modal) close(); });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && modal.classList.contains("is-open")) close();
      });
      if (busca) busca.addEventListener("input", function () {
        var q = busca.value.trim().toLowerCase();
        lista.querySelectorAll(".baia-colab__item").forEach(function (it) {
          it.hidden = q && (it.getAttribute("data-busca") || "").indexOf(q) === -1;
        });
      });
      lista.addEventListener("click", function (e) {
        var item = e.target.closest(".baia-colab__item");
        if (!item || !alvo) return;
        item.disabled = true;
        mzPost(modal.dataset.alocarUrl || modal.dataset.atribuirUrl,
          "baia=" + encodeURIComponent(alvo) + "&" + bodyKey + "=" + encodeURIComponent(item.getAttribute(itemAttr)),
          function (err) { item.disabled = false; mzToast(err || erroMsg, true); });
      });
      return { open: open };
    }

    // Botões do zoom: colaborador + dispositivo
    var retirarColab = document.getElementById("mz-retirar-colab");
    var atribuirColab = document.getElementById("mz-atribuir-colab");
    var alocarPcBtn = document.getElementById("mz-alocar-pc");
    var alocarNbBtn = document.getElementById("mz-alocar-nb");
    var removerDispBtn = document.getElementById("mz-remover-disp");

    wirePicker(atribuirColab, "baia-colab", "baia-colab-baia", "data-colab", "colaborador", "Não foi possível atribuir.");
    var pcPicker = wirePicker(alocarPcBtn, "baia-pc", "baia-pc-baia", "data-comp", "computador", "Não foi possível alocar.");
    wirePicker(alocarNbBtn, "baia-nb", "baia-nb-baia", "data-nb", "notebook", "Não foi possível alocar.");

    // Desativar para TROCA: manda a máquina p/ Desativados e recarrega já abrindo a
    // lista de substitutas do estoque (?trocar=<baia>).
    var trocaBtn = document.getElementById("mz-troca");
    if (trocaBtn) {
      trocaBtn.addEventListener("click", function (e) {
        e.preventDefault();
        var pk = trocaBtn.dataset.baia, patr = trocaBtn.dataset.patr || "esta máquina";
        if (!pk) return;
        mzConfirm("Desativar para troca",
          "A máquina " + patr + " vai para o estoque de Desativados (guardando de onde ela saiu). " +
          "Em seguida você escolhe a substituta do estoque. Continuar?",
          function () {
            fetch("/parque/desativar-para-troca/", {
              method: "POST",
              headers: { "X-CSRFToken": csrf(), "Content-Type": "application/x-www-form-urlencoded" },
              body: "baia=" + encodeURIComponent(pk),
            }).then(function (r) { return r.json(); }).then(function (j) {
              if (j.ok) {
                var u = new URL(window.location);
                u.searchParams.set("trocar", pk);
                window.location = u.toString();
              } else { mzToast(j.erro || "Não foi possível desativar.", true); }
            }).catch(function () { mzToast("Falha de conexão.", true); });
          });
      });
    }

    // Voltou da desativação? Abre direto a lista de máquinas do estoque p/ a mesa.
    var trocarPk = new URLSearchParams(window.location.search).get("trocar");
    if (trocarPk && pcPicker) {
      var elBaia = planta.querySelector('.baia[data-baia="' + trocarPk + '"]');
      var nomeBaia = elBaia ? elBaia.getAttribute("data-nome") : "";
      mzToast("Máquina desativada. Escolha a substituta do estoque.");
      pcPicker.open(trocarPk, nomeBaia);
      var u2 = new URL(window.location); u2.searchParams.delete("trocar");
      history.replaceState({}, "", u2.toString());
    }

    if (retirarColab) {
      retirarColab.addEventListener("click", function () {
        var pk = retirarColab.dataset.baia, nome = retirarColab.dataset.nome || "o colaborador";
        if (!pk) return;
        mzConfirm("Retirar colaborador",
          "Retirar " + nome + " desta mesa? O computador e as informações continuam na mesa.",
          function () { mzPost("/parque/remover-colaborador-baia/", "baia=" + encodeURIComponent(pk),
            function (err) { mzToast(err, true); }); });
      });
    }
    if (removerDispBtn) {
      removerDispBtn.addEventListener("click", function () {
        var pk = removerDispBtn.dataset.baia;
        if (!pk) return;
        mzConfirm("Remover dispositivo",
          "Remover o dispositivo desta mesa? Um computador volta ao estoque; um notebook fica livre. A mesa fica vazia.",
          function () { mzPost("/parque/remover-dispositivo-baia/", "baia=" + encodeURIComponent(pk),
            function (err) { mzToast(err, true); }); });
      });
    }

    function abrir(b) {
      var d = b.dataset;
      baiaAtual = d.baia || null;
      set("mz-pessoa", d.colaborador && d.colaborador !== "—" ? d.colaborador : d.nome);
      set("mz-baia", d.nome);
      // Botão "Retirar colaborador": só quando a baia tem uma pessoa vinculada.
      var temColab = d.colaborador && d.colaborador !== "—";
      if (retirarColab) {
        retirarColab.hidden = !temColab;
        retirarColab.disabled = false;
        retirarColab.dataset.baia = d.baia || "";
        retirarColab.dataset.nome = temColab ? d.colaborador : "";
      }
      // Atribuir só aparece quando a baia NÃO tem colaborador (senão, retire antes).
      if (atribuirColab) {
        atribuirColab.hidden = temColab;
        atribuirColab.disabled = false;
        atribuirColab.dataset.baia = d.baia || "";
        atribuirColab.dataset.baiaNome = d.nome || "";
      }
      // Dispositivo: mesa vazia mostra "Alocar computador/notebook"; com dispositivo mostra "Remover".
      var vazia = (d.tipo || d.pcstatus) === "sem_pc";
      [alocarPcBtn, alocarNbBtn].forEach(function (btn) {
        if (!btn) return;
        btn.hidden = !vazia;
        btn.disabled = false;
        btn.dataset.baia = d.baia || "";
        btn.dataset.baiaNome = d.nome || "";
      });
      if (removerDispBtn) {
        removerDispBtn.hidden = vazia;
        removerDispBtn.disabled = false;
        removerDispBtn.dataset.baia = d.baia || "";
      }
      // Patrimônio (ID único da máquina) — aparece SEMPRE; é o dado que vincula a máquina.
      var patr = document.getElementById("mz-patrimonio");
      if (patr) {
        patr.textContent = d.patrimonio ? (d.patrimonio) : "sem patrimônio";
        patr.classList.toggle("is-vazio", !d.patrimonio);
        // Clicar no patrimônio abre a etiqueta para impressão.
        var etq = (d.patrimonio && d.etiqueta) ? d.etiqueta : "";
        patr.classList.toggle("is-link", !!etq);
        patr.title = etq ? "Clique para abrir a etiqueta para impressão"
                         : "Patrimônio — identificador único da máquina";
        patr.onclick = etq ? function () { window.open(etq, "_blank"); } : null;
      }
      set("mz-status", d.status);
      var telEl = document.getElementById("mz-tel");
      if (telEl) {
        var telMap = { ativo: "Telemetria ativa", inativo: "Telemetria parada", sem: "Sem agente de coleta" };
        telEl.textContent = telMap[d.tel] || "";
        telEl.hidden = !telMap[d.tel];
      }
      set("mz-so", d.so);
      set("mz-cpu", d.cpu);
      set("mz-placa", d.placa);
      set("mz-ram", d.ram);
      set("mz-disco", d.disco);
      // Extras de telemetria — só aparecem quando o agente coletou (senão ficam ocultos).
      // `diverg` entra na mesma lista: é o aviso de que o cadastro (que é o que
      // as linhas acima mostram) discorda do que o agente mediu na máquina.
      [["diverg", d.divergencias], ["gpu", d.gpu], ["uptime", d.uptime], ["local", d.local]].forEach(function (par) {
        var li = document.getElementById("mz-" + par[0] + "-li");
        var sp = document.getElementById("mz-" + par[0]);
        var val = (par[1] || "").trim();
        if (sp) sp.textContent = val;
        if (li) li.hidden = !val;
      });
      set("mz-mouse", d.mouse);
      set("mz-teclado", d.teclado);
      set("mz-webcam", d.webcam);
      set("mz-headset", d.headset);
      set("mz-monitor", d.monitor);
      set("mz-leitor", d.leitor);
      var editar = document.getElementById("mz-editar");
      if (editar) editar.href = d.edit || "#";

      // Linhas que existem só quando há o dado (some o <li> inteiro se vazio).
      // `serial` vale para os dois tipos; `unidade`, `conta` e `anydesk` hoje
      // vêm do mapa de notebooks.
      ["serial", "unidade", "conta", "anydesk"].forEach(function (campo) {
        var alvo = document.getElementById("mz-" + campo);
        var linha = document.getElementById("mz-" + campo + "-li");
        var valor = d[campo] || "";
        if (alvo) alvo.textContent = valor;
        if (linha) linha.hidden = !valor;
      });

      // Notebook → o zoom vira um laptop (tela + base/teclado) em vez de monitor.
      zoom.classList.toggle("is-notebook", d.pcstatus === "notebook");

      // Badge de desempenho (verde→vermelho conforme a classe).
      var badge = document.getElementById("mz-desempenho");
      if (badge) {
        var classe = d.classe || "";
        if (d.desempenho && classe && classe !== "—") {
          badge.textContent = d.desempenho + " · " + classe;
          badge.dataset.classe = classe;
          badge.hidden = false;
        } else {
          badge.hidden = true;
        }
      }

      // Chamado de reparo / desativação — disponível para QUALQUER máquina.
      // Só o aviso vermelho aparece quando a máquina está crítica.
      var chamado = document.getElementById("mz-chamado");
      if (chamado) {
        var temBaia = !!d.reparo;
        chamado.hidden = !temBaia;
        var btnReparo = document.getElementById("mz-reparo");
        var btnTroca = document.getElementById("mz-troca");
        if (btnReparo) btnReparo.href = d.reparo || "#";
        if (btnTroca) {
          // "Desativar para troca" só faz sentido quando há um COMPUTADOR na mesa.
          btnTroca.hidden = !d.patrimonio;
          btnTroca.href = d.troca || "#";
          btnTroca.dataset.baia = d.baia || "";
          btnTroca.dataset.patr = d.patrimonio || "";
        }
        var ehCritico = d.classe === "Crítico";
        chamado.classList.toggle("is-critico", ehCritico);
        var aviso = document.getElementById("mz-critico-msg");
        if (aviso) aviso.hidden = !ehCritico;
        // Finalizar reparo só quando a máquina está em manutenção.
        baiaAtual = d.baia || null;
        var fin = document.getElementById("mz-finalizar");
        if (fin) { fin.hidden = d.chamado !== "1"; fin.disabled = false; }
      }

      // Diagnóstico: causas do score + soluções.
      preencherDiagnostico("mz", d.diag, d.classe);

      // Tela com efeito de DEFEITO (riscos/scanlines/glitch) quando crítica.
      var monitor = zoom.querySelector(".monitor");
      if (monitor) monitor.classList.toggle("monitor--defeito", d.classe === "Crítico");

      zoom.classList.add("is-open");
      document.body.style.overflow = "hidden";
    }

    function fechar() {
      zoom.classList.remove("is-open");
      document.body.style.overflow = "";
    }

    // ---------------------------------------------------------------------
    // CHEGAR DE FORA JÁ COM A MÁQUINA ABERTA (?baia=123)
    //
    // Quem clica num registro (Registros, notificação, agenda) quer ver AQUELA
    // máquina — não o mapa da loja para procurar qual era. Com o parâmetro na
    // URL, o mapa rola até ela e abre o painel dela.
    //
    // Roda depois de `abrir` estar definida e antes de nada mais precisar
    // dela; se a baia não estiver nesta planta (loja errada, baia removida),
    // não faz nada — o mapa abre normal.
    try {
      var busca = new URLSearchParams(window.location.search);
      var pedida = busca.get("baia");
      var alvoBaia = pedida
        ? document.querySelector('.baia[data-baia="' + pedida + '"]')
        : null;

      // ?patrimonio=PC-CG0111 — quem chega do Mural traz o PATRIMONIO, nao o
      // pk da baia. Nao precisa de consulta: o _baia.html ja' publica o
      // patrimonio no proprio elemento, e o mesmo parcial desenha PC e
      // notebook, entao os dois funcionam sem caso especial.
      if (!alvoBaia) {
        var patr = (busca.get("patrimonio") || "").trim();
        if (patr) {
          var todas = document.querySelectorAll(".baia[data-patrimonio]");
          for (var i = 0; i < todas.length; i++) {
            if ((todas[i].dataset.patrimonio || "").trim().toLowerCase()
                === patr.toLowerCase()) { alvoBaia = todas[i]; break; }
          }
          if (!alvoBaia && window.mkAvisar) {
            mkAvisar("Não achei a máquina " + patr + " neste mapa.", "error");
          }
        }
      }

      if (alvoBaia) {
        alvoBaia.scrollIntoView({ behavior: "smooth", block: "center" });
        abrir(alvoBaia);
      }
    } catch (e) {}

    // Publicado de propósito: o mapa de NOTEBOOKS abre o mesmo painel, e a
    // única coisa que ele precisa é chamar este `abrir` com um objeto que
    // tenha os campos esperados no `dataset`. Sem isto voltaríamos a ter dois
    // painéis para a mesma pergunta — foi o que o dono reclamou.
    window.mkAbrirZoom = abrir;
    window.mkFecharZoom = fechar;

    function abrirDaLista(e) {
      var b = e.target.closest(".baia");
      if (b) abrir(b);
    }
    if (planta) planta.addEventListener("click", abrirDaLista);
    // Preventiva: o carrossel do dia também abre o MESMO monitor ao clicar num card.
    var pvcar = document.getElementById("pv-day-car");
    if (pvcar) pvcar.addEventListener("click", abrirDaLista);
    // Painel de Tarefas: a loja oculta de cards abre o mesmo monitor (via initVerMaquina).
    var tfcards = document.getElementById("tf-cards");
    if (tfcards) tfcards.addEventListener("click", abrirDaLista);
    var fecharBtn = document.getElementById("mapa-zoom-fechar");
    if (fecharBtn) fecharBtn.addEventListener("click", fechar);
    zoom.addEventListener("click", function (e) {
      if (e.target === zoom) fechar();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && zoom.classList.contains("is-open")) fechar();
    });
  }

  // ---------- Gráficos clicáveis (barra → mapa) ----------
  function initChartNav() {
    document.querySelectorAll("[data-chart-nav]").forEach(function (box) {
      var urls;
      try { urls = JSON.parse(box.getAttribute("data-chart-nav")); } catch (e) { return; }
      if (!urls || !urls.length) return;
      var canvas = box.querySelector("canvas");
      if (!canvas) return;
      var porSerie = box.getAttribute("data-chart-nav-mode") === "dataset";
      canvas.style.cursor = "pointer";
      canvas.addEventListener("click", function (evt) {
        if (!window.Chart || !window.Chart.getChart) return;
        var chart = window.Chart.getChart(canvas);
        if (!chart) return;
        var pts = chart.getElementsAtEventForMode(
          evt, "nearest", { intersect: true }, true
        );
        if (!pts || !pts.length) return;
        var idx = porSerie ? pts[0].datasetIndex : pts[0].index;
        if (urls[idx]) window.location.href = urls[idx];
      });
    });
  }

  // ---------- Tabela de dispositivos (modo tabela): clique na linha + filtro ----------
  function initTabelaDispositivos() {
    var body = document.getElementById("tab-body");
    if (!body) return;

    // Clique na linha abre a edição (exceto na coluna de seleção).
    body.querySelectorAll("tr.tab-row[data-edit]").forEach(function (tr) {
      tr.addEventListener("click", function (e) {
        if (e.target.closest(".tab-col-chk")) return;
        window.location.href = tr.getAttribute("data-edit");
      });
    });

    // Busca na lista: usa o data-busca (nº série, patrimônio, nome, usuário, specs…),
    // sem acento/caixa. Mostra "sem resultado" e limpa com o × / Esc.
    var inp = document.getElementById("tab-busca");
    if (inp) {
      var limpar = document.getElementById("tab-busca-x");
      var semRes = document.getElementById("tab-sem-busca");
      var linhas = Array.prototype.slice.call(body.querySelectorAll("tr.tab-row"));
      function norm(s) {
        return (s || "").toString().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
      }
      linhas.forEach(function (tr) {
        tr._busca = norm(tr.getAttribute("data-busca") || tr.textContent);
      });
      function aplicar() {
        var q = norm(inp.value.trim());
        if (limpar) limpar.hidden = !q;
        var achou = 0;
        linhas.forEach(function (tr) {
          var ok = !q || tr._busca.indexOf(q) !== -1;
          tr.style.display = ok ? "" : "none";
          if (ok) achou++;
        });
        if (semRes) semRes.hidden = !(q && achou === 0);
      }
      inp.addEventListener("input", aplicar);
      inp.addEventListener("keydown", function (e) { if (e.key === "Escape") { inp.value = ""; aplicar(); } });
      if (limpar) limpar.addEventListener("click", function () { inp.value = ""; aplicar(); inp.focus(); });
    }

    // ----- Barra FLUTUANTE de ações (mesma .make-fab-bar do changelist) -----
    var transferirUrl = body.getAttribute("data-transferir");          // transferir (nível tabela)
    var transferirRow = body.getAttribute("data-transferir-row") === "1"; // transferir por item (peça)
    var atribuirUrl = body.getAttribute("data-atribuir");
    var caixaUrl = body.getAttribute("data-caixa");                    // montar caixa (2+)
    var etiquetaUrl = body.getAttribute("data-etiqueta");              // imprimir etiqueta(s) (1+)
    var podeExcluir = body.getAttribute("data-pode-excluir") === "1";
    var ehNotebook = body.getAttribute("data-modelo") === "notebook";   // termo só p/ notebooks
    var token = (document.querySelector("[name=csrfmiddlewaretoken]") || {}).value || "";
    var temTransferir = !!(transferirUrl || transferirRow);
    var all = document.getElementById("tr-all");
    function chks() { return Array.prototype.slice.call(body.querySelectorAll(".tr-chk")); }
    function marcados() { return chks().filter(function (c) { return c.checked; }); }
    function tabToast(msg, erro) {
      // Delegado ao painel do topo (ver mkAvisar).
      mkAvisar(msg, erro ? "error" : "success");
    }

    var bar = document.createElement("div");
    bar.className = "make-fab-bar";
    bar.innerHTML =
      '<span class="make-fab-count"></span>' +
      '<button type="button" class="make-fab make-fab--alterar">'+mkIco('pencil')+' Alterar</button>' +
      (temTransferir ? '<button type="button" class="make-fab make-fab--transferir">'+mkIco('truck')+' Transferir</button>' : '') +
      (atribuirUrl ? '<button type="button" class="make-fab make-fab--atribuir">'+mkIco('user')+' Atribuir</button>' : '') +
      (caixaUrl ? '<button type="button" class="make-fab make-fab--caixa">'+mkIco('box')+' Montar caixa</button>' : '') +
      (etiquetaUrl ? '<button type="button" class="make-fab make-fab--etiqueta">'+mkIco('tag')+' Etiqueta(s)</button>' : '') +
      (ehNotebook ? '<button type="button" class="make-fab make-fab--termo">'+mkIco('doc')+' Gerar termo</button>' : '') +
      '<button type="button" class="make-fab make-fab--reativar" hidden>'+mkIco('recycle')+' Reativar</button>' +
      (podeExcluir ? '<button type="button" class="make-fab make-fab--excluir">'+mkIco('trash')+' Excluir</button>' : '');
    document.body.appendChild(bar);

    var btnAlt = bar.querySelector(".make-fab--alterar");
    var btnTr = bar.querySelector(".make-fab--transferir");
    var btnAtr = bar.querySelector(".make-fab--atribuir");
    var btnCx = bar.querySelector(".make-fab--caixa");
    var btnEtq = bar.querySelector(".make-fab--etiqueta");
    var btnTermo = bar.querySelector(".make-fab--termo");
    var btnRea = bar.querySelector(".make-fab--reativar");
    var btnExc = bar.querySelector(".make-fab--excluir");
    var contador = bar.querySelector(".make-fab-count");

    function atualizar() {
      var sel = marcados();
      bar.classList.toggle("is-open", sel.length > 0);
      contador.textContent = sel.length + (sel.length > 1 ? " selecionados" : " selecionado");
      var um = sel.length === 1;
      if (btnAlt) { btnAlt.disabled = !um; btnAlt.title = um ? "Alterar" : "Selecione exatamente 1"; }
      if (btnTr) btnTr.disabled = !um;
      if (btnAtr) btnAtr.disabled = !um;
      if (btnCx) { btnCx.disabled = sel.length < 2; btnCx.title = sel.length < 2 ? "Selecione 2 ou mais" : "Montar caixa"; }
      if (btnEtq) btnEtq.disabled = sel.length < 1;
      if (btnTermo) { btnTermo.disabled = !um; btnTermo.title = um ? "Gerar termo de responsabilidade" : "Selecione exatamente 1"; }
      // Reativar: só quando 1 item DESATIVADO (a linha tem data-reativar) está marcado.
      if (btnRea) {
        var rea = um ? sel[0].closest("tr").getAttribute("data-reativar") : "";
        btnRea.hidden = !rea;
      }
      if (all) {
        var todos = chks();
        all.checked = todos.length > 0 && sel.length === todos.length;
        all.indeterminate = sel.length > 0 && sel.length < todos.length;
      }
    }

    if (all) all.addEventListener("change", function () {
      var v = all.checked;
      chks().forEach(function (c) { c.checked = v; });
      atualizar();
    });
    chks().forEach(function (c) { c.addEventListener("change", atualizar); });

    if (btnAlt) btnAlt.addEventListener("click", function () {
      var sel = marcados();
      if (sel.length === 1) window.location.href = sel[0].closest("tr").getAttribute("data-edit");
    });
    if (btnTr) btnTr.addEventListener("click", function () {
      var sel = marcados();
      if (sel.length !== 1) return;
      // Por item (peça) usa o data-transferir da linha; senão o da tabela (mapa).
      var destino = transferirRow ? sel[0].closest("tr").getAttribute("data-transferir") : transferirUrl;
      if (destino) window.location.href = destino;
    });
    if (btnAtr) btnAtr.addEventListener("click", function () {
      if (marcados().length === 1 && atribuirUrl) window.location.href = atribuirUrl;
    });
    if (btnCx) btnCx.addEventListener("click", function () {
      var ids = marcados().map(function (c) { return c.value; });
      if (ids.length >= 2 && caixaUrl) {
        window.location.href = caixaUrl + (caixaUrl.indexOf("?") >= 0 ? "&" : "?") + "ids=" + ids.join(",");
      }
    });
    if (btnEtq) btnEtq.addEventListener("click", function () {
      var ids = marcados().map(function (c) { return c.value; });
      if (!ids.length || !etiquetaUrl) return;
      // A view de etiquetas casa por: nb_ids (Notebook), baias (Baia) ou ids (Computador).
      var modelo = body.getAttribute("data-modelo");
      var param = modelo === "notebook" ? "nb_ids" : (modelo === "baia" ? "baias" : "ids");
      window.location.href = etiquetaUrl + "?" + param + "=" + ids.join(",");
    });
    if (btnTermo) btnTermo.addEventListener("click", function () {
      var sel = marcados();
      if (sel.length !== 1) return;
      btnTermo.disabled = true;
      fetch("/parque/gerar-termo-notebook/", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": token },
        body: "notebook=" + encodeURIComponent(sel[0].value),
      })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          btnTermo.disabled = false;
          if (res.ok && res.j.ok) {
            tabToast(res.j.msg || "Termo gerado.");
            if (res.j.url) window.open(res.j.url, "_blank");
          } else {
            tabToast((res.j && res.j.erro) || "Não foi possível gerar o termo.", true);
          }
        })
        .catch(function () { btnTermo.disabled = false; tabToast("Erro de conexão.", true); });
    });
    if (btnRea) btnRea.addEventListener("click", function () {
      var sel = marcados();
      if (sel.length !== 1) return;
      var url = sel[0].closest("tr").getAttribute("data-reativar");
      if (url) window.location.href = url;
    });
    if (btnExc) btnExc.addEventListener("click", function () {
      if (!marcados().length) return;
      var form = document.getElementById("disp-bulk-form");
      if (!form) return;
      if (form.requestSubmit) form.requestSubmit(); else form.submit();
    });

    atualizar();
  }

  // ---------- Explorador de SCORE: slider de faixa que filtra os gráficos ----------
  function initScoreExplorer() {
    var dataEl = document.getElementById("score-itens-data");
    if (!dataEl) return;
    var itens;
    try { itens = JSON.parse(dataEl.textContent); } catch (e) { return; }
    if (!itens.length) return;

    var elMin = document.getElementById("score-min");
    var elMax = document.getElementById("score-max");
    var elSel = document.getElementById("score-sel");
    var elCount = document.getElementById("score-count");
    var elMedia = document.getElementById("score-media");
    var elFaixa = document.getElementById("score-faixa");
    if (!elMin || !elMax) return;

    var CORES = { "Crítico": "#e0533f", "Baixo": "#ef8f3c", "Bom": "#8fb82e", "Ótimo": "#00a651" };
    var ORDEM = ["Crítico", "Baixo", "Bom", "Ótimo"];

    // Histograma: 10 faixas (0-9 … 90-100). Altura fixa = todas as máquinas.
    var binLabels = [], binAll = [0,0,0,0,0,0,0,0,0,0];
    for (var i = 0; i < 10; i++) binLabels.push((i * 10) + (i < 9 ? "-" + (i * 10 + 9) : "-100"));
    itens.forEach(function (d) { binAll[Math.min(9, Math.floor(d.s / 10))]++; });

    // Os gráficos são criados em build(), que espera o Chart.js terminar de
    // carregar (o unfold injeta o Chart.js depois deste script).
    var chartHist, chartClasse, chartUni;

    function aplicar() {
      var lo = parseInt(elMin.value, 10), hi = parseInt(elMax.value, 10);
      if (lo > hi) { var t = lo; lo = hi; hi = t; }
      elSel.style.left = lo + "%";
      elSel.style.width = (hi - lo) + "%";

      var sel = itens.filter(function (d) { return d.s >= lo && d.s <= hi; });
      elCount.textContent = sel.length;
      elFaixa.textContent = lo + "–" + hi;
      elMedia.textContent = sel.length
        ? Math.round(sel.reduce(function (a, d) { return a + d.s; }, 0) / sel.length) : 0;

      if (!chartHist) return;  // gráficos ainda não montaram (Chart.js carregando)
      chartHist.data.datasets[0].backgroundColor = binLabels.map(function (_, i) {
        var c = i * 10, f = (i < 9 ? i * 10 + 9 : 100);
        return (f >= lo && c <= hi) ? "#00a651" : "#93a19a";
      });
      chartHist.update();

      var porClasse = { "Crítico": 0, "Baixo": 0, "Bom": 0, "Ótimo": 0 };
      sel.forEach(function (d) { if (porClasse[d.c] != null) porClasse[d.c]++; });
      chartClasse.data.datasets[0].data = ORDEM.map(function (c) { return porClasse[c]; });
      chartClasse.update();

      var porUni = {};
      sel.forEach(function (d) { porUni[d.u] = (porUni[d.u] || 0) + 1; });
      var arr = Object.keys(porUni).map(function (k) { return [k, porUni[k]]; })
        .sort(function (a, b) { return b[1] - a[1]; }).slice(0, 8);
      chartUni.data.labels = arr.map(function (x) { return x[0]; });
      chartUni.data.datasets[0].data = arr.map(function (x) { return x[1]; });
      chartUni.update();
    }

    // Faixa atual (mín/máx já ordenados).
    function faixa() {
      var lo = parseInt(elMin.value, 10), hi = parseInt(elMax.value, 10);
      return lo > hi ? [hi, lo] : [lo, hi];
    }
    // Abre o mapa por score (PCs + notebooks) com os filtros escolhidos.
    function irMapa(params) {
      var q = Object.keys(params).map(function (k) {
        return k + "=" + encodeURIComponent(params[k]);
      }).join("&");
      window.location.href = "/parque/mapa-score/?" + q;
    }
    function maoCursor(e) {
      var alvo = e && (e.native ? e.native.target : e.target);
      if (alvo) alvo.style.cursor = (e.chart && e.chart.getActiveElements && e.chart.getActiveElements().length) ? "pointer" : "default";
    }

    var tentativas = 0;
    function build() {
      if (!window.Chart) {
        if (tentativas++ < 25) return setTimeout(build, 200);  // espera o Chart.js
        return;
      }
      // Paleta ciente do tema (dark premium): eixos/grade/legenda legíveis no escuro.
      var _dark = document.documentElement.classList.contains("dark") || document.body.classList.contains("dark");
      var TICK = _dark ? "#9db0a5" : "#5f6f66";
      var GRID = _dark ? "rgba(255,255,255,.09)" : "rgba(16,40,27,.08)";
      var DOUGH_BORDER = _dark ? "#0f1512" : "#ffffff";
      chartHist = new Chart(document.getElementById("score-hist"), {
        type: "bar",
        data: { labels: binLabels, datasets: [{ data: binAll, backgroundColor: [], borderRadius: 5 }] },
        options: { maintainAspectRatio: false, animation: { duration: 250 }, onHover: maoCursor,
          // Clicar numa barra abre o mapa só daquela faixa de score.
          onClick: function (e, els) { if (els && els.length) { var i = els[0].index; irMapa({ min: i * 10, max: i < 9 ? i * 10 + 9 : 100 }); } },
          plugins: { legend: { display: false } },
          scales: { y: { beginAtZero: true, ticks: { precision: 0, color: TICK }, grid: { color: GRID } },
                    x: { grid: { display: false }, ticks: { color: TICK } } } },
      });
      chartClasse = new Chart(document.getElementById("score-classe"), {
        type: "doughnut",
        data: { labels: ORDEM.slice(), datasets: [{ data: [0,0,0,0],
          backgroundColor: ORDEM.map(function (c) { return CORES[c]; }),
          borderColor: DOUGH_BORDER, borderWidth: 2, hoverOffset: 8 }] },
        options: { maintainAspectRatio: false, cutout: "58%", animation: { duration: 250 }, onHover: maoCursor,
          // Clicar numa classe abre o mapa daquela classe na faixa atual.
          onClick: function (e, els) { if (els && els.length) { var f = faixa(); irMapa({ min: f[0], max: f[1], classe: ORDEM[els[0].index] }); } },
          plugins: { legend: { display: true, position: "right",
            labels: { boxWidth: 12, padding: 10, usePointStyle: true, font: { size: 12 }, color: TICK } } } },
      });
      chartUni = new Chart(document.getElementById("score-unidade"), {
        type: "bar",
        data: { labels: [], datasets: [{ data: [], backgroundColor: "#00a651", borderRadius: 5 }] },
        options: { maintainAspectRatio: false, indexAxis: "y", animation: { duration: 250 }, onHover: maoCursor,
          // Clicar numa unidade abre o mapa daquela unidade na faixa atual.
          onClick: function (e, els) { if (els && els.length) { var f = faixa(); irMapa({ min: f[0], max: f[1], unidade: chartUni.data.labels[els[0].index] }); } },
          plugins: { legend: { display: false } },
          scales: { x: { beginAtZero: true, ticks: { precision: 0, color: TICK }, grid: { color: GRID } },
                    y: { grid: { display: false }, ticks: { color: TICK } } } },
      });
      aplicar();
    }

    elMin.addEventListener("input", aplicar);
    elMax.addEventListener("input", aplicar);
    var btnMapa = document.getElementById("score-ver-mapa");
    if (btnMapa) btnMapa.addEventListener("click", function () { var f = faixa(); irMapa({ min: f[0], max: f[1] }); });
    build();
  }

  // ---------- Form de Reparo: campos dependentes da "Peça a trocar" ----------
  //  • "Outra peça"  → habilita "Qual peça (outra)" (obrigatório).
  //  • "Nenhuma"     → desativa cotação, ID Bitrix e custo (só reparo/manutenção).
  function initReparoPecaCampos() {
    var sel = document.getElementById("id_peca");
    var tipo = document.getElementById("id_tipo");
    if (!sel && !tipo) return;
    var outro = document.getElementById("id_peca_outro");
    var cotacao = document.getElementById("id_realizar_cotacao");
    var bitrix = document.getElementById("id_bitrix_task_id");
    var custo = document.getElementById("id_custo");

    function setCampo(el, ativo, limpar) {
      if (!el) return;
      el.disabled = !ativo;
      if (!ativo && limpar) {
        if (el.type === "checkbox") el.checked = false;
        else el.value = "";
      }
      var linha = el.closest(".form-row, fieldset > div") || el.parentNode;
      if (linha && linha.style) linha.style.opacity = ativo ? "" : ".5";
    }

    function sync() {
      // Desativação para troca: não há peça nem cotação — desativa tudo.
      if (tipo && tipo.value === "desativacao") {
        setCampo(sel, false, true);
        setCampo(outro, false, true);
        setCampo(cotacao, false, true);
        setCampo(bitrix, false, true);
        if (outro) outro.required = false;
        return;
      }
      setCampo(sel, true, false);  // reabilita a peça nos outros tipos
      var v = sel ? sel.value : "";
      var nenhuma = v === "nenhuma";
      var ehOutro = v === "outro";
      setCampo(outro, ehOutro, true);
      if (outro) outro.required = ehOutro;
      // Sem troca de peça → não há cotação/compra nem custo.
      setCampo(cotacao, !nenhuma, true);
      setCampo(bitrix, !nenhuma, true);
      setCampo(custo, !nenhuma, true);
    }

    if (sel) sel.addEventListener("change", sync);
    if (tipo) tipo.addEventListener("change", sync);
    sync();
  }

  // ---------- Mapa: arrastar baia para outro setor (mover/solicitar) ----------
  function initMapaDnD() {
    var mapa = document.querySelector(".mapa");
    var planta = document.getElementById("mapa-planta");
    var modal = document.getElementById("mov-modal");
    if (!mapa || !planta || !modal) return;

    var podeMover = mapa.getAttribute("data-pode-mover") === "1";
    var tokenEl = document.querySelector('[name=csrfmiddlewaretoken]');
    var token = tokenEl ? tokenEl.value : "";
    var drag = null, pendente = null;

    var title = document.getElementById("mov-modal-title");
    var msg = document.getElementById("mov-modal-msg");
    var okBtn = document.getElementById("mov-ok");
    var cancelBtn = document.getElementById("mov-cancel");
    // Modal de troca (arrastar uma baia sobre outra)
    var trocaModal = document.getElementById("trocar-modal");

    function escapeHtml(s) { var d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }

    planta.addEventListener("dragstart", function (e) {
      var b = e.target.closest(".baia[data-baia]");
      if (!b) return;
      drag = { baia: b.getAttribute("data-baia"), setor: b.getAttribute("data-setor"), nome: b.getAttribute("data-nome") };
      try { e.dataTransfer.setData("text/plain", drag.baia); e.dataTransfer.effectAllowed = "move"; } catch (x) {}
    });
    function limparRealces() {
      var a = planta.querySelector(".baia--alvo");
      if (a) a.classList.remove("baia--alvo");
      planta.querySelectorAll(".mapa-setor__baias.is-drop").forEach(function (z) {
        z.classList.remove("is-drop");
      });
    }

    planta.addEventListener("dragover", function (e) {
      if (!drag) return;
      var alvo = e.target.closest(".baia[data-baia]");
      var zona = e.target.closest(".mapa-setor__baias");
      var alvoOk = alvo && alvo.getAttribute("data-baia") !== drag.baia;
      var zonaOk = !alvoOk && zona && zona.getAttribute("data-setor") !== drag.setor;
      if (!alvoOk && !zonaOk) { limparRealces(); return; }
      e.preventDefault();
      limparRealces();
      if (alvoOk) alvo.classList.add("baia--alvo");   // vai trocar com esta
      else zona.classList.add("is-drop");             // vai mover para este setor
    });
    planta.addEventListener("dragend", limparRealces);
    // Auto-scroll: ao arrastar perto das bordas, a página acompanha.
    document.addEventListener("dragover", function (e) {
      if (!drag) return;
      var y = e.clientY, h = window.innerHeight, margem = 90;
      if (y < margem) window.scrollBy(0, -20);
      else if (y > h - margem) window.scrollBy(0, 20);
    });
    planta.addEventListener("dragleave", function (e) {
      // Só limpa quando o cursor realmente sai do mapa (evita piscar entre baias).
      if (!planta.contains(e.relatedTarget)) limparRealces();
    });
    planta.addEventListener("drop", function (e) {
      if (!drag) return;
      var alvo = e.target.closest(".baia[data-baia]");
      var zona = e.target.closest(".mapa-setor__baias");
      limparRealces();
      // Soltou SOBRE outra baia → trocar os computadores.
      if (alvo && alvo.getAttribute("data-baia") !== drag.baia) {
        e.preventDefault();
        confirmarTroca(drag, {
          baia: alvo.getAttribute("data-baia"),
          nome: alvo.getAttribute("data-nome"),
          colab: alvo.getAttribute("data-colaborador"),
        });
        return;
      }
      // Soltou na área de outro setor → mover.
      if (zona && zona.getAttribute("data-setor") !== drag.setor) {
        e.preventDefault();
        zona.classList.remove("is-drop");
        abrirModal(drag, zona.getAttribute("data-setor-nome"), zona.getAttribute("data-setor"));
      }
    });

    // ----- Troca de computadores entre duas baias (#trocar-modal) -----
    function confirmarTroca(d, alvo) {
      if (!trocaModal) return;
      var tTitle = document.getElementById("trocar-title");
      var tMsg = document.getElementById("trocar-msg");
      var tOk = document.getElementById("trocar-ok");
      var tCancel = document.getElementById("trocar-cancel");
      function consultor(x) { return (x.colab && x.colab !== "—") ? x.colab : x.nome; }
      var quem = "<b>" + escapeHtml(consultor(d)) + "</b> (" + escapeHtml(d.nome) +
        ") e <b>" + escapeHtml(consultor(alvo)) + "</b> (" + escapeHtml(alvo.nome) + ")";
      tTitle.textContent = podeMover ? "Trocar computadores" : "Solicitar troca";
      tMsg.innerHTML = podeMover
        ? "Trocar o computador entre " + quem + "?"
        : "Solicitar a troca de computador entre " + quem +
          "?<br>Um responsável (Téc. Pós Venda, Supervisor ou Gerente) precisará autorizar.";
      tOk.textContent = podeMover ? "Trocar" : "Enviar solicitação";
      tOk.disabled = false; tOk.style.display = ""; tCancel.textContent = "Cancelar";
      trocaModal.classList.add("is-open");
      tOk.onclick = function () {
        tOk.disabled = true;
        fetch("/parque/trocar-pcs/", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": token },
          body: "baia_a=" + encodeURIComponent(d.baia) + "&baia_b=" + encodeURIComponent(alvo.baia),
        }).then(function (r) { return r.json(); }).then(function (j) {
          if (j.ok && j.status === "aplicada") { window.location.reload(); }
          else if (j.ok) {
            tTitle.textContent = "Solicitação enviada";
            tMsg.textContent = j.msg || "Enviada para autorização.";
            tOk.style.display = "none"; tCancel.textContent = "Fechar";
          } else {
            tTitle.textContent = "Não foi possível";
            tMsg.textContent = j.erro || "Erro."; tOk.style.display = "none"; tCancel.textContent = "Fechar";
          }
        }).catch(function () { tOk.disabled = false; });
      };
      tCancel.onclick = function () { trocaModal.classList.remove("is-open"); drag = null; };
    }
    if (trocaModal) {
      trocaModal.addEventListener("click", function (e) {
        if (e.target === trocaModal) trocaModal.classList.remove("is-open");
      });
    }

    function abrirModal(d, destinoNome, destinoId) {
      pendente = { baiaId: d.baia, setorId: destinoId };
      title.textContent = podeMover ? "Mover baia" : "Solicitar movimentação";
      msg.innerHTML = podeMover
        ? "Mover <b>" + escapeHtml(d.nome) + "</b> para o setor <b>" + escapeHtml(destinoNome) + "</b>?"
        : "Solicitar a movimentação de <b>" + escapeHtml(d.nome) + "</b> para <b>" + escapeHtml(destinoNome) + "</b>?<br>Um responsável (Téc. Pós Venda, Supervisor ou Gerente) precisará autorizar.";
      okBtn.textContent = podeMover ? "Confirmar" : "Enviar solicitação";
      okBtn.disabled = false; okBtn.style.display = "";
      cancelBtn.textContent = "Cancelar";
      modal.classList.add("is-open");
    }
    function fecharModal() { modal.classList.remove("is-open"); pendente = null; drag = null; }
    function resultado(texto, erro) {
      title.textContent = erro ? "Não foi possível" : "Pronto";
      msg.textContent = texto;
      okBtn.style.display = "none";
      cancelBtn.textContent = "Fechar";
    }

    cancelBtn.addEventListener("click", fecharModal);
    modal.addEventListener("click", function (e) { if (e.target === modal) fecharModal(); });

    okBtn.addEventListener("click", function () {
      if (!pendente) return;
      okBtn.disabled = true;
      fetch("/parque/mover-baia/", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": token },
        body: "baia_id=" + encodeURIComponent(pendente.baiaId) + "&setor_destino_id=" + encodeURIComponent(pendente.setorId),
      })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          if (res.ok && res.j.ok && res.j.status === "aplicada") { window.location.reload(); }
          else if (res.ok && res.j.ok) { resultado(res.j.msg || "Solicitação enviada."); }
          else { resultado(res.j.erro || "Não foi possível mover.", true); }
        })
        .catch(function () { resultado("Erro de conexão.", true); });
    });
  }

  // ---------- Mapa: trocar computadores entre 2 baias (consultores) ----------
  function initMapaTrocar() {
    var planta = document.getElementById("mapa-planta");
    var btn = document.getElementById("mapa-trocar");
    var modal = document.getElementById("trocar-modal");
    if (!planta || !btn || !modal) return;

    var token = (document.querySelector("[name=csrfmiddlewaretoken]") || {}).value || "";
    var ativo = false, sel = [];
    var title = document.getElementById("trocar-title");
    var msg = document.getElementById("trocar-msg");
    var ok = document.getElementById("trocar-ok");
    var cancel = document.getElementById("trocar-cancel");

    function esc(s) { var d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }
    function limpar() { sel.forEach(function (s) { s.el.classList.remove("baia--sel"); }); sel = []; }
    function sair() { ativo = false; planta.classList.remove("modo-trocar"); btn.classList.remove("is-on"); btn.textContent = "Trocar PCs"; limpar(); }

    btn.addEventListener("click", function () {
      ativo = !ativo;
      planta.classList.toggle("modo-trocar", ativo);
      btn.classList.toggle("is-on", ativo);
      btn.textContent = ativo ? "Cancelar troca" : "Trocar PCs";
      limpar();
    });

    // Captura o clique antes do zoom abrir.
    planta.addEventListener("click", function (e) {
      if (!ativo) return;
      var b = e.target.closest(".baia[data-baia]");
      if (!b) return;
      e.preventDefault();
      e.stopPropagation();
      var id = b.getAttribute("data-baia");
      var idx = -1;
      for (var i = 0; i < sel.length; i++) { if (sel[i].baia === id) { idx = i; break; } }
      if (idx >= 0) { sel[idx].el.classList.remove("baia--sel"); sel.splice(idx, 1); return; }
      if (sel.length >= 2) return;
      b.classList.add("baia--sel");
      sel.push({ el: b, baia: id, nome: b.getAttribute("data-nome"), colab: b.getAttribute("data-colaborador") });
      if (sel.length === 2) confirmar();
    }, true);

    function consultor(s) { return (s.colab && s.colab !== "—") ? s.colab : s.nome; }

    function confirmar() {
      var a = sel[0], c = sel[1];
      title.textContent = "Trocar computadores";
      msg.innerHTML = "Trocar o computador entre <b>" + esc(consultor(a)) + "</b> (" + esc(a.nome) +
        ") e <b>" + esc(consultor(c)) + "</b> (" + esc(c.nome) + ")?";
      ok.textContent = "Trocar"; ok.disabled = false; ok.style.display = ""; cancel.textContent = "Cancelar";
      modal.classList.add("is-open");
      ok.onclick = function () {
        ok.disabled = true;
        fetch("/parque/trocar-pcs/", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": token },
          body: "baia_a=" + encodeURIComponent(a.baia) + "&baia_b=" + encodeURIComponent(c.baia),
        }).then(function (r) { return r.json(); }).then(function (j) {
          if (j.ok) { window.location.reload(); }
          else { title.textContent = "Não foi possível"; msg.textContent = j.erro || "Erro."; ok.style.display = "none"; cancel.textContent = "Fechar"; }
        }).catch(function () { ok.disabled = false; });
      };
      cancel.onclick = function () { modal.classList.remove("is-open"); sair(); };
    }
  }

  // ---------- Mapa no CELULAR: clique longo + arrastar até o setor ----------
  function initMapaTouch() {
    var mapa = document.querySelector(".mapa");
    var planta = document.getElementById("mapa-planta");
    var modal = document.getElementById("mov-modal");
    if (!mapa || !planta || !modal || !("ontouchstart" in window)) return;

    var podeMover = mapa.getAttribute("data-pode-mover") === "1";
    var tokenEl = document.querySelector('[name=csrfmiddlewaretoken]');
    var token = tokenEl ? tokenEl.value : "";

    var overlay = document.createElement("div");
    overlay.className = "mov-touch";
    overlay.innerHTML =
      '<div class="mov-touch__head"><b id="mt-baia"></b>' +
      '<span>Arraste até o setor de destino e solte</span></div>' +
      '<div class="mov-touch__grid" id="mt-grid"></div>' +
      '<button type="button" class="mov-touch__cancel" id="mt-cancel">Cancelar</button>';
    document.body.appendChild(overlay);
    var grid = overlay.querySelector("#mt-grid");
    var headBaia = overlay.querySelector("#mt-baia");
    overlay.querySelector("#mt-cancel").addEventListener("click", encerrar);
    // Toque simples num setor (além de arrastar) — mais confiável no celular.
    grid.addEventListener("click", function (e) {
      var box = e.target.closest(".mov-touch__box");
      if (!box || box.getAttribute("data-setor") === origem) return;
      var info = baiaInfo, destId = box.getAttribute("data-setor"), destNome = box.textContent;
      encerrar();
      confirmar(info, destId, destNome);
    });

    var chip = document.createElement("div");
    chip.className = "mov-touch__chip";
    chip.style.display = "none";
    document.body.appendChild(chip);

    var pressTimer = null, startX = 0, startY = 0, dragging = false;
    var origem = null, baiaInfo = null, alvo = null, origemUnidadeEl = null;

    function setores() {
      // Mover no toque = dentro da MESMA loja. Escopo = a unidade da baia de origem
      // (no mapa completo cada loja é uma .mapa-unidade; no mapa de uma loja só, é a planta).
      var escopo = origemUnidadeEl || planta;
      return Array.prototype.map.call(
        escopo.querySelectorAll(".mapa-setor__baias[data-setor]"),
        function (z) { return { id: z.getAttribute("data-setor"), nome: z.getAttribute("data-setor-nome") }; }
      );
    }

    planta.addEventListener("touchstart", function (e) {
      var b = e.target.closest(".baia[data-baia]");
      if (!b) return;
      var t = e.touches[0];
      startX = t.clientX; startY = t.clientY;
      origemUnidadeEl = b.closest(".mapa-unidade");  // null no mapa de uma loja só
      baiaInfo = {
        id: b.getAttribute("data-baia"), nome: b.getAttribute("data-nome"),
        colab: b.getAttribute("data-colaborador"), patrimonio: b.getAttribute("data-patrimonio"),
        pcstatus: b.getAttribute("data-pcstatus"),
        uni: (origemUnidadeEl && origemUnidadeEl.getAttribute("data-unidade"))
             || mapa.getAttribute("data-origem-unidade") || "",
      };
      origem = b.getAttribute("data-setor");
      pressTimer = setTimeout(function () { iniciar(t); }, 450);
    }, { passive: true });

    planta.addEventListener("touchmove", function (e) {
      if (!dragging && pressTimer) {
        var t = e.touches[0];
        if (Math.abs(t.clientX - startX) > 12 || Math.abs(t.clientY - startY) > 12) {
          clearTimeout(pressTimer); pressTimer = null;  // virou rolagem
        }
      }
    }, { passive: true });

    planta.addEventListener("touchend", function () {
      if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; }
    });

    function posChip(t) { chip.style.left = t.clientX + "px"; chip.style.top = t.clientY + "px"; }

    function limparSelecao() {
      var s = window.getSelection && window.getSelection();
      if (s && s.rangeCount) { try { s.removeAllRanges(); } catch (x) {} }
    }

    function iniciar(t) {
      dragging = true;
      document.body.classList.add("is-arrastando");  // bloqueia seleção de texto
      limparSelecao();
      if (navigator.vibrate) { try { navigator.vibrate(15); } catch (x) {} }
      var uni = origemUnidadeEl ? (origemUnidadeEl.getAttribute("data-unidade") || "") : "";
      headBaia.textContent = "Movendo: " + baiaInfo.nome + (uni ? " · " + uni : "");
      var instr = overlay.querySelector(".mov-touch__head span");
      if (instr) instr.textContent = "Toque no setor de destino (mesma loja) ou arraste até ele";
      grid.innerHTML = "";
      setores().forEach(function (s) {
        var box = document.createElement("div");
        box.className = "mov-touch__box" + (s.id === origem ? " is-origem" : "");
        box.setAttribute("data-setor", s.id);
        box.textContent = s.nome + (s.id === origem ? " (atual)" : "");
        grid.appendChild(box);
      });
      // Opção de mandar p/ OUTRA loja (só quando a baia tem máquina e o mapa permite transferir).
      if (window.__abrirTransferMobile && baiaInfo.patrimonio) {
        var truck = document.createElement("div");
        truck.className = "mov-touch__box mov-touch__box--truck";
        truck.textContent = "Enviar para outra loja";
        truck.addEventListener("click", function () {
          var info = baiaInfo;
          encerrar();
          window.__abrirTransferMobile(info);
        });
        grid.appendChild(truck);
      }
      chip.textContent = baiaInfo.nome;
      chip.style.display = "block";
      posChip(t);
      overlay.classList.add("is-open");
      document.body.style.overflow = "hidden";
      document.addEventListener("touchmove", arrastar, { passive: false });
      document.addEventListener("touchend", soltar);
    }

    function arrastar(e) {
      if (!dragging) return;
      e.preventDefault();
      limparSelecao();  // mata qualquer seleção que tente surgir durante o arraste
      var t = e.touches[0];
      posChip(t);
      chip.style.display = "none";
      var el = document.elementFromPoint(t.clientX, t.clientY);
      chip.style.display = "block";
      var box = el && el.closest(".mov-touch__box");
      grid.querySelectorAll(".mov-touch__box").forEach(function (x) { x.classList.remove("is-over"); });
      alvo = (box && box.hasAttribute("data-setor") && box.getAttribute("data-setor") !== origem) ? box : null;
      if (alvo) alvo.classList.add("is-over");
    }

    function soltar() {
      document.removeEventListener("touchmove", arrastar, { passive: false });
      document.removeEventListener("touchend", soltar);
      dragging = false;
      chip.style.display = "none";
      var dest = alvo;
      if (dest) {
        encerrar();
        confirmar(baiaInfo, dest.getAttribute("data-setor"), dest.textContent);
      }
      // Sem destino arrastado: mantém o overlay aberto para o usuário TOCAR num setor.
    }

    function encerrar() {
      overlay.classList.remove("is-open");
      chip.style.display = "none";
      document.body.style.overflow = "";
      document.body.classList.remove("is-arrastando");
      alvo = null;
    }

    function confirmar(baia, destinoId, destinoNome) {
      var title = document.getElementById("mov-modal-title");
      var msg = document.getElementById("mov-modal-msg");
      var okBtn = document.getElementById("mov-ok");
      var cancelM = document.getElementById("mov-cancel");
      function esc(s) { var d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }
      title.textContent = podeMover ? "Mover baia" : "Solicitar movimentação";
      msg.innerHTML = podeMover
        ? "Mover <b>" + esc(baia.nome) + "</b> para <b>" + esc(destinoNome) + "</b>?"
        : "Solicitar a movimentação de <b>" + esc(baia.nome) + "</b> para <b>" + esc(destinoNome) + "</b>?";
      okBtn.textContent = podeMover ? "Confirmar" : "Enviar solicitação";
      okBtn.disabled = false; okBtn.style.display = ""; cancelM.textContent = "Cancelar";
      modal.classList.add("is-open");
      okBtn.onclick = function () {
        okBtn.disabled = true;
        fetch("/parque/mover-baia/", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": token },
          body: "baia_id=" + encodeURIComponent(baia.id) + "&setor_destino_id=" + encodeURIComponent(destinoId),
        })
          .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
          .then(function (res) {
            if (res.ok && res.j.ok && res.j.status === "aplicada") { window.location.reload(); }
            else {
              title.textContent = (res.ok && res.j.ok) ? "Pronto" : "Não foi possível";
              msg.textContent = (res.ok && res.j.ok) ? (res.j.msg || "") : (res.j.erro || "Erro.");
              okBtn.style.display = "none"; cancelM.textContent = "Fechar";
            }
          })
          .catch(function () { title.textContent = "Não foi possível"; msg.textContent = "Erro de conexão."; okBtn.style.display = "none"; cancelM.textContent = "Fechar"; });
      };
      cancelM.onclick = function () { modal.classList.remove("is-open"); };
    }
  }

  // ---------- Cadastro de computador: pré-visualiza o patrimônio pela loja ----------
  function initPatrimonioPreview() {
    var loja = document.getElementById("id_loja");
    if (!loja) return;
    var box = document.createElement("div");
    box.className = "make-patrimonio-preview";
    box.innerHTML = mkIco('tag')+' Patrimônio que será gerado: <b>—</b>';
    (loja.closest(".form-row") || loja.parentNode).appendChild(box);
    var alvo = box.querySelector("b");
    function atualizar() {
      if (!loja.value) { alvo.textContent = "—"; return; }
      alvo.textContent = "...";
      fetch("/parque/proximo-patrimonio/?unidade=" + encodeURIComponent(loja.value))
        .then(function (r) { return r.json(); })
        .then(function (d) { alvo.textContent = (d.ok && d.patrimonio) ? d.patrimonio : "—"; })
        .catch(function () { alvo.textContent = "—"; });
    }
    loja.addEventListener("change", atualizar);
    atualizar();
  }

  // ---------- Transferência: puxar specs da baia escolhida (origem/destino) ----------
  function initTransferenciaAutofill() {
    if (!window.django || !window.django.jQuery) return;
    var $ = window.django.jQuery;
    var origem = $("#id_baia_origem"), destino = $("#id_baia_destino");
    if (!origem.length && !destino.length) return;

    function preencher(baiaId, campos, campoColab) {
      if (!baiaId) return;
      fetch("/parque/baia-specs/" + baiaId + "/")
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d.ok) return;
          Object.keys(campos).forEach(function (k) {
            var el = document.getElementById(campos[k]);
            if (el && !el.value) el.value = d[k] || "";
          });
          var cf = document.getElementById(campoColab);
          if (cf && !cf.value) cf.value = d.colaborador || "";
        });
    }
    origem.on("change", function () {
      preencher(this.value, {
        so: "id_so_antigo", cpu: "id_processador_antigo", placa: "id_placa_mae_antigo",
        ram: "id_ram_antigo", disco: "id_armazenamento_antigo",
      }, "id_colaborador_saida");
    });
    destino.on("change", function () {
      preencher(this.value, {
        so: "id_so_novo", cpu: "id_processador_novo", placa: "id_placa_mae_novo",
        ram: "id_ram_novo", disco: "id_armazenamento_novo",
      }, "id_colaborador_destino");
    });
  }

  // ---------- Esconde badges vazios/zero no menu lateral ----------
  function initSidebarBadges() {
    var sidebar = document.getElementById("nav-sidebar-inner");
    if (!sidebar) return;
    sidebar.querySelectorAll("span.uppercase").forEach(function (el) {
      var t = (el.textContent || "").trim();
      if (t === "" || t === "0") el.style.display = "none";
    });
  }

  // ---------- A busca da gaveta vira LUPA que abre ----------
  // Pedido do dono: "isso aqui podia virar uma lupa que quando clica abre um
  // campo de pesquisa dinâmico". Fechada, a busca ocupa uma faixa de 48px no
  // topo da gaveta para ficar esperando; como lupa, devolve essa faixa aos
  // itens de menu e só cresce quando alguém vai buscar.
  //
  // Nada é movido nem recriado: o `#nav-filter`, o `searchDropdown()` do Alpine
  // e o `hx-get` continuam onde estão, com os mesmos ganchos. O que muda é uma
  // CLASSE na casca, e o CSS faz o resto (make-m3.css §19.21). Depois do que
  // aconteceu ao mover o bloco do usuário — o Alpine destrói o estado da
  // subárvore que sai do DOM — mexer só em classe é a escolha consciente aqui.
  function initBuscaGaveta() {
    var caixa = document.querySelector("#nav-sidebar .mksrch-box");
    var campo = document.getElementById("nav-filter");
    if (!caixa || !campo || caixa.dataset.mkLupa) return;
    caixa.dataset.mkLupa = "1";

    function abrir(on) {
      caixa.classList.toggle("mksrch--aberta", on);
      caixa.classList.toggle("mksrch--lupa", !on);
      if (on) campo.focus();
    }
    abrir(false);

    caixa.addEventListener("click", function () {
      if (!caixa.classList.contains("mksrch--aberta")) abrir(true);
    });
    // Fecha ao sair vazia: se há texto, o resultado ainda interessa.
    campo.addEventListener("blur", function () {
      setTimeout(function () {
        if (!campo.value.trim() && !caixa.contains(document.activeElement)) abrir(false);
      }, 120);
    });
    campo.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { campo.value = ""; abrir(false); }
    });
    // Atalho: "/" abre a busca de qualquer lugar, como em editor de código.
    document.addEventListener("keydown", function (e) {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      var a = document.activeElement;
      var digitando = a && (a.tagName === "INPUT" || a.tagName === "TEXTAREA" || a.isContentEditable);
      if (digitando) return;
      e.preventDefault();
      abrir(true);
    });
  }

  // ---------- O avatar sobe para a barra do topo — DESLIGADA ----------
  //
  // NÃO RELIGUE sem resolver o problema abaixo. Está na referência de layout
  // que o dono mandou (avatar redondo com chevron no canto direito da barra) e
  // foi tentado: o avatar aparece no lugar certo, mas o MENU DA CONTA para de
  // abrir — e é o único caminho para trocar de tema, trocar a senha e SAIR.
  //
  // Causa: `appendChild` para outro pai é uma REMOÇÃO seguida de inserção. O
  // observador do Alpine vê a remoção e destrói o estado daquela subárvore;
  // depois vê a inserção e monta de novo. O objeto de dados volta a existir (dá
  // para ler e escrever `openUserLinks` por fora), mas o efeito do `x-show`
  // não volta a rodar — o menu fica com `display: none` para sempre.
  // `Alpine.destroyTree()` + `Alpine.initTree()` na subárvore movida também não
  // recupera; testado, sem erro e sem efeito.
  //
  // Caminho viável, se o layout voltar à mesa: parar de depender do Alpine
  // neste menu e controlá-lo por classe própria, como foi feito com a gaveta
  // (make-m3.css §19.12). Aí mover o nó deixa de ter consequência. Não foi
  // feito agora porque o mesmo bloco carrega o seletor de tema, que também é
  // Alpine, e trocar tudo isso é uma tarefa por si.
  //
  // O bloco é MOVIDO inteiro, com o `x-data` dele. Isso é essencial: dentro
  // desse bloco vive o único caminho para trocar de tema, trocar a senha e
  // SAIR. Mover só o visual e deixar o estado atrás quebraria o menu; mover a
  // raiz do `x-data` leva o Alpine junto e o menu continua abrindo.
  //
  // A ARMADILHA, e por isso o marcador: as regras de gaveta endereçam os blocos
  // por POSIÇÃO (`#nav-sidebar-inner > div:nth-of-type(n)`). Tirar o bloco do
  // meio faria a BUSCA virar o nº 2 e herdar o estilo do cartão de usuário — e
  // a régua de 76px passaria a esconder o menu inteiro em vez da busca. O
  // marcador vazio ocupa o índice e nada disso acontece.
  function initAvatarNoTopo() {
    var bloco = document.querySelector("#nav-sidebar-inner > div[x-data*='openUserLinks']");
    var lado = document.querySelector("#main > header.make-header .mkhdr__side");
    if (!bloco || !lado || bloco.dataset.mkNoTopo) return;
    bloco.dataset.mkNoTopo = "1";

    var marcador = document.createElement("div");
    marcador.className = "mknu-vaga";
    marcador.setAttribute("aria-hidden", "true");
    bloco.parentNode.insertBefore(marcador, bloco);

    bloco.classList.add("mknu--topo");
    lado.appendChild(bloco);
  }

  // ---------- Um botão "Filtrar", com os filtros num popup de fichas ----------
  // Pedido do dono: "melhor colocar uma opção ali de filtrar e aparecer um menu
  // circular pra selecionar". Os dois seletores soltos (UNIDADE e SETOR) saem da
  // linha e passam a viver atrás de UM botão; dentro do popup, cada opção é uma
  // ficha arredondada em vez de linha de lista.
  //
  // Sobre "circular": um menu em ANEL (opções dispostas em círculo em volta do
  // botão) só funciona com até uns seis itens, e a lista de setores passa disso
  // — viraria um carrossel ilegível. Então a forma é popup com fichas
  // ARREDONDADAS, que é o que dá para varrer com o olho e escala com a lista.
  // Se você quiser o anel de verdade mesmo assim, é meia hora de trabalho.
  //
  // Os filtros NÃO são reescritos: os nós existentes são MOVIDOS para dentro do
  // popup. Isso é seguro aqui porque `initFiltroDropdowns` liga os ouvintes
  // DIRETO em cada elemento, e ouvinte ligado no próprio nó viaja com ele. (Não
  // seria seguro com Alpine, que destrói o estado do que sai do DOM — foi o que
  // me quebrou o menu da conta.)

  // ---------- Calendário de intervalo do filtro ----------
  //
  // Componente próprio, sem biblioteca: grade do mês, um clique marca o
  // início, o segundo marca o fim. Quem envia o valor continuam sendo os dois
  // <input type="date"> do formulário — o calendário só escreve neles. Assim,
  // sem JS, a tela cai nos campos nativos e nada se perde.
  function initCalendarioFiltro() {
    document.querySelectorAll("[data-mkcal]").forEach(montarCalendario);
  }

  // Publicado de proposito, pelo mesmo motivo do `mkAbrirZoom`: telas que
  // desenham o proprio conteudo por JS (o Mural) nascem DEPOIS deste init e
  // nunca seriam varridas por ele. Sem isto, elas teriam de escrever um
  // segundo calendario — e a casa voltaria a ter dois jeitos de perguntar a
  // mesma coisa. Recebe o host `[data-mkcal]`; e' idempotente (o proprio
  // montarCalendario ignora host ja' montado).
  window.mkMontarCalendario = montarCalendario;

  var MK_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
                  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
  var MK_DIAS = ["D", "S", "T", "Q", "Q", "S", "S"];

  function mkISO(d) {
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
           "-" + String(d.getDate()).padStart(2, "0");
  }
  function mkDeISO(t) {
    if (!t) return null;
    var p = String(t).split("-");
    if (p.length !== 3) return null;
    var d = new Date(+p[0], +p[1] - 1, +p[2]);
    return isNaN(d) ? null : d;
  }

  function montarCalendario(host) {
    if (host.dataset.mkCalPronto) return;
    host.dataset.mkCalPronto = "1";

    var form = host.closest("form");
    var iDesde = form && form.querySelector('input[name="vence_desde"]');
    var iAte = form && form.querySelector('input[name="vence_ate"]');

    var desde = mkDeISO(host.dataset.desde);
    var ate = mkDeISO(host.dataset.ate);
    var hoje = mkDeISO(host.dataset.hoje) || new Date();
    var vista = new Date((desde || hoje).getFullYear(), (desde || hoje).getMonth(), 1);

    // O `.mkcal__cab` e' a manchete do picker do M3: o periodo escolhido em
    // letra grande, e o lugar onde o "Limpar data" (criado pelo
    // initFiltrarPopup) e' encaixado. Antes o resumo era uma linha de texto
    // pequena DEPOIS da grade, onde ninguem lia.
    host.innerHTML =
      '<div class="mkcal__cab">' +
        '<p class="mkcal__resumo" data-mkcal-resumo></p>' +
        '<span class="mkcal__slot" data-mkcal-slot></span>' +
      '</div>' +
      '<div class="mkcal__topo">' +
        '<button type="button" class="mkcal__nav" data-mkcal-ant aria-label="Mês anterior">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg>' +
        '</button>' +
        '<span class="mkcal__mes" data-mkcal-mes></span>' +
        '<button type="button" class="mkcal__nav" data-mkcal-prox aria-label="Próximo mês">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>' +
        '</button>' +
      '</div>' +
      '<div class="mkcal__sem">' + MK_DIAS.map(function (d) {
        return '<span>' + d + '</span>';
      }).join("") + '</div>' +
      '<div class="mkcal__grade" data-mkcal-grade></div>';

    var elMes = host.querySelector("[data-mkcal-mes]");
    var elGrade = host.querySelector("[data-mkcal-grade]");
    var elResumo = host.querySelector("[data-mkcal-resumo]");

    function escrever() {
      if (iDesde) iDesde.value = desde ? mkISO(desde) : "";
      if (iAte) iAte.value = ate ? mkISO(ate) : "";
    }

    function fmt(d) {
      return String(d.getDate()).padStart(2, "0") + "/" +
             String(d.getMonth() + 1).padStart(2, "0") + "/" + d.getFullYear();
    }

    function pintar() {
      elMes.textContent = MK_MESES[vista.getMonth()] + " " + vista.getFullYear();
      var primeiro = new Date(vista.getFullYear(), vista.getMonth(), 1);
      var inicio = new Date(primeiro);
      inicio.setDate(1 - primeiro.getDay());            // começa no domingo
      var html = "";
      for (var i = 0; i < 42; i++) {
        var d = new Date(inicio.getFullYear(), inicio.getMonth(), inicio.getDate() + i);
        var iso = mkISO(d);

        // DUAS camadas, e e' isso que faz a trilha do intervalo ser continua:
        // a CELULA pinta a faixa de ponta a ponta (sem gap, com as pontas
        // arredondadas) e o BOTAO e' o alvo redondo de 40px em cima dela.
        // Com um elemento so, cada dia virava um retangulo separado — era o
        // calendario apertado que o dono reprovou.
        var cel = ["mkcal__cel"];
        var bot = ["mkcal__d"];
        var ehIni = desde && iso === mkISO(desde);
        var ehFim = ate && iso === mkISO(ate);
        if (d.getMonth() !== vista.getMonth()) bot.push("mkcal__d--fora");
        if (iso === mkISO(hoje)) bot.push("mkcal__d--hoje");
        if (ehIni || ehFim) bot.push("mkcal__d--sel");
        if (ehIni && ehFim) cel.push("mkcal__cel--so");
        else if (ehIni) cel.push(ate ? "mkcal__cel--ini" : "mkcal__cel--so");
        else if (ehFim) cel.push("mkcal__cel--fim");
        else if (desde && ate && d > desde && d < ate) cel.push("mkcal__cel--meio");

        // `--i` alimenta o atraso da cascata no CSS (os dias caem em onda
        // quando o calendario aparece). Sem indice, a alternativa era 42
        // regras `:nth-child`.
        html += '<div class="' + cel.join(" ") + '" style="--i:' + i + '">' +
                '<button type="button" class="' + bot.join(" ") + '" data-iso="' + iso + '">' +
                d.getDate() + '</button></div>';
      }
      elGrade.innerHTML = html;
      // Manchete: o periodo em letra grande, com uma etiqueta em cima. E' a
      // unica linha do passo que responde "o que esta escolhido agora".
      //
      // FORMATO CURTO, de proposito. Com `dd/mm/aaaa` nas duas pontas dava 23
      // caracteres em corpo 22 — cerca de 250px — e ao lado dele mora o
      // "Limpar data": num painel de 356px a linha quebrava em duas. O ano
      // sai porque ele ja esta no cabecalho do mes, uma linha abaixo; quando
      // o intervalo cruza o ano, volta (senao 28/12 a 03/01 mentiria).
      function curto(d) {
        return String(d.getDate()).padStart(2, "0") + "/" +
               String(d.getMonth() + 1).padStart(2, "0");
      }
      var mesmoAno = !(desde && ate) || desde.getFullYear() === ate.getFullYear();
      function pt(d) { return mesmoAno ? curto(d) : fmt(d); }

      var titulo, dica;
      if (desde && ate) { titulo = pt(desde) + " – " + pt(ate); dica = "Período escolhido"; }
      else if (desde) { titulo = pt(desde) + " – …"; dica = "Agora escolha o fim"; }
      else { titulo = "Qualquer data"; dica = "Toque no primeiro dia"; }
      elResumo.innerHTML = "<small>" + dica + "</small>" + titulo;
    }

    host.querySelector("[data-mkcal-ant]").addEventListener("click", function () {
      vista = new Date(vista.getFullYear(), vista.getMonth() - 1, 1); pintar();
    });
    host.querySelector("[data-mkcal-prox]").addEventListener("click", function () {
      vista = new Date(vista.getFullYear(), vista.getMonth() + 1, 1); pintar();
    });

    elGrade.addEventListener("click", function (e) {
      var b = e.target.closest("[data-iso]");
      if (!b) return;
      var d = mkDeISO(b.dataset.iso);
      var iso = b.dataset.iso;

      // ------------------------------------------------------------------
      // DESMARCAR. A primeira versão não tinha este ramo, e era a queixa do
      // usuário: escolhida a data, não havia mais como voltar a "sem data" —
      // todo clique ou reiniciava o intervalo ou o fechava. A única saída era
      // a ficha "Qualquer data", que ninguém lê como "limpar".
      //
      // Agora tocar de novo numa PONTA marcada apaga aquela ponta: dois
      // cliques nas duas pontas devolvem o calendário ao vazio, sem aplicar
      // nada e sem sair do painel.
      // ------------------------------------------------------------------
      if (ate && iso === mkISO(ate)) {
        ate = null;
        escrever(); pintar();
        return;
      }
      if (desde && iso === mkISO(desde)) {
        // Com o fim marcado, remover o início promove o fim a data única
        // ("a partir de"); sem fim, o calendário volta ao vazio.
        desde = ate || null;
        ate = null;
        escrever(); pintar();
        return;
      }

      // Sem início, ou já com intervalo fechado, ou clique antes do início:
      // começa de novo. Senão, fecha o intervalo.
      if (!desde || (desde && ate) || d < desde) { desde = d; ate = null; }
      else { ate = d; }
      escrever();
      pintar();
    });

    // Deixa o componente acessível para as fichas de atalho ("15 dias" etc.)
    // e para o botão "Limpar data" do painel.
    host.mkCal = {
      definir: function (isoDesde, isoAte) {
        desde = mkDeISO(isoDesde);
        ate = mkDeISO(isoAte);
        if (desde) vista = new Date(desde.getFullYear(), desde.getMonth(), 1);
        escrever();
        pintar();
      },
      limpar: function () {
        desde = null; ate = null;
        escrever();
        pintar();
      },
      vazio: function () { return !desde && !ate; }
    };

    pintar();
  }


  // ---------- Barra do topo vazia: some ----------
  //
  // Depois que o "?" e o sino foram para o Assistente, em muitas telas a barra
  // do topo ficou sem nada dentro: uma faixa de 64px de puro espaço entre o
  // alto da janela e o conteúdo. Em vez de chutar uma altura no CSS, aqui a
  // pergunta é objetiva — sobrou algum controle VISÍVEL na barra? Se não,
  // marca o body e o CSS tira a faixa. Em tela estreita o botão da gaveta
  // aparece, então a barra continua; e nas telas em que o "voltar" subiu para
  // ela (initVoltarNoTopo), também.
  function initTopoVazio() {
    var barra = document.querySelector("#main > header.make-header");
    if (!barra) return;

    function medir() {
      var controles = barra.querySelectorAll(
        'a, button, [role="button"], input, select, h1:not(.mkhdr__h1--cedido)');
      var vivo = false;
      controles.forEach(function (c) {
        if (vivo) return;
        if (c.hasAttribute("hidden") || c.offsetParent === null) return;
        var r = c.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) vivo = true;
      });
      document.body.classList.toggle("mk-topo-vazio", !vivo);
    }

    medir();
    // O conteúdo da barra muda depois do carregamento (o "voltar" sobe, a
    // gaveta abre/fecha, o tema troca): remede quando isso acontecer.
    new MutationObserver(medir).observe(barra, { childList: true, subtree: true, attributes: true });
    window.addEventListener("resize", medir);
  }



  // ---------- "Voltar" só nas subtelas ----------
  //
  // Decisão do dono: "tira todos os botões de voltar e sobe o conteúdo das
  // telas que são acessadas diretamente pelo menu. As subtelas podem ter o
  // botão". Se a tela está no menu, ela é destino de primeiro nível: não há de
  // onde voltar.
  //
  // Quem responde "esta tela está no menu?" é o próprio menu — comparamos o
  // caminho atual com o href de cada item da gaveta, em vez de manter uma
  // lista em JS para desencontrar da navegação de verdade (settings/base.py).
  function initVoltarSoNasSubtelas() {
    var caminho = mkNormalizarCaminho(location.pathname);
    var noMenu = false;
    document.querySelectorAll("#nav-sidebar-apps ol li a[href]").forEach(function (a) {
      if (noMenu) return;
      var href = a.getAttribute("href") || "";
      if (href.charAt(0) !== "/") return;
      if (mkNormalizarCaminho(href.split("?")[0]) === caminho) noMenu = true;
    });
    if (!noMenu) return;

    document.body.classList.add("mk-sem-voltar");
    document.querySelectorAll("[data-mk-voltar]").forEach(function (el) {
      var caixa = el.closest(".mkpro-head__actions");
      el.remove();
      if (caixa && !caixa.children.length) caixa.remove();
    });
    var slot = document.getElementById("mk-voltar");
    if (slot) { slot.hidden = true; slot.removeAttribute("href"); }
  }

  function mkNormalizarCaminho(c) {
    c = (c || "/").split("#")[0].split("?")[0];
    if (c.length > 1 && c.charAt(c.length - 1) !== "/") c += "/";
    return c;
  }

  // ---------- Tema: os três ícones, com o ATIVO marcado ----------
  //
  // Histórico curto: o unfold põe três links (Claro / Escuro / Sistema) e não
  // marca qual está valendo — o dono reclamou que não dava para saber o tema.
  // Tentei trocar por um interruptor "Tema escuro"; ele reprovou ("tira essa
  // merda de Tema escuro e deixa só os ícones"). Então os ícones ficam, e o
  // que faltava é o que esta função faz: MARCAR o ativo.
  //
  // A escolha vive no localStorage `adminTheme` (Alpine.$persist do unfold,
  // valor entre aspas), com 'auto' significando "seguir o sistema".
  function initTemaIcones() {
    var menu = document.querySelector("#nav-sidebar .mknu-menu");
    if (!menu || menu.dataset.mkTemaObs) return;
    menu.dataset.mkTemaObs = "1";

    function escolhido() {
      var v = "";
      try { v = (localStorage.getItem("adminTheme") || "").replace(/"/g, ""); }
      catch (e) { v = ""; }
      if (v === "light" || v === "dark" || v === "auto") return v;
      return document.documentElement.classList.contains("dark") ? "dark" : "light";
    }

    function pintar() {
      var atual = escolhido();
      // O unfold liga o clique por Alpine (`x-on:click`) ou por `onclick`,
      // dependendo da versão — procurar só `[onclick]` achava ZERO link e a
      // marcação nunca aparecia. Aqui lemos os três jeitos possíveis.
      menu.querySelectorAll("a, button").forEach(function (el) {
        var on = el.getAttribute("onclick") ||
                 el.getAttribute("x-on:click") ||
                 el.getAttribute("@click") || "";
        if (on.indexOf("switchTheme") < 0) return;
        var qual = on.indexOf("dark") >= 0 ? "dark"
                 : on.indexOf("light") >= 0 ? "light"
                 : on.indexOf("auto") >= 0 ? "auto" : "";
        el.classList.add("mktema-ic");
        el.classList.toggle("is-sel", qual === atual);
        el.setAttribute("aria-pressed", qual === atual ? "true" : "false");
        el.setAttribute("title",
          qual === "light" ? "Tema claro" : qual === "dark" ? "Tema escuro" : "Seguir o sistema");
      });
      // "Ver site" sai do menu — pedido do dono.
      menu.querySelectorAll("a").forEach(function (a) {
        if ((a.textContent || "").trim().toLowerCase() === "ver site") a.remove();
      });
    }

    pintar();
    menu.addEventListener("click", function () { setTimeout(pintar, 30); });
    new MutationObserver(pintar).observe(menu, { childList: true, subtree: true });
    new MutationObserver(pintar).observe(document.documentElement,
      { attributes: true, attributeFilter: ["class"] });
  }

  // ---------- Agenda do topo: calendário + avisos ----------
  //
  // O objeto pequeno (dia, data e hora) fica sempre visível na barra. O painel
  // abre em duas colunas: avisos/solicitações à esquerda (o bloco que vinha do
  // sino, adotado de `_avisos.html`) e o mês à direita, com ponto nos dias que
  // têm evento e a lista do dia escolhido embaixo.
  //
  // Os eventos vêm de /agenda/eventos/?ano&mes SÓ quando o painel abre — a
  // barra aparece em toda tela e não pode custar consulta antes disso.
  function initAgendaTopo() {
    var raiz = document.getElementById("mk-agenda");
    if (!raiz || raiz.dataset.mkPronto) return;
    raiz.dataset.mkPronto = "1";

    var btn = document.getElementById("mk-agenda-btn");
    var pop = document.getElementById("mk-agenda-pop");
    var elDia = document.getElementById("mk-agenda-dia");
    var elData = document.getElementById("mk-agenda-data");
    var elHora = document.getElementById("mk-agenda-hora");
    var elMes = document.getElementById("mk-agenda-mes");
    var elGrade = document.getElementById("mk-agenda-grade");
    var elLista = document.getElementById("mk-agenda-dia-lista");
    var elDiaT = document.getElementById("mk-agenda-dia-t");
    var elHojeL = document.getElementById("mk-agenda-hoje-lbl");
    var elHojeD = document.getElementById("mk-agenda-hoje-data");
    var elN = document.getElementById("mk-agenda-n");
    var elAvisos = document.getElementById("mk-agenda-avisos");
    if (!btn || !pop) return;

    var SEM = ["domingo", "segunda-feira", "terça-feira", "quarta-feira",
               "quinta-feira", "sexta-feira", "sábado"];
    var MES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
               "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

    // --- o objeto pequeno: dia, data curta e relógio ---
    function relogio() {
      var d = new Date();
      // "sex, 04 set" + "15:18" — o formato da referência, em pt-BR.
      if (elData) elData.textContent = SEM[d.getDay()].slice(0, 3) + ", " +
        String(d.getDate()).padStart(2, "0") + " " + MES[d.getMonth()].slice(0, 3);
      if (elHora) elHora.textContent =
        String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
    }
    relogio();
    setInterval(relogio, 30000);

    // --- adota as MENSAGENS da página (o "salvo com sucesso" e afins) ---
    //
    // Decisão do dono: nada de faixa de notificação dentro da tela; tudo vem
    // para esta área. O parcial `unfold/helpers/messages.html` entrega as
    // mensagens escondidas em `#mk-msgs-fonte` e aqui elas viram cartão na
    // coluna de avisos, com o ponto aceso no objeto do topo.
    var msgs = document.getElementById("mk-msgs-fonte");
    var nMsgs = 0;
    var temErro = false;
    if (msgs && elAvisos) {
      var itens = msgs.querySelectorAll(".mkmsg");
      nMsgs = itens.length;
      itens.forEach(function (m) {
        var nivel = m.dataset.nivel || "info";
        if (nivel === "error" || nivel === "warning") temErro = true;
        var cartao = document.createElement("div");
        cartao.className = "mkag__msg mkag__msg--" + nivel;
        cartao.textContent = m.textContent.trim();
        elAvisos.insertBefore(cartao, elAvisos.firstChild);   // o novo em cima
      });
      msgs.remove();
    }

    // --- adota a FAIXA DO AGENTE ---
    //
    // Ela nao e uma `message` do Django: e um aviso permanente que o header
    // desenhava como tarja no alto de TODA tela ("coleta de desempenho nao
    // detectada nesta maquina"). O dono foi categorico: notificacao nenhuma
    // fica na pagina. O no e movido inteiro, entao o botao "Baixar agente" e o
    // "x" de dispensar continuam funcionando (os ouvintes estao no proprio
    // elemento e viajam com ele).
    var faixaAgente = document.getElementById("agente-aviso");
    if (faixaAgente && elAvisos) {
      elAvisos.appendChild(faixaAgente);
      // Ela vem `hidden` do template para nao pintar solta no alto da pagina
      // antes desta adocao. Quem revela e' quem adota — e so' aqui dentro.
      // O `display:none` inline vem de "dispensar" (sessionStorage, no proprio
      // header.html): nesse caso nao acende ponto nem revela nada.
      if (faixaAgente.style.display !== "none") {
        faixaAgente.hidden = false;
        raiz.classList.add("mkag--tem");
        if (elN) elN.hidden = false;
      }
    }

    // --- adota os avisos que vinham do sino ---
    var fonte = document.getElementById("mk-avisos-fonte");
    if (fonte && elAvisos) {
      var naoLidas = parseInt(fonte.dataset.naoLidas || "0", 10) || 0;
      while (fonte.firstChild) elAvisos.appendChild(fonte.firstChild);
      fonte.remove();
      if (naoLidas && elN) {
        elN.hidden = false;                     // ponto, não contador
        elN.setAttribute("title", naoLidas + (naoLidas > 1 ? " avisos não lidos" : " aviso não lido"));
        raiz.classList.add("mkag--tem");
      }
    }
    // Mensagem da página também acende o ponto — senão o retorno da ação
    // ("protocolo gerado") ficaria invisível.
    if (nMsgs && elN) {
      elN.hidden = false;
      raiz.classList.add("mkag--tem");
      if (!elN.getAttribute("title")) elN.setAttribute("title", "Há avisos novos");
    }

    // --- estado do calendário ---
    var hojeISO = "";
    var agora = new Date();
    var vista = new Date(agora.getFullYear(), agora.getMonth(), 1);
    var dados = { por_dia: {}, eventos: [], hoje_eventos: [] };
    var diaSel = null;

    function iso(d) {
      return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
             "-" + String(d.getDate()).padStart(2, "0");
    }
    function fmtBR(t) {
      var p = String(t).split("-");
      return p.length === 3 ? p[2] + "/" + p[1] + "/" + p[0] : t;
    }

    function pintarGrade() {
      elMes.textContent = MES[vista.getMonth()] + " " + vista.getFullYear();
      var primeiro = new Date(vista.getFullYear(), vista.getMonth(), 1);
      var ini = new Date(primeiro);
      ini.setDate(1 - primeiro.getDay());
      var html = "";
      for (var i = 0; i < 42; i++) {
        var d = new Date(ini.getFullYear(), ini.getMonth(), ini.getDate() + i);
        var k = iso(d);
        var cls = ["mkag__d"];
        if (d.getMonth() !== vista.getMonth()) cls.push("mkag__d--fora");
        if (k === hojeISO) cls.push("mkag__d--hoje");
        if (k === diaSel) cls.push("mkag__d--sel");
        if (dados.por_dia[k]) cls.push("mkag__d--tem");
        html += '<button type="button" class="' + cls.join(" ") + '" data-iso="' + k + '">' +
                d.getDate() + "</button>";
      }
      elGrade.innerHTML = html;
    }

    var ICO = {
      preventiva: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
      solicitacao: '<path d="M4 8h16M16 4l4 4-4 4"/><path d="M20 16H4M8 12l-4 4 4 4"/>',
      chamado: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
      feito: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/>'
    };

    function esc(t) {
      return String(t == null ? "" : t)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function pintarLista() {
      var alvo = diaSel || hojeISO;
      var itens = dados.eventos.filter(function (e) { return e.dia === alvo; });
      // O escopo entra no título: sem isso, quem vê só a própria loja acha que
      // está vendo tudo, e quem não vê nada não descobre o motivo.
      var escopo = dados.escopo ? " · " + dados.escopo : "";
      elDiaT.textContent = (alvo === hojeISO ? "Hoje" : fmtBR(alvo)) + escopo;
      if (!itens.length) {
        elLista.innerHTML = '<p class="mkag__vazio">Nada marcado neste dia.</p>';
        return;
      }
      elLista.innerHTML = itens.map(function (e) {
        var tag = e.url ? "a" : "div";
        return "<" + tag + ' class="mkag__ev mkag__ev--' + esc(e.tipo) + '"' +
          (e.url ? ' href="' + esc(e.url) + '"' : "") + ">" +
          '<span class="mkag__ev-ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
          'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
          (ICO[e.tipo] || ICO.chamado) + "</svg></span>" +
          '<span class="mkag__ev-txt"><b>' + esc(e.titulo) + "</b>" +
          (e.onde ? "<em>" + esc(e.onde) + "</em>" : "") + "</span>" +
          "</" + tag + ">";
      }).join("");
    }

    var buscando = false;
    function buscar() {
      if (buscando) return;
      buscando = true;
      elGrade.classList.add("is-carregando");
      fetch("/agenda/eventos/?ano=" + vista.getFullYear() + "&mes=" + (vista.getMonth() + 1),
            { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (d) {
          dados = d;
          hojeISO = d.hoje;
          var p = String(d.hoje).split("-");
          var h = new Date(+p[0], +p[1] - 1, +p[2]);
          if (elHojeL) elHojeL.textContent = SEM[h.getDay()];
          if (elHojeD) elHojeD.textContent =
            String(h.getDate()) + " de " + MES[h.getMonth()] + " de " + h.getFullYear();
          pintarGrade();
          pintarLista();
        })
        .catch(function () {
          elLista.innerHTML = '<p class="mkag__vazio">Não foi possível carregar a agenda agora.</p>';
        })
        .then(function () {
          buscando = false;
          elGrade.classList.remove("is-carregando");
        });
    }

    function abrir(on) {
      pop.hidden = !on;
      btn.setAttribute("aria-expanded", on ? "true" : "false");
      raiz.classList.toggle("mkag--aberto", on);
      if (on) buscar();
    }

    // POR QUE UMA BANDEIRA, E NÃO `closest("#mk-agenda")` NO DOCUMENTO
    //
    // O dono clicava num dia e o painel FECHAVA. O culpado é a ordem: o
    // clique no dia repinta a grade (`elGrade.innerHTML = ...`), então quando
    // o clique termina de subir até o `document` o botão clicado JÁ NÃO ESTÁ
    // na página — `e.target.closest("#mk-agenda")` devolve null e o painel se
    // fechava como se o clique fosse fora dele.
    //
    // Marcar na fase de CAPTURA resolve na raiz: ali o alvo ainda está no
    // documento, e vale para qualquer parte do painel que se redesenhe depois
    // (dias, avisos, lista do dia).
    var cliqueDentro = false;
    raiz.addEventListener("click", function () { cliqueDentro = true; }, true);

    btn.addEventListener("click", function () { abrir(pop.hidden); });

    // Erro de ação abre o painel sozinho: a regra é notificação só no topo,
    // mas resposta a um envio que falhou não pode depender de a pessoa
    // adivinhar que precisa clicar aqui.
    if (temErro) setTimeout(function () { abrir(true); }, 250);
    document.addEventListener("click", function (e) {
      var dentro = cliqueDentro;
      cliqueDentro = false;
      if (pop.hidden || dentro) return;
      if (e.target.closest && e.target.closest("#mk-agenda")) return;
      abrir(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !pop.hidden) { abrir(false); btn.focus(); }
    });
    var bAnt = document.getElementById("mk-agenda-ant");
    var bProx = document.getElementById("mk-agenda-prox");
    if (bAnt) bAnt.addEventListener("click", function () {
      vista = new Date(vista.getFullYear(), vista.getMonth() - 1, 1); diaSel = null; buscar();
    });
    if (bProx) bProx.addEventListener("click", function () {
      vista = new Date(vista.getFullYear(), vista.getMonth() + 1, 1); diaSel = null; buscar();
    });
    elGrade.addEventListener("click", function (e) {
      var b = e.target.closest("[data-iso]");
      if (!b) return;
      diaSel = b.dataset.iso;
      pintarGrade();
      pintarLista();
    });
  }


  // ---------- Marca as telas de formulário do admin ----------
  //
  // O CSS precisa saber que ESTA tela é um formulário de adicionar/editar para
  // esconder o "+" da barra (o dono achou o botão numa tela de adicionar e
  // notou o óbvio: dá para entrar em adicionar dentro de adicionar, sem fim).
  // O unfold não põe classe nenhuma no <body> para isso, e CSS não lê URL —
  // então a marca vem daqui.
  function initFormularioAdmin() {
    var p = location.pathname;
    var ehAdd = /\/add\/?$/.test(p);
    var ehChange = /\/\d+\/change\/?$/.test(p) || /\/change\/?$/.test(p);
    if (ehAdd || ehChange) {
      document.body.classList.add("mk-form-admin");
      // DUAS marcas, não uma. O "+" só é problema na tela de ADICIONAR (era
      // possível entrar em adicionar dentro de adicionar, sem fim — foi o que
      // o dono apontou). Na tela de EDITAR o mesmo botão é atalho legítimo
      // para cadastrar o próximo, e o template do unfold o mantém de
      // propósito: esconder lá era o CSS contrariando o template.
      document.body.classList.add(ehAdd ? "mk-form-add" : "mk-form-change");
    }
  }


  // ---------- Fonte dos gráficos ----------
  //
  // O Chart.js desenha o texto dele no CANVAS com a fonte padrão da
  // biblioteca (uma pilha que cai em serifada no Windows). Resultado: rótulo
  // de legenda e número de eixo saíam com letra diferente do resto do
  // sistema — o dono viu na hora ("esses textos aí com fontes diferentes").
  // CSS não alcança texto dentro de canvas; a troca tem de ser no default da
  // biblioteca, e os gráficos já montados precisam de `update()`.
  function initFonteDosGraficos() {
    var tentativas = 0;
    function aplicar() {
      if (!window.Chart) {
        if (++tentativas < 40) setTimeout(aplicar, 120);
        return;
      }
      var C = window.Chart;
      var raiz = getComputedStyle(document.documentElement);
      // PILHA SIMPLES, de propósito. O texto do gráfico é desenhado no
      // CANVAS, e `ctx.font` só aceita um atalho CSS de fonte válido: se a
      // pilha do body traz nomes que o canvas não parseia, o Chrome DESCARTA
      // o valor e volta para a fonte padrão dele — serifada. Era isso que
      // aparecia na legenda e no tooltip.
      var fonte = "Figtree, sans-serif";
      var tinta = (raiz.getPropertyValue("--md-on-surface-variant") || "").trim() || "#6d7a71";
      try {
        C.defaults.font.family = fonte;
        C.defaults.font.size = 11.5;
        C.defaults.font.weight = "500";
        C.defaults.color = tinta;
      } catch (e) { return; }
      // Redesenha o que já estava na tela com a fonte antiga.
      document.querySelectorAll("canvas").forEach(function (cv) {
        var ch = C.getChart ? C.getChart(cv) : null;
        if (ch) { try { ch.update("none"); } catch (e) {} }
      });
    }
    aplicar();
  }


  // ---------- Novo setor em popup ----------
  //
  // Os quatro botoes de criar setor apontavam para o formulario do admin
  // (`/admin/parque/setor/add/?unidade=N`): trocava de tela para digitar dois
  // campos e voltava por um "voltar". O dono chamou de loucura, com razao.
  //
  // Aqui o clique e interceptado e o `<dialog>` de `_setor_novo.html` abre com
  // a unidade daquele link ja escolhida. Sem o dialogo na pagina (ou sem JS),
  // o link continua funcionando como antes — o admin segue sendo a rota de
  // reserva, nao um beco sem saida.
  function initSetorPopup() {
    var dlg = document.getElementById("stn-dlg");
    if (!dlg || dlg.dataset.mkPronto) return;
    dlg.dataset.mkPronto = "1";

    var sel = dlg.querySelector("#stn-unidade");
    var nome = dlg.querySelector("#stn-nome");

    document.addEventListener("click", function (e) {
      var a = e.target.closest('a[href*="/admin/parque/setor/add/"]');
      if (!a) return;
      e.preventDefault();
      // `?unidade=N` do link vira a opcao marcada no popup.
      var q = (a.getAttribute("href") || "").split("?")[1] || "";
      var uni = new URLSearchParams(q).get("unidade");
      if (uni && sel) {
        var achou = false;
        Array.prototype.forEach.call(sel.options, function (o) {
          if (o.value === String(uni)) { o.selected = true; achou = true; }
        });
        if (!achou && sel.options.length) sel.options[0].selected = true;
      }
      if (nome) nome.value = "";
      if (typeof dlg.showModal === "function") dlg.showModal();
      else dlg.setAttribute("open", "");
      if (nome) setTimeout(function () { nome.focus(); }, 40);
    });

    dlg.querySelectorAll("[data-stn-fechar]").forEach(function (b) {
      b.addEventListener("click", function () { dlg.close(); });
    });
    // Clique no veu fecha (o <dialog> nao faz isso sozinho).
    dlg.addEventListener("click", function (e) {
      if (e.target === dlg) dlg.close();
    });
  }

  function initFiltrarPopup() {
    // O HOST é o PAI da barra de filtros, qualquer que seja o nome da classe
    // dele. Antes isto exigia `.mpa-fbar`, que só existe no mapa — por isso o
    // mapa tinha o botão "Filtrar" e a Tabela, os Notebooks e os Setores
    // continuavam com os dropdowns crus na tela. Era o que o dono chamou de
    // "visões distintas": a mesma barra com três aparências.
    var barra = document.querySelector(".flt-bar");
    if (!barra) return;                         // tela de loja única: nada a agrupar
    var fbar = barra.parentElement;
    if (!fbar || fbar.dataset.mkFiltrar) return;

    var blocos = [];
    // Além dos dropdowns, vão para o popup os filtros avulsos de cada tela:
    // cargo (mapa) e período de compra (tabela de dispositivos).
    fbar.querySelectorAll(".flt-bar, .mapa-cargo").forEach(function (el) { blocos.push(el); });
    var periodo = document.querySelector(".tab-periodo");
    if (periodo) blocos.push(periodo);
    if (!blocos.length) return;
    fbar.dataset.mkFiltrar = "1";

    var casca = document.createElement("div");
    casca.className = "mkfp";

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "mkfp__btn";
    btn.setAttribute("aria-haspopup", "dialog");
    btn.setAttribute("aria-expanded", "false");
    btn.innerHTML =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<path d="M4 5h16l-6 7v6l-4 2v-8z"/></svg>' +
      '<span class="mkfp__lbl">Filtrar</span>' +
      '<span class="mkfp__n" hidden></span>';

    var pop = document.createElement("div");
    pop.className = "mkfp__pop";
    pop.setAttribute("role", "dialog");
    pop.setAttribute("aria-label", "Filtros do mapa");
    pop.hidden = true;

    // O primeiro bloco marca o lugar: a casca entra ali e os filtros vão para
    // dentro dela, então a ordem da linha não muda.
    blocos[0].parentNode.insertBefore(casca, blocos[0]);
    casca.appendChild(btn);
    casca.appendChild(pop);
    blocos.forEach(function (el) { pop.appendChild(el); });

    // ------------------------------------------------------------------
    // O painel de cada dropdown fica SEMPRE aberto dentro do popup — o popup
    // já é a abertura. E isso tem de ser feito no ATRIBUTO, não no CSS.
    //
    // Por quê: o `styles.css` do unfold (Tailwind v4) traz
    //     [hidden]:where(:not([hidden="until-found"])) { display: none !important }
    // DENTRO de uma `@layer`. Pela regra de camadas, `!important` dentro de
    // camada vence `!important` fora dela, e especificidade não entra na
    // conta — então nenhuma regra minha em make-m3.css consegue ganhar. O
    // sintoma era o painel sem pintar e as fichas sem receber clique.
    //
    // O `initFiltroDropdowns` recoloca `hidden` em TODOS os painéis a cada
    // clique (o `fecharTodos` dele), por isso o observador: ele tira de novo.
    // ------------------------------------------------------------------
    var paineis = pop.querySelectorAll("[data-mkdd-panel]");
    function abrirPaineis() {
      paineis.forEach(function (pn) { if (pn.hasAttribute("hidden")) pn.removeAttribute("hidden"); });
    }
    abrirPaineis();
    paineis.forEach(function (pn) {
      new MutationObserver(abrirPaineis).observe(pn, { attributes: true, attributeFilter: ["hidden"] });
    });

    // Quantos filtros estão VALENDO — lê o estado que os próprios componentes
    // publicam, em vez de manter contagem paralela.
    //
    // O selo contava `.fltx-active` DENTRO do popup, e esse bloco fica FORA
    // dele (é irmão da `.flt-bar`, no host): o número não subia com unidade nem
    // com os grupos genéricos novos. Agora conta os chips de filtro aplicado
    // onde eles realmente estão — um chip por filtro em vigor, seja unidade,
    // setor, situação, tipo, motivo ou período.
    function contar() {
      var n = fbar.querySelectorAll(".fltx-active .fltx-chip").length;
      if (!n) {
        pop.querySelectorAll('[data-mkdd-multi] input[type="checkbox"]:checked').forEach(function (c) {
          if (!c.hasAttribute("data-mkdd-all")) n++;
        });
      }
      var cargo = pop.querySelector("#mapa-cargo-sel");
      if (cargo && cargo.value) n++;
      var chip = btn.querySelector(".mkfp__n");
      chip.textContent = n ? String(n) : "";
      chip.hidden = !n;
      btn.classList.toggle("is-on", !!n);
    }
    contar();

    // ------------------------------------------------------------------
    // ALTURA PELO ESPACO QUE SOBRA, nao por numero fixo.
    //
    // O CSS trazia `max-height: min(78vh, 540px)`, e 540px contados a partir
    // do botao. Só que o botao fica a ~250px do topo: numa janela de 780px o
    // painel terminava em 790 e o rodape — com o "Aplicar" — nascia fora da
    // tela. O dono: "o cara é obrigado a rolar a tela pra aplicar o filtro?".
    //
    // Aqui a conta é a única que serve: quanto sobra ABAIXO do botao. E se
    // sobrar pouco (janela baixa, botao no meio da tela), o painel deixa de
    // ser popup ancorado e vira folha presa no rodape da janela — que é o
    // mesmo desenho do celular, e ali o "Aplicar" está sempre visível.
    // ------------------------------------------------------------------
    var ALTURA_MIN = 340;      // menos que isso não cabe lista + rodapé
    var ALTURA_MAX = 540;
    function ajustarAltura() {
      if (pop.hidden) return;
      var r = btn.getBoundingClientRect();
      // `clientHeight` do documento, nao `innerHeight`: aquele desconta a
      // barra de rolagem horizontal quando existe. E 32px de margem para o
      // painel nao encostar na borda de baixo.
      var alturaJanela = document.documentElement.clientHeight || window.innerHeight;
      var folga = alturaJanela - r.bottom - 32;
      if (folga < ALTURA_MIN) {
        pop.classList.add("mkfp__pop--folha");
        pop.style.removeProperty("max-height");
      } else {
        pop.classList.remove("mkfp__pop--folha");
        // `setProperty(..., "important")`, e nao `style.maxHeight = ...`:
        // ARMADILHA MEDIDA. A regra do painel no make-m3.css e'
        // `max-height: min(78vh, 540px) !important`, e no CSS uma declaracao
        // com `!important` na FOLHA vence estilo inline SEM `!important` — o
        // inverso do que a intuicao diz. A medicao rodava certinho e nao
        // valia nada: o painel continuava com 540px contados do botao, e o
        // "Aplicar" nascia abaixo da borda da janela.
        pop.style.setProperty("max-height", Math.min(folga, ALTURA_MAX) + "px", "important");
      }
    }

    function abrir(on) {
      pop.hidden = !on;
      btn.setAttribute("aria-expanded", on ? "true" : "false");
      casca.classList.toggle("mkfp--aberto", on);
      if (on) ajustarAltura();
      else pop.style.removeProperty("max-height");
    }
    window.addEventListener("resize", ajustarAltura);
    // Rolar a pagina move o botao: o painel acompanha em vez de sair da tela.
    window.addEventListener("scroll", ajustarAltura, true);
    btn.addEventListener("click", function (e) { e.stopPropagation(); abrir(pop.hidden); });
    document.addEventListener("click", function (e) {
      if (pop.hidden || e.target.closest(".mkfp")) return;
      abrir(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !pop.hidden) { abrir(false); btn.focus(); }
    });
    pop.addEventListener("change", contar);

    // ------------------------------------------------------------------
    // UM SÓ "APLICAR". Antes o popup misturava três comportamentos: unidade e
    // as fichas de data eram LINKS (navegavam no clique), setor tinha um
    // Aplicar próprio e o intervalo tinha outro. Era o que o dono chamou de
    // horrível — e é, porque o mesmo painel se comportava de três formas.
    //
    // Aqui dentro tudo passa a ser escolha, e quem envia é o rodapé. O
    // formulário do intervalo é reaproveitado como carregador: os campos de
    // unidade e setor entram nele como hidden na hora do envio. Fora do popup
    // (sem JS) os links continuam funcionando como sempre.
    // ------------------------------------------------------------------
    // ------------------------------------------------------------------
    // PAINEL EM CAMADAS — uma pergunta por vez.
    //
    // A versão anterior abria TODOS os grupos ao mesmo tempo, em duas
    // colunas. No mapa isso dava sete lojas, dezesseis setores, um select de
    // cargo, quatro atalhos de data e o calendário — cerca de trinta alvos de
    // clique numa janela mais alta que a tela, por cima dos cards. O dono
    // resumiu: "tá muita informação pra colocar ao mesmo tempo".
    //
    // Agora o painel abre com UMA LINHA POR DIMENSÃO, dizendo o que está
    // escolhido nela. Clicar na linha mostra só aquele grupo; o "voltar"
    // retorna ao menu. Os grupos continuam sendo os MESMOS nós que o servidor
    // mandou — links com href pronto, `keep`, calendário, checkbox de setor —
    // então o contrato não muda e sem JS a tela filtra igual. O que mudou é
    // quem está visível.
    //
    // Mover estes nós é seguro: os ouvintes de `initFiltroDropdowns` estão
    // ligados nos próprios elementos (viajam com eles) e aqui não há Alpine.
    // A `.flt-bar` continua no documento, vazia, porque `initFiltroDropdowns`
    // a procura por `querySelector` global para ler `data-uni`/`data-keep` e
    // montar a URL do setor múltiplo.
    // ------------------------------------------------------------------
    var SVG = {
      loja: '<path d="M3 9l1.6-5h14.8L21 9"/><path d="M4.5 9h15v11h-15z"/><path d="M9.5 20v-6h5v6"/>',
      setor: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.6"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.6"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.6"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.6"/>',
      data: '<rect x="3.5" y="5" width="17" height="15.5" rx="2.2"/><path d="M3.5 10h17M8 3.2v3.6M16 3.2v3.6"/><path d="M12 13.2v3.3l2.4 1.4"/>',
      estado: '<path d="M4 17.5a8 8 0 1 1 16 0"/><path d="M12 17.5l4.2-6.2"/><circle cx="12" cy="17.5" r="1.4" fill="currentColor"/>',
      tipo: '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0l-7.2-7.2a2 2 0 0 1-.6-1.4V4a1 1 0 0 1 1-1h8a2 2 0 0 1 1.4.6l7.4 7.4a2 2 0 0 1 0 2.4z"/><path d="M7.5 7.5h.01"/>',
      motivo: '<path d="m21.7 18-8-14a2 2 0 0 0-3.5 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3z"/><path d="M12 9v4M12 17h.01"/>',
      oficina: '<path d="M14.7 6.3a4 4 0 0 0 5 5l-9.4 9.4a2 2 0 0 1-2.8 0l-2.2-2.2a2 2 0 0 1 0-2.8z"/>',
      estoque: '<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M6 17h12v4H6z"/>',
      pessoa: '<path d="M17 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2"/><circle cx="10" cy="7" r="4"/><path d="M19 8v6M22 11h-6"/>',
      geral: '<path d="M4 6h16M4 12h10M4 18h6"/><circle cx="18" cy="12" r="2"/><circle cx="12" cy="18" r="2"/>'
    };
    // Cada dimensão com o seu papel de cor do M3. O ícone DIFERENCIA, não
    // decora: quem não lê o rótulo acha pela cor.
    var TOM = {
      loja:    ["var(--md-primary-container)", "var(--md-on-primary-container)"],
      setor:   ["var(--md-secondary-container)", "var(--md-on-secondary-container)"],
      data:    ["var(--md-tertiary-container)", "var(--md-on-tertiary-container)"],
      estado:  ["var(--md-st-ok-cont)", "var(--md-st-ok)"],
      tipo:    ["var(--md-secondary-container)", "var(--md-on-secondary-container)"],
      motivo:  ["var(--md-st-warn-cont)", "var(--md-st-warn)"],
      oficina: ["var(--md-secondary-container)", "var(--md-on-secondary-container)"],
      estoque: ["var(--md-tertiary-container)", "var(--md-on-tertiary-container)"],
      pessoa:  ["var(--md-secondary-container)", "var(--md-on-secondary-container)"],
      geral:   ["var(--md-surface-container-highest)", "var(--md-on-surface-variant)"]
    };
    var POR_PARAM = {
      unidade: "loja", loja: "loja",
      sit: "estado", situacao: "estado", status: "estado",
      tipo: "tipo", motivo: "motivo",
      autorizada: "oficina", fornecedor: "oficina",
      estoque: "estoque", com: "geral", filtro: "geral"
    };

    function familia(el) {
      if (el.classList.contains("mkdd--data") || el.classList.contains("tab-periodo")) return "data";
      if (el.classList.contains("mkdd--multi")) return "setor";
      if (el.classList.contains("mapa-cargo")) return "pessoa";
      var pp = el.getAttribute("data-mkdd-param");
      if (pp && POR_PARAM[pp]) return POR_PARAM[pp];
      if (el.classList.contains("mkdd") && !pp) return "loja";   // o grupo de unidade
      return "geral";
    }
    function caixaIcone(fam) {
      var t = TOM[fam] || TOM.geral;
      return '<span class="mkfp__ic" style="--ic-cont:' + t[0] + ';--ic-ink:' + t[1] + '">' +
             '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" ' +
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
             (SVG[fam] || SVG.geral) + '</svg></span>';
    }

    // --- os passos: uma dimensão cada ---------------------------------------
    var passos = [];
    pop.querySelectorAll(".mkdd").forEach(function (g) { passos.push(g); });
    var elCargo = pop.querySelector(".mapa-cargo");
    if (elCargo) passos.push(elCargo);
    var elPeriodo = pop.querySelector(".tab-periodo");
    if (elPeriodo) passos.push(elPeriodo);

    function tituloDe(el) {
      var l = el.querySelector(".mkdd__lbl, .mapa-cargo__lbl, label");
      var t = l ? (l.textContent || "").trim() : "";
      if (t) return t.replace(/\s*:\s*$/, "");
      if (el.classList.contains("tab-periodo")) return "Período";
      return "Filtro";
    }
    function brData(v) {
      var q = String(v || "").split("-");
      return q.length === 3 ? q[2] + "/" + q[1] : "";
    }
    function atualDe(el) {
      var cur = el.querySelector(".mkdd__cur");
      if (cur) return (cur.textContent || "").trim();
      var sel = el.querySelector("select");
      if (sel) {
        var o = sel.options[sel.selectedIndex];
        return (sel.value && o) ? (o.textContent || "").trim() : "Todos";
      }
      var datas = el.querySelectorAll('input[type="date"]');
      if (datas.length) {
        var a = datas[0].value, b = datas[1] ? datas[1].value : "";
        if (a && b) return brData(a) + " até " + brData(b);
        if (a) return "A partir de " + brData(a);
        if (b) return "Até " + brData(b);
      }
      return "Todos";
    }
    var VAZIOS = ["todas", "todos", "qualquer data", "todas as lojas", "todos os setores", ""];
    function estaVazio(txt) { return VAZIOS.indexOf(String(txt).trim().toLowerCase()) !== -1; }

    // --- casca: topo, corpo (menu + passos); o rodapé já existia ------------
    var topo = document.createElement("div");
    topo.className = "mkfp__topo";
    topo.innerHTML =
      '<button type="button" class="mkfp__ib mkfp__voltar" hidden aria-label="Voltar">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg></button>' +
      '<h4 class="mkfp__tit">Filtrar</h4>' +
      '<button type="button" class="mkfp__ib mkfp__fechar" aria-label="Fechar">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg></button>';

    var corpo = document.createElement("div");
    corpo.className = "mkfp__corpo";
    var menu = document.createElement("div");
    menu.className = "mkfp__menu";
    corpo.appendChild(menu);

    var barraNo = pop.querySelector(".flt-bar");
    passos.forEach(function (el) {
      el.classList.add("mkfp__passo");
      el.hidden = true;
      corpo.appendChild(el);
    });
    if (barraNo) corpo.appendChild(barraNo);
    pop.insertBefore(topo, pop.firstChild);
    pop.appendChild(corpo);

    var elTit = topo.querySelector(".mkfp__tit");
    var btVoltar = topo.querySelector(".mkfp__voltar");

    // Ripple do M3: a tinta sai de onde o dedo tocou.
    function pingar(host, e) {
      var r = host.getBoundingClientRect();
      var d = Math.max(r.width, r.height) * 2;
      var t = document.createElement("span");
      t.className = "mkfp__tinta";
      t.style.width = t.style.height = d + "px";
      t.style.left = (e.clientX - r.left - d / 2) + "px";
      t.style.top = (e.clientY - r.top - d / 2) + "px";
      t.addEventListener("animationend", function () { t.remove(); });
      host.appendChild(t);
    }

    var linhas = passos.map(function (el, i) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "mkfp__linha";
      b.style.setProperty("--i", i);
      b.innerHTML = caixaIcone(familia(el)) +
        '<span class="mkfp__lt"><b></b><span></span></span>' +
        '<svg class="mkfp__chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>';
      b.addEventListener("pointerdown", function (e) { pingar(b, e); });
      b.addEventListener("click", function () { mostrar(i); });
      menu.appendChild(b);
      return b;
    });

    function sincronizar() {
      passos.forEach(function (el, i) {
        var lt = linhas[i].querySelector(".mkfp__lt");
        lt.querySelector("b").textContent = tituloDe(el);
        var txt = atualDe(el);
        var sp = lt.querySelector("span");
        sp.textContent = txt;
        sp.classList.toggle("is-posto", !estaVazio(txt));
      });
    }
    function mostrar(i) {
      passos.forEach(function (el, k) { el.hidden = k !== i; });
      menu.hidden = true;
      btVoltar.hidden = false;
      elTit.textContent = tituloDe(passos[i]);
      corpo.scrollTop = 0;
      // Reinicia a cascata do calendário toda vez que o passo aparece.
      var cal = passos[i].querySelector("[data-mkcal]");
      if (cal) {
        cal.classList.remove("mkcal--desce");
        void cal.offsetWidth;
        cal.classList.add("mkcal--desce");
      }
    }
    function voltarMenu() {
      passos.forEach(function (el) { el.hidden = true; });
      menu.hidden = false;
      btVoltar.hidden = true;
      elTit.textContent = "Filtrar";
      sincronizar();
    }
    btVoltar.addEventListener("click", voltarMenu);
    topo.querySelector(".mkfp__fechar").addEventListener("click", function () { abrir(false); });
    if (elCargo) {
      var selCargo = elCargo.querySelector("select");
      if (selCargo) selCargo.addEventListener("change", function () { contar(); voltarMenu(); });
    }
    sincronizar();

    var form = pop.querySelector("form.mkdd__data");
    var calHost = pop.querySelector("[data-mkcal]");

    // ------------------------------------------------------------------
    // LIMPAR A DATA, dentro do passo da data.
    //
    // A queixa do usuário: "uma vez selecionada a data não dava pra limpar
    // mais o filtro, só depois de aplicar". Era verdade — o calendário não
    // tinha ramo de desmarcar, e a única saída era a ficha "Qualquer data",
    // que ninguém lê como "limpar". O calendário agora desmarca ponta a ponta
    // (montarCalendario) e este botão zera as duas de uma vez, sem aplicar
    // nada e sem sair do painel.
    // ------------------------------------------------------------------
    if (calHost) {
      var limpaData = document.createElement("button");
      limpaData.type = "button";
      limpaData.className = "mkfp__limpar-data";
      limpaData.textContent = "Limpar data";
      function ajustarLimpaData() {
        var vazio = calHost.mkCal ? calHost.mkCal.vazio() : false;
        limpaData.disabled = vazio;
      }
      limpaData.addEventListener("click", function () {
        if (calHost.mkCal) calHost.mkCal.limpar();
        var f = calHost.closest("form");
        if (f) {
          f.querySelectorAll('input[type="date"]').forEach(function (i) { i.value = ""; });
        }
        ajustarLimpaData();
        contar();
      });
      // No cabecalho do calendario, ao lado da manchete: e' onde a pessoa esta
      // olhando quando quer desfazer. Antes ficava solto acima do calendario.
      var slot = calHost.querySelector("[data-mkcal-slot]");
      if (slot) slot.appendChild(limpaData);
      else calHost.parentNode.insertBefore(limpaData, calHost);

      // ------------------------------------------------------------------
      // A FICHA MARCADA TEM DE BATER COM A DATA QUE VALE.
      //
      // O `is-sel` de "Qualquer data" vinha do servidor (a URL nao tinha
      // periodo) e nunca era retirado: com 03/09 a 12/09 escolhidos no
      // calendario, o painel mostrava o intervalo E a marca de "qualquer
      // data" ao mesmo tempo. Duas respostas contraditorias na mesma tela.
      //
      // Aqui a marca e' derivada: cada ficha carrega no href o periodo que
      // ela representa; marca a que for igual ao que esta nos campos. Um
      // intervalo qualquer nao casa com nenhuma — e nenhuma fica marcada,
      // que e' a verdade.
      // ------------------------------------------------------------------
      var grupoData = calHost.closest(".mkdd--data");
      function sincronizarFichasData() {
        if (!grupoData || !form) return;
        var i1 = form.querySelector('input[name="vence_desde"]');
        var i2 = form.querySelector('input[name="vence_ate"]');
        var vd = i1 ? (i1.value || "") : "";
        var va = i2 ? (i2.value || "") : "";
        grupoData.querySelectorAll("a.mkdd__opt").forEach(function (a) {
          var q = new URLSearchParams((a.getAttribute("href") || "").split("?")[1] || "");
          a.classList.toggle("is-sel",
            (q.get("vence_desde") || "") === vd && (q.get("vence_ate") || "") === va);
        });
      }

      function depoisDeMexerNaData() {
        ajustarLimpaData();
        sincronizarFichasData();
        contar();
      }
      limpaData.addEventListener("click", depoisDeMexerNaData);
      calHost.addEventListener("click", depoisDeMexerNaData);
      pop.addEventListener("click", depoisDeMexerNaData, true);
      depoisDeMexerNaData();
    }
    // null = não mexeu (vale o que está na URL); "" = escolheu "Todas".
    // `extra` guarda o mesmo para os grupos genéricos, por nome de parâmetro.
    var estado = { unidade: null, extra: {} };

    function marcarNoGrupo(grupo, alvo) {
      grupo.querySelectorAll("a.mkdd__opt").forEach(function (a) {
        a.classList.toggle("is-sel", a === alvo);
      });
    }

    // FASE DE CAPTURA, de propósito: o `initFiltroDropdowns` põe
    // `stopPropagation()` no clique de cada painel, então um ouvinte de
    // borbulha aqui nunca recebia o evento — as fichas continuavam navegando
    // como link e o calendário nunca era alimentado.
    pop.addEventListener("click", function (e) {
      var a = e.target.closest("a.mkdd__opt");
      if (!a || !pop.contains(a)) return;
      var grupo = a.closest(".mkdd");
      if (!grupo) return;
      e.preventDefault();
      var q = new URLSearchParams((a.getAttribute("href") || "").split("?")[1] || "");

      if (grupo.classList.contains("mkdd--data")) {
        // Ficha de atalho de data: alimenta o calendário em vez de navegar.
        var d = q.get("vence_desde") || "";
        var t = q.get("vence_ate") || "";
        if (calHost && calHost.mkCal) calHost.mkCal.definir(d, t);
        else {
          var i1 = form && form.querySelector('input[name="vence_desde"]');
          var i2 = form && form.querySelector('input[name="vence_ate"]');
          if (i1) i1.value = d;
          if (i2) i2.value = t;
        }
      } else if (grupo.hasAttribute("data-mkdd-param")) {
        // Grupo genérico (situação, tipo, motivo, loja, autorizada…): o nome do
        // parâmetro vem do próprio grupo, então uma tela nova só precisa
        // declarar a dimensão na view — nada de JS por tela.
        var p = grupo.getAttribute("data-mkdd-param");
        estado.extra[p] = q.get(p) || "";
      } else {
        estado.unidade = q.get("unidade") || "";
      }
      marcarNoGrupo(grupo, a);
      // O `.mkdd__cur` é o que a linha do menu lê: sem atualizar aqui, a
      // escolha só apareceria depois de recarregar a página.
      var cur = grupo.querySelector(".mkdd__cur");
      if (cur && !grupo.classList.contains("mkdd--data")) {
        cur.textContent = (a.textContent || "").trim();
      }
      contar();
      // Escolheu: volta para o menu. É o que fecha o ciclo "uma pergunta por
      // vez" — a lista de opções não é lugar para ficar.
      if (typeof voltarMenu === "function" && !grupo.classList.contains("mkdd--multi")) {
        voltarMenu();
      }
    }, true);

    // Rodapé: Limpar (volta a tela sem filtro) e Aplicar (envia tudo junto).
    //
    // "Limpar" era `href="?"` fixo, e isso apaga a querystring INTEIRA — em
    // Cadastros voltava para a aba de colaboradores, em Registros para o mês
    // corrente, na Preventiva para a visão padrão. Limpar filtro não é trocar
    // de tela. Quando o parcial já publica o "Limpar tudo" (`.fltx-clear`), o
    // rodapé usa o destino DELE, que preserva o que não é filtro.
    var limparHref = "?";
    var clear = fbar.querySelector(".fltx-clear");
    if (clear && clear.getAttribute("href")) limparHref = clear.getAttribute("href");
    var pe = document.createElement("div");
    pe.className = "mkfp__pe";
    pe.innerHTML =
      '<a class="mkfp__limpar" href="' + limparHref.replace(/"/g, "&quot;") + '">Limpar</a>' +
      '<button type="button" class="mkfp__ok">Aplicar</button>';
    pop.appendChild(pe);

    pe.querySelector(".mkfp__ok").addEventListener("click", function () {
      if (!form) return;
      form.querySelectorAll("[data-mkfp-inj]").forEach(function (i) { i.remove(); });
      function juntar(nome, valor) {
        var i = document.createElement("input");
        i.type = "hidden"; i.name = nome; i.value = valor;
        i.setAttribute("data-mkfp-inj", "1");
        form.appendChild(i);
      }
      // Unidade e setor vêm do popup; os "keep" desses dois saem para não ir
      // o valor antigo junto com o novo.
      var uni = estado.unidade;
      if (uni === null) {
        var keepUni = form.querySelector('[data-mkfp-keep="unidade"]');
        uni = keepUni ? keepUni.value : "";
      }
      form.querySelectorAll('[data-mkfp-keep="unidade"], [data-mkfp-keep="setor"]')
        .forEach(function (i) { i.remove(); });
      if (uni) juntar("unidade", uni);
      var marcados = pop.querySelectorAll('input[name="setor"]:checked');
      if (marcados.length) {
        marcados.forEach(function (c) { juntar("setor", c.value); });
      }

      // ---- Grupos genéricos: cada um manda o SEU parâmetro ----
      // Mesma mecânica da unidade: grupo em que o usuário não mexeu mantém o
      // valor que veio na URL (o par `data-mkfp-keep`), e o par sai antes de
      // injetar o novo para não enviar o velho junto.
      pop.querySelectorAll("[data-mkdd-param]").forEach(function (g) {
        var p = g.getAttribute("data-mkdd-param");
        if (!p) return;
        var v = Object.prototype.hasOwnProperty.call(estado.extra, p) ? estado.extra[p] : null;
        var keeps = form.querySelectorAll('[data-mkfp-keep="' + p + '"]');
        if (v === null) v = keeps.length ? keeps[0].value : "";
        keeps.forEach(function (i) { i.remove(); });
        if (v) juntar(p, v);
      });

      // ---- Período com nome de parâmetro próprio ----
      // O calendário (`initCalendarioFiltro`) só sabe escrever em
      // `vence_desde`/`vence_ate`. Quando a tela chama o período de outra coisa
      // — os logs usam `de`/`ate` —, o valor é reenviado sob o nome real e os
      // campos originais saem do envio (`disabled`), senão a view recebia dois
      // períodos e ignorava o que a pessoa escolheu.
      var gdata = pop.querySelector(".mkdd--data[data-mkfp-de]");
      if (gdata) {
        [["vence_desde", gdata.getAttribute("data-mkfp-de")],
         ["vence_ate", gdata.getAttribute("data-mkfp-ate")]].forEach(function (par) {
          var el = form.querySelector('input[name="' + par[0] + '"]');
          if (!el || !par[1]) return;
          if (el.value) juntar(par[1], el.value);
          el.disabled = true;
        });
      }

      // ---- Campos de data que vivem em OUTRO formulário dentro do popup ----
      // O período de compra da tabela (`.tab-periodo`) é um formulário próprio
      // que o popup engoliu; sem isto, digitar a data ali e clicar no "Aplicar"
      // do rodapé perdia o que foi digitado.
      pop.querySelectorAll('input[type="date"][name]').forEach(function (el) {
        if (form.contains(el) || !el.value) return;
        juntar(el.name, el.value);
      });
      form.submit();
    });

    // O Aplicar de dentro do grupo de setor e o do intervalo saem de cena: o
    // rodapé faz o trabalho dos dois (o CSS os esconde; aqui só garantimos que
    // um clique acidental não dispare envio pela metade).
    pop.querySelectorAll("[data-mkdd-apply], .mkdd__data-b").forEach(function (b) {
      b.setAttribute("tabindex", "-1");
      b.setAttribute("aria-hidden", "true");
    });
  }

  // ---------- Busca ÚNICA com popup de filtros ----------
  // Pedido do dono: "o mapa precisa ter um campo único de pesquisa e uma opção
  // de filtro no próprio campo que abre um popup com os filtros para aplicar".
  //
  // Antes a faixa tinha três controles soltos lado a lado — Unidade, Setor e
  // Cargo — mais o campo de busca. Agora tem UM campo, com um botão de filtro
  // dentro dele; os seletores vivem num popup ancorado no campo.
  //
  // Os filtros NÃO são reescritos: os nós existentes são MOVIDOS para dentro do
  // popup. Reescrever significaria refazer `_filtros.html` e `_mapa_cargo.html`,
  // que carregam gancho vivo — `.flt-bar[data-uni][data-keep]`, `[data-mkdd]`,
  // `#mapa-cargo-sel` — e o JS que monta a URL a partir deles. Movendo, tudo
  // continua funcionando como está e o risco fica perto de zero.
  function initBuscaUnica() {
    var fbar = document.querySelector(".mpa-fbar");
    var busca = fbar && fbar.querySelector(".mapa__busca");
    if (!fbar || !busca || fbar.dataset.mkBuscaUnica) return;

    var filtros = [];
    fbar.querySelectorAll(".flt-bar, .mapa-cargo").forEach(function (el) { filtros.push(el); });
    if (!filtros.length) return;          // tela de loja única: nada a agrupar
    fbar.dataset.mkBuscaUnica = "1";

    // Casca: o campo de busca e o botão de filtro dividem a mesma moldura.
    var casca = document.createElement("div");
    casca.className = "mkbu";
    busca.parentNode.insertBefore(casca, busca);
    casca.appendChild(busca);

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "mkbu__btn";
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-haspopup", "dialog");
    btn.innerHTML =
      '<span class="material-symbols-outlined" aria-hidden="true">tune</span>' +
      '<span class="mkbu__lbl">Filtros</span>' +
      '<span class="mkbu__n" hidden></span>';
    casca.appendChild(btn);

    var pop = document.createElement("div");
    pop.className = "mkbu__pop";
    pop.setAttribute("role", "dialog");
    pop.setAttribute("aria-label", "Filtros do mapa");
    pop.hidden = true;
    filtros.forEach(function (el) { pop.appendChild(el); });
    casca.appendChild(pop);

    // Quantos filtros estão valendo. Lê o estado que os próprios componentes já
    // publicam, em vez de manter contagem paralela: o `.fltx-active` que o
    // `_filtros.html` desenha quando há filtro, e o valor do seletor de cargo.
    function contar() {
      var n = 0;
      pop.querySelectorAll(".fltx-active .fltx-tag, .fltx-active__i").forEach(function () { n++; });
      if (!n && pop.querySelector(".fltx-active")) n = 1;
      var cargo = pop.querySelector("#mapa-cargo-sel");
      if (cargo && cargo.value) n++;
      var chip = btn.querySelector(".mkbu__n");
      chip.textContent = n ? String(n) : "";
      chip.hidden = !n;
      btn.classList.toggle("is-on", !!n);
      return n;
    }
    contar();

    function abrir(on) {
      pop.hidden = !on;
      btn.setAttribute("aria-expanded", on ? "true" : "false");
      casca.classList.toggle("mkbu--aberto", on);
    }
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      abrir(pop.hidden);
    });
    document.addEventListener("click", function (e) {
      if (pop.hidden) return;
      if (e.target.closest(".mkbu")) return;
      abrir(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !pop.hidden) { abrir(false); btn.focus(); }
    });
    // Mexer num filtro recarrega a tela (é assim que eles já funcionam), mas o
    // contador acompanha enquanto a página ainda está de pé.
    pop.addEventListener("change", contar);
    pop.addEventListener("click", function () { setTimeout(contar, 0); });
  }

  // ---------- Topo alinhado: um título só, e o alinhamento do conteúdo ----------
  // Duas frases do dono guiaram isto, e elas parecem brigar até você olhar as
  // telas:
  //   "olha esse espaço inútil, vamos remodelar essa parte toda"  (no mapa)
  //   "deixa esse padrão de alinhamento"                          (no dashboard)
  //
  // O que ele apontou no dashboard é o título DENTRO do conteúdo, no mesmo
  // canto esquerdo dos cartões de baixo. Minha primeira tentativa subiu o
  // título para a barra — o que quebra justamente esse alinhamento, porque a
  // barra tem recuo próprio e a seta de voltar empurra o texto 40px para a
  // direita.
  //
  // Então o desenho é este:
  //   · o título fica no conteúdo, alinhado com o que vem abaixo;
  //   · a barra PERDE o título (era a duplicata — "Mapa completo" na barra e
  //     "Mapa completo — todas as lojas" 70px abaixo) e fica com a seta de
  //     voltar, as ações da tela, o "?" e o sino;
  //   · o ar entre as duas faixas sai no CSS (§19.16).
  //
  // Este projeto já tinha essa decisão registrada para outros títulos: o
  // make-admin.css esconde `.mapa__titulo`, `.make-dash-titulo` e
  // `.aprov__titulo` com o comentário "o título aparece UMA vez só (no header)".
  // Ali a escolha foi manter o da barra; aqui é o oposto — fica o da tela, que é
  // o mais completo e o que carrega contagem e ações. Uma escolha, não duas.
  function initTopoUnico() {
    var head = document.querySelector("#content .mkpro-head");
    if (!head || head.dataset.mkFundido) return;
    var barra = document.querySelector("#main > header.make-header");
    if (!barra) return;
    head.dataset.mkFundido = "1";

    // A barra abre mão do título: quem manda é o da tela.
    var h1 = barra.querySelector("h1");
    if (h1 && head.querySelector(".mkpro-head__title")) {
      h1.classList.add("mkhdr__h1--cedido");
    }

    // As ações da tela FICAM na tela. Já tentei subi-las para a barra e o
    // resultado foi ícone de 300x150px: cada tela dimensiona o próprio SVG num
    // seletor escopado no bloco dela (ex.: `.rkb .pvx-btn svg{width:18px}` em
    // reparos_kanban.html). Tirar o botão de dentro de `.rkb` mata esse
    // seletor e o <svg> volta ao tamanho padrão do CSS, que é 300x150 — o
    // topo estoura e a página fica mais larga que a janela. Mover nó é barato;
    // mover o CSS de 20 telas não é. Só o título continua sendo cedido, que é
    // mudança de classe, não de lugar.
  }

  // ---------- O VOLTAR sobe para a barra do topo ----------
  // O ícone de gaveta do M3 (`menu_open`, um ≡ com seta) estava sendo lido como
  // seta de voltar; ao lado do "Voltar ao Início" que a tela já desenhava, dava
  // a impressão de dois botões de voltar. O dono pediu o voltar NO LUGAR do
  // recolher, e é o que acontece aqui.
  //
  // O link não é copiado: ele é MOVIDO de dentro da página para o slot do topo.
  // Copiar criaria exatamente a duplicata que estamos removendo, e obrigaria a
  // editar cada tela. Movendo, uma implementação serve todas, e tela que não
  // tem voltar simplesmente não mostra botão.
  var MK_SELETORES_VOLTAR = ".mkdf-head__back, .mapa__voltar, [data-mk-voltar]";

  function initVoltarNoTopo() {
    var slot = document.getElementById("mk-voltar");
    if (!slot || slot.dataset.mkPronto) return;

    var origem = document.querySelector(MK_SELETORES_VOLTAR);
    if (!origem || !origem.getAttribute("href")) return;
    slot.dataset.mkPronto = "1";

    // O rótulo vira TOOLTIP, não texto na barra: no M3 a barra do topo tem
    // ícone de navegação + título, e mais nada. A primeira versão punha o texto
    // ao lado do ícone e o resultado foi "muito textoooo" — com a seta em
    // dobro, porque o link da tela já trazia um "←" dentro do próprio texto.
    // Daí a limpeza do prefixo abaixo.
    var rotulo = (origem.textContent || "").trim()
      .replace(/\s+/g, " ")
      .replace(/^[←‹<⟵←‹\s]+/, "")
      .trim();
    slot.setAttribute("href", origem.getAttribute("href"));
    slot.setAttribute("title", rotulo ? "Voltar para " + rotulo : "Voltar");
    slot.setAttribute("aria-label", slot.getAttribute("title"));
    slot.innerHTML = '<span class="material-symbols-outlined" aria-hidden="true">arrow_back</span>';
    slot.hidden = false;

    // Sai da página: o botão passa a existir num lugar só.
    var caixa = origem.closest(".mkpro-head__actions");
    origem.remove();
    if (caixa && !caixa.children.length) caixa.remove();
  }

  // ---------- Menu lateral: UM botão só, na barra do topo ----------
  // Havia dois controles, e faziam coisas diferentes: o do unfold escondia a
  // barra inteira e o meu, no rodapé dela, recolhia para ícones. Agora é um só,
  // na barra do topo — onde a própria gaveta nunca o cobre.
  //
  // A visibilidade é decidida por CSS (make-m3.css §19.12), não pelo Alpine do
  // tema. Tentei usar o `sidebarToggle()` dele e não funciona de forma
  // confiável: o valor de `sidebarOpen` muda, mas o efeito do `x-show` não roda
  // de novo e o `display: none` em linha permanece — a gaveta não voltava e o
  // menu ficava morto. Aqui o estado é só nosso, e é impossível ficar sem menu:
  //   • acima de 1280px -> gaveta sempre visível; o botão escolhe entre gaveta
  //     cheia e régua de ícones (classe `mkx-side-collapsed`).
  //   • até 1280px -> gaveta sobreposta; o botão abre/fecha (`mk-gaveta-aberta`),
  //     e clique fora ou Esc fecham.
  // O limite de 1280px é o mesmo que o unfold usa, para não brigarem.
  function mkTelaLarga() { return window.innerWidth > 1280; }

  function initSidebarCollapse() {
    var btn = document.getElementById("mk-menu-toggle");
    if (!btn || btn.dataset.mkPronto) return;
    btn.dataset.mkPronto = "1";
    var corpo = document.body;

    // Título em cada item, para virar tooltip quando só o ícone aparecer. O
    // rótulo é o <span> que NÃO é o ícone: `textContent` do link inteiro traria
    // junto a ligadura da fonte de ícones ("home Início").
    document.querySelectorAll("#nav-sidebar-apps ol li a").forEach(function (a) {
      var rotulo = a.querySelector("span:not(.material-symbols-outlined)");
      var t = ((rotulo || a).textContent || "").trim();
      if (t) a.title = t;
    });

    function rotular() {
      var texto;
      if (!mkTelaLarga()) {
        texto = corpo.classList.contains("mk-gaveta-aberta") ? "Fechar menu" : "Abrir menu";
      } else {
        texto = corpo.classList.contains("mkx-side-collapsed") ? "Expandir menu" : "Recolher menu";
      }
      btn.title = texto;
      btn.setAttribute("aria-label", texto);
      // O par de ícones de gaveta do M3: `menu_open` mostra que ela está
      // aberta; `menu` (a hambúrguer) que está fechada ou recolhida.
      var ic = btn.querySelector(".material-symbols-outlined");
      if (ic) {
        var aberta = mkTelaLarga()
          ? !corpo.classList.contains("mkx-side-collapsed")
          : corpo.classList.contains("mk-gaveta-aberta");
        ic.textContent = aberta ? "menu_open" : "menu";
      }
      btn.setAttribute("aria-expanded",
        mkTelaLarga() ? (corpo.classList.contains("mkx-side-collapsed") ? "false" : "true")
                      : (corpo.classList.contains("mk-gaveta-aberta") ? "true" : "false"));
    }

    function recolher(on) {
      corpo.classList.toggle("mkx-side-collapsed", on);
      try { localStorage.setItem("mkx-side", on ? "1" : "0"); } catch (e) {}
      rotular();
    }

    function abrirGaveta(on) {
      corpo.classList.toggle("mk-gaveta-aberta", on);
      rotular();
    }

    // O recolhimento só é restaurado em tela larga: numa estreita a régua de
    // ícones come a tela sem ajudar ninguém.
    var salvo = false;
    try { salvo = localStorage.getItem("mkx-side") === "1"; } catch (e) {}
    corpo.classList.toggle("mkx-side-collapsed", mkTelaLarga() && salvo);
    rotular();

    btn.addEventListener("click", function () {
      if (mkTelaLarga()) recolher(!corpo.classList.contains("mkx-side-collapsed"));
      else abrirGaveta(!corpo.classList.contains("mk-gaveta-aberta"));
    });

    // O X dentro da gaveta (só em tela estreita) fecha. Ele vinha com o
    // `sidebarToggle()` do tema, que não é mais quem manda aqui.
    var fechar = document.querySelector(".mkbrand__close");
    if (fechar) {
      fechar.removeAttribute("x-on:click");
      fechar.addEventListener("click", function (e) {
        e.preventDefault(); e.stopPropagation(); abrirGaveta(false);
      });
    }

    // Gaveta sobreposta: clique fora e Esc fecham. Sem isso, véu sem saída.
    document.addEventListener("click", function (e) {
      if (mkTelaLarga() || !corpo.classList.contains("mk-gaveta-aberta")) return;
      if (e.target.closest("#nav-sidebar") || e.target.closest("#mk-menu-toggle")) return;
      abrirGaveta(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && corpo.classList.contains("mk-gaveta-aberta")) abrirGaveta(false);
    });

    // Ao estreitar a janela, desfaz a régua e fecha a gaveta: nenhum estado
    // atravessa o limite de forma incoerente.
    window.addEventListener("resize", function () {
      if (!mkTelaLarga()) corpo.classList.remove("mkx-side-collapsed");
      else corpo.classList.remove("mk-gaveta-aberta");
      rotular();
    });
  }

  // ---------- Toast "Acesso negado" (canto inferior esquerdo) ----------
  function initAcessoNegado() {
    if (!/[?&]negado=/.test(window.location.search)) return;
    // Também pelo painel do topo: era o último aviso desenhado na página.
    mkAvisar("Acesso negado — você não tem permissão para acessar essa área.", "error");
    try { history.replaceState(null, "", window.location.pathname); } catch (e) {}
  }

  // ---------- Transferência entre lojas (mapa + caminhão + animação) ----------
  function initTransferLojas() {
    // Funciona tanto na página dedicada (.tl.mapa) quanto embutido no mapa da
    // loja. Exclui o mapa de notebooks (.tl-nb), que tem seu próprio handler.
    var root = document.querySelector(".mapa[data-transferir-url]:not(.tl-nb)");
    if (!root) return;
    var planta = root.querySelector(".mapa__planta") || document.getElementById("transfer-planta");
    if (!planta) return;

    var dock = document.getElementById("truck-dock");
    var anim = document.getElementById("transfer-anim");
    var destUnits = document.getElementById("dest-units");
    var destMap = document.getElementById("dest-map");
    var confirmModal = document.getElementById("tl-confirm");
    var confirmMsg = document.getElementById("tl-confirm-msg");
    var okBtn = document.getElementById("tl-ok");
    var cancelBtn = document.getElementById("tl-cancel");
    var bitrixInput = document.getElementById("tl-bitrix");
    var bitrixWrap = document.getElementById("tl-bitrix-wrap");

    var url = root.getAttribute("data-transferir-url");
    var origemUnidade = root.getAttribute("data-origem-unidade") || "";
    var tokenEl = document.querySelector("[name=csrfmiddlewaretoken]");
    var token = tokenEl ? tokenEl.value : "";

    var drag = null;     // máquina sendo enviada {baia, nome, colab, patrimonio}
    var destino = null;  // destino escolhido

    function esc(s) { var d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }
    function maquinaLabel(d) {
      if (d.patrimonio) return d.patrimonio;
      return (d.colab && d.colab !== "—") ? d.colab : d.nome;
    }
    function toast(texto, erro) {
      // Delegado ao painel do topo (ver mkAvisar).
      mkAvisar(texto, erro ? "error" : "success");
    }

    // Loja de origem da baia: no mapa completo vem da unidade do grupo; senão, do root.
    function uniDaBaia(b) {
      var u = b.closest(".mapa-unidade");
      if (u) {
        if (u.getAttribute("data-unidade")) return u.getAttribute("data-unidade").trim();
        var t = u.querySelector(".mapa-unidade__titulo");
        if (t) return t.textContent.replace(/^[^0-9A-Za-zÀ-ÿ]+/, "").trim();
      }
      return origemUnidade;
    }

    // ----- arrastar a máquina -----
    planta.addEventListener("dragstart", function (e) {
      var b = e.target.closest(".baia[data-baia]");
      if (!b) return;
      if (b.getAttribute("data-pcstatus") === "sem_pc" && !b.getAttribute("data-patrimonio")) {
        drag = null; return;  // baia sem máquina não viaja (mas pode ser movida no mapa)
      }
      drag = {
        baia: b.getAttribute("data-baia"),
        nome: b.getAttribute("data-nome"),
        colab: b.getAttribute("data-colaborador"),
        patrimonio: b.getAttribute("data-patrimonio"),
        uni: uniDaBaia(b),
      };
      try { e.dataTransfer.setData("text/plain", drag.baia); e.dataTransfer.effectAllowed = "move"; } catch (x) {}
      if (dock) dock.classList.add("is-armed");
    });
    planta.addEventListener("dragend", function () {
      if (dock) dock.classList.remove("is-armed", "is-over");
    });

    // ----- soltar no caminhão -----
    if (dock) {
      dock.addEventListener("dragover", function (e) { if (drag) { e.preventDefault(); dock.classList.add("is-over"); } });
      dock.addEventListener("dragleave", function () { dock.classList.remove("is-over"); });
      dock.addEventListener("drop", function (e) {
        if (!drag) return;
        e.preventDefault();
        dock.classList.remove("is-over", "is-armed");
        tocarAnimacao();
      });
    }

    // ----- arrastar no TOQUE (celular) -----
    // DESLIGADO: no celular o toque é UNIFICADO pelo overlay de "mover" (initMapaTouch),
    // que oferece os setores da loja + a opção "Enviar para outra loja" (via ponte abaixo).
    // Assim os dois sistemas de toque não competem mais (era o bug do chip flutuante).
    if (false && "ontouchstart" in window && dock) {
      var tPress = null, tSX = 0, tSY = 0, tDragging = false, tBaia = null;
      var tChip = document.createElement("div");
      tChip.className = "tl-touch-chip"; tChip.style.display = "none";
      document.body.appendChild(tChip);

      function tLimparSel() { var s = window.getSelection && window.getSelection(); if (s && s.rangeCount) { try { s.removeAllRanges(); } catch (x) {} } }
      function tPosChip(t) { tChip.style.left = t.clientX + "px"; tChip.style.top = t.clientY + "px"; }
      function tSobreDock(t) {
        tChip.style.display = "none";
        var el = document.elementFromPoint(t.clientX, t.clientY);
        tChip.style.display = "block";
        return !!(el && (el === dock || el.closest("#truck-dock")));
      }
      planta.addEventListener("touchstart", function (e) {
        var b = e.target.closest(".baia[data-baia]");
        if (!b) return;
        if (b.getAttribute("data-pcstatus") === "sem_pc" && !b.getAttribute("data-patrimonio")) return;
        var t = e.touches[0]; tSX = t.clientX; tSY = t.clientY;
        tBaia = { baia: b.getAttribute("data-baia"), nome: b.getAttribute("data-nome"),
                  colab: b.getAttribute("data-colaborador"), patrimonio: b.getAttribute("data-patrimonio"),
                  uni: uniDaBaia(b) };
        tPress = setTimeout(function () { tIniciar(t); }, 380);
      }, { passive: true });
      planta.addEventListener("touchmove", function (e) {
        if (!tDragging && tPress) {
          var t = e.touches[0];
          if (Math.abs(t.clientX - tSX) > 12 || Math.abs(t.clientY - tSY) > 12) { clearTimeout(tPress); tPress = null; }
        }
      }, { passive: true });
      planta.addEventListener("touchend", function () { if (tPress) { clearTimeout(tPress); tPress = null; } });

      function tIniciar(t) {
        tDragging = true;
        document.body.classList.add("is-arrastando");
        tLimparSel();
        if (navigator.vibrate) { try { navigator.vibrate(15); } catch (x) {} }
        dock.classList.add("is-armed");
        tChip.textContent = maquinaLabel(tBaia);
        tChip.style.display = "block"; tPosChip(t);
        document.addEventListener("touchmove", tArrastar, { passive: false });
        document.addEventListener("touchend", tSoltar);
      }
      function tArrastar(e) {
        if (!tDragging) return;
        e.preventDefault(); tLimparSel();
        var t = e.touches[0]; tPosChip(t);
        dock.classList.toggle("is-over", tSobreDock(t));
      }
      function tSoltar(e) {
        document.removeEventListener("touchmove", tArrastar, { passive: false });
        document.removeEventListener("touchend", tSoltar);
        tDragging = false;
        document.body.classList.remove("is-arrastando");
        tChip.style.display = "none";
        var t = (e.changedTouches && e.changedTouches[0]) || null;
        var solto = t ? tSobreDock(t) : false;
        dock.classList.remove("is-over");
        if (solto && tBaia) {
          drag = { baia: tBaia.baia, nome: tBaia.nome, colab: tBaia.colab, patrimonio: tBaia.patrimonio, uni: tBaia.uni };
          dock.classList.remove("is-armed");
          tocarAnimacao();
        } else {
          dock.classList.remove("is-armed");
        }
        tBaia = null;
        tChip.style.display = "none";  // garante esconder (tSobreDock reexibe o chip)
      }
    }

    // ----- soltou no caminhão → vai direto escolher o destino -----
    function tocarAnimacao() { abrirDestino(); }

    function abrirOverlay(el) { if (el) { el.classList.add("is-open"); el.setAttribute("aria-hidden", "false"); } }
    function fecharOverlay(el) { if (el) { el.classList.remove("is-open"); el.setAttribute("aria-hidden", "true"); } }

    function abrirDestino() { abrirOverlay(destUnits); }

    // Ponte p/ o toque unificado (initMapaTouch): abre o seletor de loja com esta baia.
    window.__abrirTransferMobile = function (info) {
      if (!info || (info.pcstatus === "sem_pc" && !info.patrimonio)) return;  // sem máquina não viaja
      drag = { baia: info.id, nome: info.nome, colab: info.colab, patrimonio: info.patrimonio, uni: info.uni };
      tocarAnimacao();
    };

    // ----- escolher a loja de destino -----
    if (destUnits) {
      destUnits.addEventListener("click", function (e) {
        var card = e.target.closest(".tl-unit[data-unidade]");
        if (!card) return;
        var uid = card.getAttribute("data-unidade");
        destMap.querySelectorAll(".dest-unidade").forEach(function (u) {
          u.hidden = u.getAttribute("data-unidade") !== uid;
        });
        var nomeUni = card.querySelector(".tl-unit__nome");
        var titulo = document.getElementById("dest-map-title");
        if (titulo) titulo.textContent = "Destino: " + (nomeUni ? nomeUni.textContent : "");
        fecharOverlay(destUnits);
        abrirOverlay(destMap);
      });
    }
    var destBack = document.getElementById("dest-back");
    if (destBack) destBack.addEventListener("click", function () { fecharOverlay(destMap); abrirDestino(); });

    document.querySelectorAll("[data-close-dest]").forEach(function (btn) {
      btn.addEventListener("click", function () { fecharOverlay(destUnits); fecharOverlay(destMap); drag = null; destino = null; });
    });

    // ----- modal "nova baia" (substitui o prompt do navegador) -----
    var novaModal = document.getElementById("tl-novabaia");
    var novaInput = document.getElementById("tl-novabaia-input");
    var novaOk = document.getElementById("tl-novabaia-ok");
    var novaCancel = document.getElementById("tl-novabaia-cancel");
    var novaPendente = null;  // {setor, setorNome, uniNome}

    function abrirNovaBaia(dados) {
      novaPendente = dados;
      if (novaInput) { novaInput.value = ""; novaInput.classList.remove("is-erro"); }
      abrirOverlay(novaModal);
      if (novaInput) setTimeout(function () { novaInput.focus(); }, 50);
    }
    function confirmarNovaBaia() {
      if (!novaPendente) return;
      var nome = (novaInput.value || "").trim();
      if (!nome) { novaInput.classList.add("is-erro"); novaInput.focus(); return; }
      destino = {
        setor: novaPendente.setor, setorNome: novaPendente.setorNome,
        novo: nome, uniNome: novaPendente.uniNome,
      };
      novaPendente = null;
      fecharOverlay(novaModal);
      abrirConfirmacao();
    }
    if (novaOk) novaOk.addEventListener("click", confirmarNovaBaia);
    if (novaCancel) novaCancel.addEventListener("click", function () { novaPendente = null; fecharOverlay(novaModal); });
    if (novaModal) novaModal.addEventListener("click", function (e) { if (e.target === novaModal) { novaPendente = null; fecharOverlay(novaModal); } });
    if (novaInput) novaInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); confirmarNovaBaia(); }
    });

    // ----- escolher a vaga / nova baia -----
    if (destMap) {
      destMap.addEventListener("click", function (e) {
        var alvo = e.target.closest(".dest-baia");
        if (!alvo || alvo.disabled) return;
        var uniEl = alvo.closest(".dest-unidade");
        var uniNome = uniEl ? uniEl.getAttribute("data-unidade-nome") : "";
        if (alvo.getAttribute("data-novo")) {
          abrirNovaBaia({
            setor: alvo.getAttribute("data-setor"),
            setorNome: alvo.getAttribute("data-setor-nome"),
            uniNome: uniNome,
          });
          return;
        }
        destino = {
          baia: alvo.getAttribute("data-baia"),
          setor: alvo.getAttribute("data-setor"),
          setorNome: alvo.getAttribute("data-setor-nome"),
          baiaNome: alvo.getAttribute("data-nome"), uniNome: uniNome,
        };
        abrirConfirmacao();
      });
    }

    // ----- confirmação -----
    // Mesma loja de origem e destino = movimentação interna (não exige Bitrix).
    function ehInterno() {
      var uo = ((drag && drag.uni) || origemUnidade || "").trim();
      return !!(destino && destino.uniNome && uo && destino.uniNome.trim() === uo);
    }
    function abrirConfirmacao() {
      if (!drag || !destino) return;
      var ondeVai = destino.novo
        ? ("nova baia \"" + destino.novo + "\"")
        : ("baia \"" + destino.baiaNome + "\"");
      var interno = ehInterno();
      var uo = (drag && drag.uni) || origemUnidade;
      if (interno) {
        confirmMsg.innerHTML =
          "Mover o computador <b>" + esc(maquinaLabel(drag)) + "</b> internamente em <b>" + esc(destino.uniNome) + "</b> " +
          "para o setor <b>" + esc(destino.setorNome) + "</b> (" + esc(ondeVai) + ")?";
      } else {
        confirmMsg.innerHTML =
          "Confirmar a transferência do computador <b>" + esc(maquinaLabel(drag)) + "</b> " +
          "da unidade <b>" + esc(uo) + "</b> para a unidade <b>" + esc(destino.uniNome) + "</b>, " +
          "setor <b>" + esc(destino.setorNome) + "</b> (" + esc(ondeVai) + ")?";
      }
      if (bitrixWrap) bitrixWrap.hidden = interno;
      if (bitrixInput) bitrixInput.value = "";
      okBtn.disabled = false; okBtn.style.display = "";
      cancelBtn.textContent = "Cancelar";
      abrirOverlay(confirmModal);
    }
    function fecharConfirmacao() { fecharOverlay(confirmModal); }

    cancelBtn.addEventListener("click", fecharConfirmacao);
    confirmModal.addEventListener("click", function (e) { if (e.target === confirmModal) fecharConfirmacao(); });

    okBtn.addEventListener("click", function () {
      if (!drag || !destino) return;
      var bitrix = bitrixInput ? bitrixInput.value.trim() : "";
      if (!ehInterno() && !bitrix) {
        toast("Informe o código da tarefa do Bitrix para concluir a transferência.", true);
        if (bitrixInput) bitrixInput.focus();
        return;
      }
      okBtn.disabled = true;
      var body = "baia_origem=" + encodeURIComponent(drag.baia) +
        "&setor_destino=" + encodeURIComponent(destino.setor);
      if (destino.novo) body += "&nome_baia_destino=" + encodeURIComponent(destino.novo);
      else body += "&baia_destino=" + encodeURIComponent(destino.baia);
      if (bitrix) body += "&bitrix_task_id=" + encodeURIComponent(bitrix);
      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": token },
        body: body,
      })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          if (res.ok && res.j.ok && res.j.status === "aplicada") {
            if (res.j.protocolo_url) window.open(res.j.protocolo_url, "_blank");
            toast(res.j.msg || "Transferência realizada.");
            setTimeout(function () { window.location.reload(); }, 1200);
          } else if (res.ok && res.j.ok) {
            fecharConfirmacao(); fecharOverlay(destMap);
            toast(res.j.msg || "Solicitação enviada para autorização.");
            setTimeout(function () { window.location.reload(); }, 1500);
          } else {
            okBtn.disabled = false;
            toast((res.j && res.j.erro) || "Não foi possível transferir.", true);
          }
        })
        .catch(function () { okBtn.disabled = false; toast("Erro de conexão.", true); });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      fecharOverlay(confirmModal); fecharOverlay(novaModal); fecharOverlay(destMap); fecharOverlay(destUnits);
    });
  }

  // ---------- Transferência de NOTEBOOKS entre lojas (arrastar → caminhão) ----------
  function initTransferNotebooks() {
    var root = document.querySelector(".tl-nb[data-transferir-url]");
    if (!root) return;
    var planta = root.querySelector(".mapa__planta") || document.getElementById("transfer-planta-nb");
    if (!planta) return;

    var docksWrap = document.getElementById("nb-docks");
    var dock = document.getElementById("truck-dock-nb");
    var dockColab = document.getElementById("dock-colab");
    var anim = document.getElementById("transfer-anim-nb");
    var destUnits = document.getElementById("dest-units-nb");
    var confirmModal = document.getElementById("tl-confirm-nb");
    var confirmMsg = document.getElementById("tl-confirm-msg-nb");
    var userDest = document.getElementById("tl-user-dest-nb");
    var bitrixInput = document.getElementById("tl-bitrix-nb");
    var okBtn = document.getElementById("tl-ok-nb");
    var cancelBtn = document.getElementById("tl-cancel-nb");
    var carrossel = document.getElementById("colab-carrossel");
    var track = document.getElementById("colab-track");
    var busca = document.getElementById("colab-busca");
    var nbNomeEl = document.getElementById("colab-nb-nome");

    var url = root.getAttribute("data-transferir-url");
    var atribuirUrl = root.getAttribute("data-atribuir-url");
    var removerUrl = root.getAttribute("data-remover-url");
    var tokenEl = document.querySelector("[name=csrfmiddlewaretoken]");
    var token = tokenEl ? tokenEl.value : "";

    var drag = null;     // notebook sendo enviado {pk, nome, user}
    var destino = null;  // loja de destino {id, nome}

    function armar(on) { if (docksWrap) docksWrap.classList.toggle("is-armed", on); }

    function esc(s) { var d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }
    function nbLabel(d) {
      if (d.user && d.user !== "—") return (d.nome ? d.nome.trim() + " · " : "") + d.user;
      return (d.nome || "").trim() || "Notebook";
    }
    function toast(texto, erro) {
      // Delegado ao painel do topo (ver mkAvisar).
      mkAvisar(texto, erro ? "error" : "success");
    }

    function pegarCard(el) {
      var c = el.closest(".nb-card[data-notebook]");
      if (!c) return null;
      return { pk: c.getAttribute("data-notebook"), nome: c.getAttribute("data-nome"),
               user: c.getAttribute("data-user") };
    }

    // ----- arrastar o notebook (desktop) -----
    planta.addEventListener("dragstart", function (e) {
      var d = pegarCard(e.target);
      if (!d) return;
      drag = d;
      try { e.dataTransfer.setData("text/plain", drag.pk); e.dataTransfer.effectAllowed = "move"; } catch (x) {}
      armar(true);
    });
    planta.addEventListener("dragend", function () {
      if (!aberto(destUnits) && !aberto(carrossel)) {
        armar(false);
        if (dock) dock.classList.remove("is-over");
        if (dockColab) dockColab.classList.remove("is-over");
      }
    });

    // ----- soltar no caminhão -----
    if (dock) {
      dock.addEventListener("dragover", function (e) { if (drag) { e.preventDefault(); dock.classList.add("is-over"); } });
      dock.addEventListener("dragleave", function () { dock.classList.remove("is-over"); });
      dock.addEventListener("drop", function (e) {
        if (!drag) return;
        e.preventDefault();
        dock.classList.remove("is-over"); armar(false);
        tocarAnimacao();
      });
    }

    // ----- soltar em "atribuir a colaborador" -----
    if (dockColab) {
      dockColab.addEventListener("dragover", function (e) { if (drag) { e.preventDefault(); dockColab.classList.add("is-over"); } });
      dockColab.addEventListener("dragleave", function () { dockColab.classList.remove("is-over"); });
      dockColab.addEventListener("drop", function (e) {
        if (!drag) return;
        e.preventDefault();
        dockColab.classList.remove("is-over"); armar(false);
        abrirCarrossel();
      });
    }

    // ----- arrastar no TOQUE (celular) -----
    if ("ontouchstart" in window && dock) {
      var tPress = null, tSX = 0, tSY = 0, tDragging = false, tNb = null;
      var tChip = document.createElement("div");
      tChip.className = "tl-touch-chip"; tChip.style.display = "none";
      document.body.appendChild(tChip);

      function tLimparSel() { var s = window.getSelection && window.getSelection(); if (s && s.rangeCount) { try { s.removeAllRanges(); } catch (x) {} } }
      function tPosChip(t) { tChip.style.left = t.clientX + "px"; tChip.style.top = t.clientY + "px"; }
      function tAlvo(t) {  // 'truck' | 'colab' | null
        tChip.style.display = "none";
        var el = document.elementFromPoint(t.clientX, t.clientY);
        tChip.style.display = "block";
        if (el && el.closest("#truck-dock-nb")) return "truck";
        if (el && el.closest("#dock-colab")) return "colab";
        return null;
      }
      planta.addEventListener("touchstart", function (e) {
        var d = pegarCard(e.target);
        if (!d) return;
        var t = e.touches[0]; tSX = t.clientX; tSY = t.clientY; tNb = d;
        tPress = setTimeout(function () { tIniciar(t); }, 380);
      }, { passive: true });
      planta.addEventListener("touchmove", function (e) {
        if (!tDragging && tPress) {
          var t = e.touches[0];
          if (Math.abs(t.clientX - tSX) > 12 || Math.abs(t.clientY - tSY) > 12) { clearTimeout(tPress); tPress = null; }
        }
      }, { passive: true });
      planta.addEventListener("touchend", function () { if (tPress) { clearTimeout(tPress); tPress = null; } });

      function tIniciar(t) {
        tDragging = true;
        document.body.classList.add("is-arrastando");
        tLimparSel();
        if (navigator.vibrate) { try { navigator.vibrate(15); } catch (x) {} }
        armar(true);
        tChip.textContent = nbLabel(tNb);
        tChip.style.display = "block"; tPosChip(t);
        document.addEventListener("touchmove", tArrastar, { passive: false });
        document.addEventListener("touchend", tSoltar);
      }
      function tArrastar(e) {
        if (!tDragging) return;
        e.preventDefault(); tLimparSel();
        var t = e.touches[0]; tPosChip(t);
        var alvo = tAlvo(t);
        dock.classList.toggle("is-over", alvo === "truck");
        if (dockColab) dockColab.classList.toggle("is-over", alvo === "colab");
      }
      function tSoltar(e) {
        document.removeEventListener("touchmove", tArrastar, { passive: false });
        document.removeEventListener("touchend", tSoltar);
        tDragging = false;
        document.body.classList.remove("is-arrastando");
        tChip.style.display = "none";
        var t = (e.changedTouches && e.changedTouches[0]) || null;
        var alvo = t ? tAlvo(t) : null;
        dock.classList.remove("is-over");
        if (dockColab) dockColab.classList.remove("is-over");
        if (alvo && tNb) {
          drag = tNb;
          armar(false);
          if (alvo === "truck") tocarAnimacao(); else abrirCarrossel();
        } else if (!aberto(destUnits)) {
          armar(false);
        }
        tNb = null;
        tChip.style.display = "none";  // garante esconder (tAlvo reexibe o chip)
      }
    }

    // ----- soltou no caminhão → vai direto escolher o destino -----
    function tocarAnimacao() { abrirDestino(); }

    function abrirOverlay(el) { if (el) { el.classList.add("is-open"); el.setAttribute("aria-hidden", "false"); } }
    function fecharOverlay(el) { if (el) { el.classList.remove("is-open"); el.setAttribute("aria-hidden", "true"); } }
    function aberto(el) { return !!(el && el.classList.contains("is-open")); }
    function abrirDestino() { abrirOverlay(destUnits); }

    // ----- carrossel de colaboradores (atribuir notebook) -----
    function abrirCarrossel() {
      if (!carrossel) return;
      if (nbNomeEl) nbNomeEl.textContent = drag ? ("“" + nbLabel(drag) + "”") : "o notebook";
      if (busca) { busca.value = ""; filtrarColab(""); }
      abrirOverlay(carrossel);
      if (track) track.scrollLeft = 0;
    }
    function filtrarColab(termo) {
      if (!track) return;
      termo = (termo || "").trim().toLowerCase();
      track.querySelectorAll(".colab-card").forEach(function (c) {
        var alvo = c.getAttribute("data-busca") || "";
        c.style.display = (!termo || alvo.indexOf(termo) !== -1) ? "" : "none";
      });
    }
    if (busca) busca.addEventListener("input", function () { filtrarColab(busca.value); });
    document.querySelectorAll("[data-close-colab]").forEach(function (btn) {
      btn.addEventListener("click", function () { fecharOverlay(carrossel); drag = null; });
    });
    if (carrossel) carrossel.addEventListener("click", function (e) {
      if (e.target === carrossel) { fecharOverlay(carrossel); drag = null; }
    });

    if (track) {
      track.addEventListener("click", function (e) {
        // Retirar o notebook de quem já tem → fica triste.
        var rem = e.target.closest(".colab-card__remover");
        if (rem) {
          e.stopPropagation();
          retirarNotebook(rem.getAttribute("data-remover"), rem.closest(".colab-card"), rem.getAttribute("data-nome"));
          return;
        }
        // Atribuir o notebook arrastado a um colaborador livre.
        var card = e.target.closest(".colab-card");
        if (!card) return;
        if (card.getAttribute("data-tem") === "1") {
          toast(card.getAttribute("data-nome") + " já está com um notebook.", true);
          return;
        }
        if (!drag) { toast("Arraste um notebook até “Atribuir a colaborador” primeiro.", true); return; }
        atribuirNotebook(card);
      });
    }

    function atribuirNotebook(card) {
      var body = "notebook=" + encodeURIComponent(drag.pk) +
        "&colaborador=" + encodeURIComponent(card.getAttribute("data-colab"));
      fetch(atribuirUrl, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": token },
        body: body,
      })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          if (res.ok && res.j.ok) {
            // O colaborador sorri e segura o notebook.
            card.classList.remove("av--neutral", "av--sad", "is-livre");
            card.classList.add("av--smile", "av--has-nb", "is-ocupado", "av--festejar");
            toast(res.j.msg || "Notebook alocado.");
            setTimeout(function () { window.location.reload(); }, 1400);
          } else {
            toast((res.j && res.j.erro) || "Não foi possível alocar.", true);
          }
        })
        .catch(function () { toast("Erro de conexão.", true); });
    }

    function retirarNotebook(nbId, card, nome) {
      fetch(removerUrl, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": token },
        body: "notebook=" + encodeURIComponent(nbId),
      })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          if (res.ok && res.j.ok) {
            // Fica triste ao perder o notebook.
            if (card) {
              card.classList.remove("av--smile", "av--has-nb", "is-ocupado");
              card.classList.add("av--sad");
            }
            toast(res.j.msg || ("Notebook retirado de " + (nome || "colaborador") + "."));
            setTimeout(function () { window.location.reload(); }, 1500);
          } else {
            toast((res.j && res.j.erro) || "Não foi possível retirar.", true);
          }
        })
        .catch(function () { toast("Erro de conexão.", true); });
    }

    // ----- escolher a loja de destino -----
    if (destUnits) {
      destUnits.addEventListener("click", function (e) {
        var card = e.target.closest(".tl-unit[data-unidade]");
        if (!card) return;
        destino = { id: card.getAttribute("data-unidade"), nome: card.getAttribute("data-unidade-nome") };
        fecharOverlay(destUnits);
        abrirConfirmacao();
      });
    }
    document.querySelectorAll("[data-close-dest-nb]").forEach(function (btn) {
      btn.addEventListener("click", function () { fecharOverlay(destUnits); drag = null; destino = null; });
    });

    // ----- confirmação -----
    function abrirConfirmacao() {
      if (!drag || !destino) return;
      confirmMsg.innerHTML =
        "Confirmar a transferência do notebook <b>" + esc(nbLabel(drag)) + "</b> " +
        "para a loja <b>" + esc(destino.nome) + "</b>?";
      if (userDest) userDest.value = "";
      if (bitrixInput) bitrixInput.value = "";
      okBtn.disabled = false;
      abrirOverlay(confirmModal);
    }
    function fecharConfirmacao() { fecharOverlay(confirmModal); }

    cancelBtn.addEventListener("click", fecharConfirmacao);
    confirmModal.addEventListener("click", function (e) { if (e.target === confirmModal) fecharConfirmacao(); });

    okBtn.addEventListener("click", function () {
      if (!drag || !destino) return;
      var bitrix = bitrixInput ? bitrixInput.value.trim() : "";
      if (!bitrix) {
        toast("Informe o código da tarefa do Bitrix para concluir a transferência.", true);
        if (bitrixInput) bitrixInput.focus();
        return;
      }
      okBtn.disabled = true;
      var body = "notebook=" + encodeURIComponent(drag.pk) +
        "&unidade_destino=" + encodeURIComponent(destino.id) +
        "&bitrix_task_id=" + encodeURIComponent(bitrix);
      if (userDest && userDest.value.trim()) body += "&usuario_destino=" + encodeURIComponent(userDest.value.trim());
      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": token },
        body: body,
      })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          if (res.ok && res.j.ok && res.j.status === "aplicada") {
            if (res.j.protocolo_url) window.open(res.j.protocolo_url, "_blank");
            toast(res.j.msg || "Transferência realizada.");
            setTimeout(function () { window.location.reload(); }, 1200);
          } else if (res.ok && res.j.ok) {
            fecharConfirmacao();
            toast(res.j.msg || "Solicitação enviada para autorização.");
            setTimeout(function () { window.location.reload(); }, 1500);
          } else {
            okBtn.disabled = false;
            toast((res.j && res.j.erro) || "Não foi possível transferir.", true);
          }
        })
        .catch(function () { okBtn.disabled = false; toast("Erro de conexão.", true); });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      fecharOverlay(confirmModal); fecharOverlay(destUnits); fecharOverlay(carrossel);
    });
  }

  // ---------- Ranking de unidades críticas (hover lista as baias) ----------
  function initRankingUnidades() {
    var canvas = document.getElementById("rank-unidades");
    var dataEl = document.getElementById("rank-unidades-data");
    if (!canvas || !dataEl) return;
    var cfg;
    try { cfg = JSON.parse(dataEl.textContent); } catch (e) { return; }
    if (!cfg.labels || !cfg.labels.length) return;

    var escuro = document.documentElement.classList.contains("dark") ||
                 document.body.classList.contains("dark");
    var corEixo = escuro ? "#9db0a5" : "#5f6f66";
    var corValor = escuro ? "#f0a08f" : "#b4362a";
    var corGrid = escuro ? "rgba(255,255,255,.09)" : "rgba(16,40,27,.12)";

    // Plugin: desenha o número de máquinas críticas acima de cada coluna.
    var rotuloValores = {
      id: "rotuloValores",
      afterDatasetsDraw: function (chart) {
        var ctx = chart.ctx, meta = chart.getDatasetMeta(0);
        ctx.save();
        ctx.font = "700 14px 'Segoe UI', system-ui, sans-serif";
        ctx.fillStyle = corValor;
        ctx.textAlign = "center";
        meta.data.forEach(function (bar, i) {
          ctx.fillText(String(chart.data.datasets[0].data[i]), bar.x, bar.y - 8);
        });
        ctx.restore();
      },
    };

    var tentativas = 0;
    (function build() {
      if (!window.Chart) {
        if (tentativas++ < 25) return setTimeout(build, 200);
        return;
      }
      new window.Chart(canvas.getContext("2d"), {
        type: "bar",
        data: {
          labels: cfg.labels,
          datasets: [{
            label: "Máquinas críticas",
            data: cfg.data,
            // Degradê vertical (do vinho ao coral) por coluna.
            backgroundColor: function (context) {
              var area = context.chart.chartArea;
              if (!area) return "#e0533f";
              var g = context.chart.ctx.createLinearGradient(0, area.bottom, 0, area.top);
              g.addColorStop(0, "#b4362a");
              g.addColorStop(1, "#f0a08f");
              return g;
            },
            hoverBackgroundColor: "#e0533f",
            borderRadius: { topLeft: 10, topRight: 10, bottomLeft: 0, bottomRight: 0 },
            borderSkipped: false,
            maxBarThickness: 70,
            categoryPercentage: 0.62,
          }],
        },
        options: {
          maintainAspectRatio: false,
          layout: { padding: { top: 22 } },
          onClick: function (evt, els) {
            if (els && els.length && cfg.nav[els[0].index]) {
              window.location.href = cfg.nav[els[0].index];
            }
          },
          onHover: function (evt, els) {
            evt.native.target.style.cursor = els && els.length ? "pointer" : "default";
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              padding: 10, displayColors: false,
              callbacks: {
                label: function (ctx) { return ctx.parsed.y + " máquina(s) crítica(s)"; },
                afterBody: function (items) {
                  var lst = (cfg.baias || [])[items[0].dataIndex] || [];
                  if (!lst.length) return [];
                  return ["", "Baias:"].concat(lst.map(function (s) { return "• " + s; }));
                },
              },
            },
          },
          scales: {
            x: { grid: { display: false },
                 ticks: { color: corEixo, font: { size: 13, weight: "600" } } },
            y: { beginAtZero: true,
                 ticks: { precision: 0, color: corEixo, stepSize: 1 },
                 grid: { color: corGrid, drawBorder: false },
                 title: { display: true, text: "máquinas críticas", color: corEixo } },
          },
        },
        plugins: [rotuloValores],
      });
    })();
  }

  // ---------- Prateleira de notebooks: lista + abre o monitor de cada um ----------
  function initShelf() {
    var planta = document.getElementById("mapa-planta");
    var modal = document.getElementById("shelf-modal");
    if (!planta || !modal) return;
    var list = document.getElementById("shelf-modal-list");
    var title = document.getElementById("shelf-modal-title");
    function esc(s) { var d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }
    function fechar() { modal.classList.remove("is-open"); modal.setAttribute("aria-hidden", "true"); }

    function abrirShelf(sh) {
      var id = sh.getAttribute("data-shelf");
      var cont = planta.querySelector('.shelf-baias[data-shelf-list="' + id + '"]');
      list.innerHTML = "";
      if (cont) {
        cont.querySelectorAll(".baia[data-baia]").forEach(function (b) {
          var nome = b.getAttribute("data-nome") || "";
          var marca = b.getAttribute("data-marca") || "";
          var colab = b.getAttribute("data-colaborador") || "";
          var modelo = marca || (colab && colab !== "—" ? colab : "sem modelo");
          var slide = document.createElement("button");
          slide.type = "button";
          slide.className = "shelf-slide";
          slide.innerHTML =
            '<svg class="shelf-slide__svg" viewBox="0 0 120 84" aria-hidden="true">' +
              '<rect class="snb-screen" x="14" y="5" width="92" height="56" rx="4"/>' +
              '<rect class="snb-fill" x="19" y="10" width="82" height="46" rx="2"/>' +
              '<text class="snb-marca" x="60" y="37">' + esc(marca) + "</text>" +
              '<polygon class="snb-base" points="3,61 117,61 120,76 0,76"/>' +
              '<rect class="snb-touch" x="50" y="65" width="20" height="5" rx="2"/>' +
            "</svg>" +
            '<span class="shelf-slide__nome">' + esc(nome) + "</span>" +
            '<span class="shelf-slide__modelo">' + esc(modelo) + "</span>";
          slide.addEventListener("click", function () {
            b.click();  // abre o monitor (initMapa) por cima do carrossel; × fecha
          });
          list.appendChild(slide);
        });
      }
      title.textContent = "Notebooks — " + (sh.getAttribute("data-setor-nome") || "");
      modal.classList.add("is-open"); modal.setAttribute("aria-hidden", "false");
      list.scrollLeft = 0;
    }

    planta.addEventListener("click", function (e) {
      var sh = e.target.closest(".mapa-shelf[data-shelf]");
      if (sh) abrirShelf(sh);
    });

    function rolar(dir) {
      var passo = Math.max(180, Math.round(list.clientWidth * 0.7));
      list.scrollBy({ left: dir * passo, behavior: "smooth" });
    }
    var prev = document.getElementById("shelf-prev");
    var next = document.getElementById("shelf-next");
    if (prev) prev.addEventListener("click", function () { rolar(-1); });
    if (next) next.addEventListener("click", function () { rolar(1); });

    var closeBtn = document.getElementById("shelf-modal-close");
    if (closeBtn) closeBtn.addEventListener("click", fechar);
    modal.addEventListener("click", function (e) { if (e.target === modal) fechar(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") fechar(); });
  }

  // ---------- Notebooks no mapa da loja: clique no card abre o monitor ----------
  function initNotebookTable() {
    document.querySelectorAll(".mapa-setor--notebooks").forEach(function (sec) {
      var lista = sec.querySelector(".shelf-baias");
      sec.addEventListener("click", function (e) {
        var card = e.target.closest(".nb-card[data-shelf-nb]");
        if (!card || !lista) return;
        var idx = parseInt(card.getAttribute("data-shelf-nb"), 10);
        var baias = lista.querySelectorAll(".baia[data-baia]");
        if (baias[idx]) baias[idx].click();  // abre o monitor (initMapa) com is-notebook
      });
    });
  }

  // ---------- Zoom do notebook (clicar no card abre a tela com animação) ----------
  function initNotebookZoom() {
    // TRADUTOR, não painel.
    //
    // Antes existia aqui um popup inteiro (`#nb-zoom`) com animação de tampa
    // de laptop: outro desenho e outro código para a mesma pergunta que o
    // mapa da loja já respondia. O dono viu e reclamou com razão. Agora o
    // mapa de notebooks inclui o mesmo `_zoom.html`, e esta função só converte
    // os dados do cartão para os nomes que o painel espera.
    var root = document.querySelector(".tl-nb .mapa__planta") || document.getElementById("mapa-planta");
    if (!root || !document.querySelector(".tl-nb")) return;
    if (typeof window.mkAbrirZoom !== "function") return;   // painel não está na página

    var zoom = document.getElementById("mapa-zoom");
    var token = (document.querySelector("[name=csrfmiddlewaretoken]") || {}).value || "";
    var termoBtn = document.getElementById("mz-ac-termo");
    var termoNb = null;   // pk do notebook aberto no painel

    root.addEventListener("click", function (e) {
      var card = e.target.closest(".nb-card[data-notebook]");
      if (!card) return;
      e.preventDefault();   // não navega para o admin; abre o painel
      var d = card.dataset;

      // De-para: à esquerda o que o painel lê, à direita o que o cartão tem.
      var falso = { dataset: {
        patrimonio: d.patrimonio || "",
        etiqueta: d.etiqueta || "",
        colaborador: (d.colab && d.colab.trim()) || (d.user && d.user.trim()) || "",
        nome: d.modelo || d.marca || "Notebook",
        status: d.status || "",
        tel: d.tel || "sem",
        so: d.so || "",
        cpu: d.cpu || "",
        placa: d.placa || "",
        ram: d.ram || "",
        disco: d.disco || "",
        gpu: d.gpu || "",
        uptime: d.uptime || "",
        local: d.local || "",
        serial: d.serial || "",
        unidade: d.unidade || "",
        conta: d.conta || "",
        anydesk: d.anydesk || "",
        desempenho: d.desempenho || "",
        classe: d.classe || "",
        diag: d.diag || "",
        edit: d.edit || "",
        // Faz o painel desenhar laptop em vez de monitor.
        pcstatus: "notebook",
        // Sem baia: o painel esconde "abrir chamado", "desativar para troca"
        // e "finalizar reparo", que são fluxos da mesa.
        baia: "", reparo: "", troca: "", chamado: ""
      } };

      window.mkAbrirZoom(falso);

      // Periféricos são da mesa, não do notebook: a faixa sai de cena.
      if (zoom) {
        var perifs = zoom.querySelector(".mzx-perifs");
        if (perifs) perifs.hidden = true;
      }

      // Termo de responsabilidade: só o notebook tem.
      termoNb = d.notebook || null;
      if (termoBtn) {
        termoBtn.hidden = !termoNb;
        termoBtn.disabled = false;
        termoBtn.title = "Gera o termo de responsabilidade deste notebook para impressão";
      }
    });

    if (termoBtn) {
      termoBtn.addEventListener("click", function () {
        if (termoBtn.disabled || !termoNb) return;
        termoBtn.disabled = true;
        fetch("/parque/gerar-termo-notebook/", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": token },
          body: "notebook=" + encodeURIComponent(termoNb),
        })
          .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
          .then(function (res) {
            termoBtn.disabled = false;
            if (res.ok && res.j && res.j.url) {
              window.open(res.j.url, "_blank");
              mkAvisar("Termo gerado.", "success");
            } else {
              mkAvisar((res.j && res.j.erro) || "Não foi possível gerar o termo.", "error");
            }
          })
          .catch(function () {
            termoBtn.disabled = false;
            mkAvisar("Falha de conexão ao gerar o termo.", "error");
          });
      });
    }
  }

  function initMontarCaixa() {
    var form = document.getElementById("cx-form");
    if (!form) return;
    var origemSel = document.getElementById("cx-origem");
    var itens = Array.prototype.slice.call(document.querySelectorAll(".cx-item"));
    var resumo = document.getElementById("cx-resumo");
    var boxCount = document.getElementById("cx-box-count");
    var totalEl = document.getElementById("cx-total");
    var box = document.getElementById("cx-box");
    var montar = document.getElementById("cx-montar");
    var anim = document.getElementById("cx-anim");

    function esc(s) { var d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }
    function inputDe(item) { return item.querySelector('input[type="number"]'); }

    // Mostra só os itens da loja de origem selecionada.
    function filtrarOrigem() {
      var uid = origemSel.value;
      itens.forEach(function (it) {
        var ok = it.getAttribute("data-unidade") === uid;
        it.style.display = ok ? "" : "none";
        if (!ok) { inputDe(it).value = 0; }
      });
      atualizar();
    }

    // Recalcula o resumo da caixa.
    function atualizar() {
      var linhas = [], totalItens = 0, totalUn = 0;
      itens.forEach(function (it) {
        if (it.style.display === "none") return;
        var q = parseInt(inputDe(it).value, 10) || 0;
        it.classList.toggle("is-na-caixa", q > 0);
        if (q > 0) {
          totalItens++; totalUn += q;
          linhas.push('<li><span class="cx-resumo__nome">' + esc(it.getAttribute("data-nome")) +
            '</span><span class="cx-resumo__q">' + q + ' un</span></li>');
        }
      });
      // itens avulsos (fora do estoque) — sempre contam, sem filtro de origem.
      var avList = document.getElementById("cx-avulsos-list");
      if (avList) {
        Array.prototype.slice.call(avList.querySelectorAll(".cx-avulso")).forEach(function (row) {
          var nomeEl = row.querySelector('input[name="avulso_nome"]');
          var qEl = row.querySelector('input[name="avulso_qtd"]');
          var nome = ((nomeEl && nomeEl.value) || "").trim();
          var q = (qEl && parseInt(qEl.value, 10)) || 0;
          row.classList.toggle("is-na-caixa", q > 0 && !!nome);
          if (q > 0 && nome) {
            totalItens++; totalUn += q;
            linhas.push('<li><span class="cx-resumo__nome">' + esc(nome) +
              ' <em class="cx-resumo__tag">avulso</em></span><span class="cx-resumo__q">' + q + ' un</span></li>');
          }
        });
      }
      resumo.innerHTML = linhas.length ? linhas.join("") : '<li class="cx-resumo__vazio">A caixa está vazia.</li>';
      boxCount.textContent = totalItens;
      box.classList.toggle("is-cheia", totalItens > 0);
      totalEl.textContent = totalItens ? (totalItens + " item(ns) · " + totalUn + " unidade(s)") : "";
      montar.disabled = totalItens === 0;
    }

    function pulsarCaixa() {
      box.classList.remove("is-pulse"); void box.offsetWidth; box.classList.add("is-pulse");
    }

    // Botões +/−
    document.querySelectorAll(".cx-step").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var inp = inputDe(btn.closest(".cx-item"));
        var max = parseInt(inp.max, 10) || 0;
        var v = (parseInt(inp.value, 10) || 0) + parseInt(btn.getAttribute("data-step"), 10);
        v = Math.max(0, Math.min(max, v));
        var aumentou = v > (parseInt(inp.value, 10) || 0);
        inp.value = v;
        if (aumentou) pulsarCaixa();
        atualizar();
      });
    });
    document.querySelectorAll(".cx-item input[type=number]").forEach(function (inp) {
      inp.addEventListener("input", atualizar);
    });
    if (origemSel) origemSel.addEventListener("change", filtrarOrigem);

    // ----- itens avulsos (fora do estoque): adicionar / remover / +/- -----
    var avList = document.getElementById("cx-avulsos-list");
    var avAdd = document.getElementById("cx-avulso-add");
    var avTpl = document.getElementById("cx-avulso-tpl");
    if (avAdd && avList && avTpl) {
      avAdd.addEventListener("click", function () {
        avList.appendChild(avTpl.content.cloneNode(true));
        var row = avList.lastElementChild;
        var nomeInp = row.querySelector('input[name="avulso_nome"]');
        if (nomeInp) nomeInp.focus();
        atualizar();
      });
      avList.addEventListener("click", function (e) {
        var step = e.target.closest(".cx-step");
        if (step) {
          var inp = step.parentNode.querySelector('input[type="number"]');
          var d = parseInt(step.getAttribute("data-step"), 10);
          inp.value = Math.max(0, (parseInt(inp.value, 10) || 0) + d);
          if (d > 0) pulsarCaixa();
          atualizar();
          return;
        }
        var x = e.target.closest(".cx-avulso__x");
        if (x) { var r = x.closest(".cx-avulso"); if (r) r.parentNode.removeChild(r); atualizar(); }
      });
      avList.addEventListener("input", atualizar);
      // Protocolo genérico: já começa com uma linha de item avulso pronta.
      if (form.getAttribute("data-generico") === "1" && !avList.querySelector(".cx-avulso")) {
        avAdd.click();
      }
    }

    // Montar: valida, anima e envia.
    montar.addEventListener("click", function () {
      if (montar.disabled) return;
      var destino = document.getElementById("cx-destino");
      if (!destino.value) { destino.focus(); destino.classList.add("is-erro"); return; }
      if (destino.value === origemSel.value) { destino.classList.add("is-erro"); return; }
      destino.classList.remove("is-erro");
      montar.disabled = true;
      if (!anim) { form.submit(); return; }
      anim.classList.add("is-open"); anim.setAttribute("aria-hidden", "false");
      var st = anim.querySelector(".cx-anim__stage");
      st.classList.remove("is-playing"); void st.offsetWidth; st.classList.add("is-playing");
      var txt = document.getElementById("cx-anim-txt");
      [[0, "Separando os itens…"], [900, "Fechando a caixa…"], [1700, "Lacrando e gerando o protocolo…"]]
        .forEach(function (p) { setTimeout(function () { if (txt) txt.textContent = p[1]; }, p[0]); });
      setTimeout(function () { form.submit(); }, 2500);
    });

    // VOLTAR DO NAVEGADOR: o overlay não pode ficar preso.
    //
    // O que acontecia: montar o protocolo abre o véu ("Lacrando e gerando o
    // protocolo…") e envia o formulário. Clicando em voltar, o navegador
    // RESTAURA esta página do cache — com o véu aberto e o botão desabilitado.
    // A tela ficava morta: só o painel de avisos do topo respondia, porque ele
    // vive fora deste nó. Era o "quebro o sistema" que o dono relatou.
    //
    // `pageshow` com `persisted` é o evento que avisa que a página voltou do
    // cache; `popstate` cobre o caso de o navegador não usar o cache.
    function destravar() {
      if (anim) { anim.classList.remove("is-open"); anim.setAttribute("aria-hidden", "true"); }
      montar.disabled = false;
      var st = anim && anim.querySelector(".cx-anim__stage");
      if (st) st.classList.remove("is-playing");
    }
    window.addEventListener("pageshow", function (e) { if (e.persisted) destravar(); });
    window.addEventListener("popstate", destravar);

    filtrarOrigem();
  }

  // ---------- Transferências: selecionar várias + excluir em lote ----------
  function initTransferenciasBulk() {
    var all = document.getElementById("tr-all");
    var btn = document.getElementById("tr-bulk-del");
    var cnt = document.getElementById("tr-bulk-cnt");
    if (!btn) return;
    var bar = btn.closest(".tr-bulkbar");
    function chks() { return Array.prototype.slice.call(document.querySelectorAll(".tr-chk")); }
    function atualizar() {
      var todos = chks();
      var marcados = todos.filter(function (c) { return c.checked; });
      if (cnt) cnt.textContent = marcados.length;
      // Só aparece ao selecionar mais de um (para 1, use o "Excluir" da linha).
      var mostra = marcados.length >= 2;
      if (bar) bar.style.display = mostra ? "" : "none";
      btn.disabled = !mostra;
      if (all) {
        all.checked = todos.length > 0 && marcados.length === todos.length;
        all.indeterminate = marcados.length > 0 && marcados.length < todos.length;
      }
    }
    if (all) all.addEventListener("change", function () {
      chks().forEach(function (c) { c.checked = all.checked; });
      atualizar();
    });
    chks().forEach(function (c) { c.addEventListener("change", atualizar); });
    atualizar();
  }

  // Transferências: barra flutuante (mesma .make-fab-bar das outras telas) que
  // aparece ao MARCAR a caixinha — Autorizar (1 pendente) e Excluir (1+). A
  // autorização abre um modal com os detalhes + campo de observação.
  function initTransferAutorizar() {
    var tbl = document.getElementById("tr-tabela");
    if (!tbl) return;
    var modal = document.getElementById("tr-modal");   // só existe p/ quem pode decidir
    var form = modal && document.getElementById("tr-decide-form");
    var info = modal && document.getElementById("tr-modal-info");
    var ta = modal && document.getElementById("tr-obs");
    var all = document.getElementById("tr-all");
    function chks() { return Array.prototype.slice.call(document.querySelectorAll(".tr-chk")); }
    function marcados() { return chks().filter(function (c) { return c.checked; }); }
    function esc(s) { var d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }

    var bar = document.createElement("div");
    bar.className = "make-fab-bar";
    bar.innerHTML =
      '<span class="make-fab-count"></span>' +
      (modal ? '<button type="button" class="make-fab make-fab--autorizar" hidden>'+mkIco('check')+' Autorizar</button>' : '') +
      '<button type="button" class="make-fab make-fab--excluir">'+mkIco('trash')+' Excluir</button>';
    document.body.appendChild(bar);
    var btnAut = bar.querySelector(".make-fab--autorizar");
    var btnExc = bar.querySelector(".make-fab--excluir");
    var contador = bar.querySelector(".make-fab-count");

    var autUrl = null, negUrl = null;
    function abrirModal(row) {
      var d = row.dataset;
      autUrl = d.aut || null; negUrl = d.neg || null;
      var linhas = [
        "<div><b>" + esc(d.tipo) + "</b></div>",
        "<div>"+mkIco('pin')+" " + esc(d.origem) + " → " + esc(d.destino) + "</div>",
      ];
      if (d.csaida) linhas.push("<div>"+mkIco('user')+" Saída: " + esc(d.csaida) + "</div>");
      if (d.cdest) linhas.push("<div>"+mkIco('user')+" Destino: " + esc(d.cdest) + "</div>");
      info.innerHTML = linhas.join("");
      if (ta) ta.value = "";
      modal.classList.add("is-open"); modal.setAttribute("aria-hidden", "false");
    }
    function fecharModal() { modal.classList.remove("is-open"); modal.setAttribute("aria-hidden", "true"); }
    function decidir(url) { if (!url || !form) return; form.action = url; if (form.requestSubmit) form.requestSubmit(); else form.submit(); }

    function atualizar() {
      var sel = marcados();
      bar.classList.toggle("is-open", sel.length > 0);
      contador.textContent = sel.length + (sel.length > 1 ? " selecionadas" : " selecionada");
      if (btnExc) btnExc.disabled = sel.length < 1;
      if (btnAut) {
        var row = sel.length === 1 ? sel[0].closest("tr") : null;
        btnAut.hidden = !(row && row.classList.contains("tr-row--pend"));   // só p/ 1 pendente
      }
      if (all) {
        var todos = chks();
        all.checked = todos.length > 0 && sel.length === todos.length;
        all.indeterminate = sel.length > 0 && sel.length < todos.length;
      }
    }

    if (all) all.addEventListener("change", function () {
      var v = all.checked; chks().forEach(function (c) { c.checked = v; }); atualizar();
    });
    chks().forEach(function (c) { c.addEventListener("change", atualizar); });

    if (btnExc) btnExc.addEventListener("click", function () {
      if (!marcados().length) return;
      var f = document.getElementById("tr-bulk-form");
      if (!f) return;
      if (f.requestSubmit) f.requestSubmit(); else f.submit();   // dispara o confirm() do form
    });
    if (btnAut) btnAut.addEventListener("click", function () {
      var sel = marcados();
      if (sel.length !== 1) return;
      var row = sel[0].closest("tr");
      if (row && row.classList.contains("tr-row--pend")) abrirModal(row);
    });

    if (modal) {
      var x = document.getElementById("tr-modal-x");
      var cancel = document.getElementById("tr-modal-cancel");
      var aut = document.getElementById("tr-modal-aut");
      var neg = document.getElementById("tr-modal-negar");
      if (x) x.addEventListener("click", fecharModal);
      if (cancel) cancel.addEventListener("click", fecharModal);
      if (aut) aut.addEventListener("click", function () { decidir(autUrl); });
      if (neg) neg.addEventListener("click", function () { decidir(negUrl); });
      modal.addEventListener("click", function (e) { if (e.target === modal) fecharModal(); });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && modal.classList.contains("is-open")) fecharModal();
      });
    }

    atualizar();
  }

  // Central de Ajuda: destaca no índice a seção que está em foco ao rolar.
  function initAjudaToc() {
    var toc = document.querySelector(".ajuda__toc");
    if (!toc) return;
    var links = Array.prototype.slice.call(toc.querySelectorAll('a[href^="#"]'));
    var porId = {};
    var itens = [];  // {a, el} em ordem do documento
    links.forEach(function (a) {
      var el = document.getElementById(a.getAttribute("href").slice(1));
      if (el) { porId[a.getAttribute("href").slice(1)] = a; itens.push({ a: a, el: el }); }
    });
    if (!itens.length) return;

    function ativar(a) {
      links.forEach(function (l) { l.classList.toggle("is-active", l === a); });
    }

    function secaoAtual() {
      var doc = document.documentElement;
      var vh = window.innerHeight;
      var alturaDoc = doc.scrollHeight || document.body.scrollHeight;
      var ateFim = alturaDoc - (window.scrollY + vh);  // px até o fim da página
      // Perto do fim, a linha de referência DESCE (0,28 → ~0,85 da tela) para que
      // as seções curtas do rodapé sejam selecionadas uma a uma (sem "pular").
      var frac = 0.28;
      if (ateFim < vh) frac = 0.28 + (1 - Math.max(ateFim, 0) / vh) * 0.55;
      var linha = vh * frac;
      var escolhido = itens[0].a;
      for (var i = 0; i < itens.length; i++) {
        if (itens[i].el.getBoundingClientRect().top - linha <= 0) escolhido = itens[i].a;
        else break;
      }
      return escolhido;
    }

    var agendado = false;
    function aoRolar() {
      if (agendado) return;
      agendado = true;
      window.requestAnimationFrame(function () { ativar(secaoAtual()); agendado = false; });
    }
    window.addEventListener("scroll", aoRolar, { passive: true });
    window.addEventListener("resize", aoRolar);
    links.forEach(function (a) { a.addEventListener("click", function () { ativar(a); }); });

    // estado inicial: hash da URL ou cálculo pela posição atual.
    ativar(porId[(location.hash || "").slice(1)] || secaoAtual());
  }

  // Tabelas do parque: clicar no cabeçalho ORDENA (asc → desc → original).
  function initTabelaSort() {
    document.querySelectorAll(".tab-tabela").forEach(function (tabela) {
      var tbody = tabela.querySelector("tbody");
      if (!tbody) return;
      var ths = Array.prototype.slice.call(tabela.querySelectorAll("thead th"));
      var original = Array.prototype.slice.call(tbody.querySelectorAll("tr.tab-row"));
      function celTexto(tr, idx) {
        var td = tr.children[idx];
        return td ? (td.textContent || "").trim() : "";
      }
      ths.forEach(function (th, idx) {
        if (th.classList.contains("tab-col-chk")) return;  // pula a coluna de seleção
        th.classList.add("tab-th-sort");
        th.addEventListener("click", function () {
          var estado = th.getAttribute("data-sort") || "none";
          var prox = estado === "none" ? "asc" : (estado === "asc" ? "desc" : "none");
          ths.forEach(function (o) { o.removeAttribute("data-sort"); });
          if (prox !== "none") th.setAttribute("data-sort", prox);
          if (prox === "none") {
            original.forEach(function (r) { tbody.appendChild(r); });
            return;
          }
          var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr.tab-row"));
          rows.sort(function (a, b) {
            var ca = celTexto(a, idx), cb = celTexto(b, idx);
            var na = parseFloat(ca.replace(/[^0-9.,-]/g, "").replace(",", "."));
            var nb = parseFloat(cb.replace(/[^0-9.,-]/g, "").replace(",", "."));
            var cmp = (!isNaN(na) && !isNaN(nb) && ca !== "" && cb !== "")
              ? na - nb
              : ca.localeCompare(cb, "pt", { sensitivity: "base", numeric: true });
            return prox === "asc" ? cmp : -cmp;
          });
          rows.forEach(function (r) { tbody.appendChild(r); });
        });
      });
    });
  }

  // Busca do mapa: filtra os cards por NS / patrimônio / nome / colaborador / specs.
  // Client-side, esconde cards e recolhe setores/unidades sem match. Vale em TODOS os mapas.
  function initMapaBusca() {
    var input = document.getElementById("mapa-busca");
    var planta = document.getElementById("mapa-planta");
    if (!input || !planta) return;
    var limpar = document.getElementById("mapa-busca-x");
    var vazio = document.getElementById("mapa-busca-vazio");

    // Atributos considerados (nome, colaborador/usuário, patrimônio, nº série, marca/modelo, specs, status, unidade).
    var ATTRS = ["nome", "colaborador", "user", "patrimonio", "serial", "marca", "modelo",
                 "cpu", "ram", "disco", "so", "status", "unidade", "classe"];

    function norm(s) {
      return (s || "").toString().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    }

    // Cards reais (ignora os clones ocultos em [hidden], ex.: shelf de notebooks).
    var cards = [].slice.call(
      planta.querySelectorAll(".baia[data-baia], .baia--notebook, .nb-card")
    ).filter(function (c) { return !c.closest("[hidden]"); });
    cards.forEach(function (c) {
      var partes = [];
      ATTRS.forEach(function (a) { var v = c.getAttribute("data-" + a); if (v) partes.push(v); });
      partes.push(c.textContent || "");
      c._busca = norm(partes.join(" "));
    });

    var addBtns = [].slice.call(planta.querySelectorAll(".baia--add"));
    var setores = [].slice.call(planta.querySelectorAll(".mapa-setor"));
    var unidades = [].slice.call(planta.querySelectorAll(".mapa-unidade"));
    var VIS_CARD = ".baia[data-baia]:not(.mapa-hit-off), .baia--notebook:not(.mapa-hit-off), .nb-card:not(.mapa-hit-off)";

    // Filtro rápido (barra de saúde): predicado combinado (AND) com a busca por texto.
    var quickFk = null;
    // Filtro por CARGO (dropdown client-side) — casado com data-cargo do card.
    var cargoSel = document.getElementById("mapa-cargo-sel");
    function cargoOk(c) {
      if (!cargoSel || !cargoSel.value) return true;
      return norm(c.getAttribute("data-cargo")) === norm(cargoSel.value);
    }
    function quickOk(c) {
      if (!quickFk) return true;
      var i = quickFk.indexOf(":"), kind = quickFk.slice(0, i), val = quickFk.slice(i + 1);
      if (kind === "cl") return c.getAttribute("data-classe") === val;
      if (kind === "tp") return c.getAttribute("data-tipo") === val;
      if (kind === "at") {
        var empty = c.getAttribute("data-tipo") === "sem_pc";
        if (val === "critico") return c.getAttribute("data-classe") === "Crítico";
        if (val === "sem_tel") return !empty && c.getAttribute("data-tel") !== "ativo";
        if (val === "prev") { var p = c.getAttribute("data-prev"); return p === "vencida" || p === "pendente"; }
      }
      return true;
    }

    function aplicar() {
      var q = norm(input.value.trim());
      var active = !!q || !!quickFk || !!(cargoSel && cargoSel.value);
      if (limpar) limpar.hidden = !q;
      var achou = 0;
      cards.forEach(function (c) {
        var ok = (!q || c._busca.indexOf(q) !== -1) && quickOk(c) && cargoOk(c);
        c.classList.toggle("mapa-hit-off", !ok);
        if (ok) achou++;
      });
      addBtns.forEach(function (b) { b.classList.toggle("mapa-hit-off", active); });
      setores.forEach(function (s) {
        s.classList.toggle("mapa-hit-off", active && !s.querySelector(VIS_CARD));
      });
      unidades.forEach(function (u) {
        u.classList.toggle("mapa-hit-off", active && !u.querySelector(".mapa-setor:not(.mapa-hit-off)"));
      });
      if (vazio) vazio.hidden = !(active && achou === 0);
    }

    input.addEventListener("input", aplicar);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { input.value = ""; setQuick(null); }
    });
    if (limpar) limpar.addEventListener("click", function () {
      input.value = ""; aplicar(); input.focus();
    });

    // Chips da barra de saúde = filtros rápidos (1 clique; clicar de novo limpa).
    var chips = [].slice.call(document.querySelectorAll(".pq-chip"));
    var pqClear = document.getElementById("pq-clear");
    function setQuick(fk) {
      quickFk = fk;
      chips.forEach(function (ch) { ch.classList.toggle("is-active", ch.getAttribute("data-fk") === fk); });
      if (pqClear) pqClear.hidden = !fk;
      aplicar();
    }
    chips.forEach(function (ch) {
      ch.addEventListener("click", function () {
        var fk = ch.getAttribute("data-fk");
        setQuick(quickFk === fk ? null : fk);
      });
    });
    if (pqClear) pqClear.addEventListener("click", function () { setQuick(null); });
    if (cargoSel) cargoSel.addEventListener("change", aplicar);
  }

  // Pré-visualização (lightbox) de um File local — imagem ou PDF — antes de enviar.
  function dzPreview(file) {
    var ext = (file.name.split(".").pop() || "").toLowerCase();
    var ov = document.getElementById("dz-preview");
    if (!ov) {
      ov = document.createElement("div");
      ov.id = "dz-preview"; ov.className = "dz-preview";
      ov.innerHTML = '<div class="dz-preview__box">' +
        '<div class="dz-preview__bar"><span class="dz-preview__cap"></span>' +
        '<button type="button" class="dz-preview__x" aria-label="Fechar">×</button></div>' +
        '<div class="dz-preview__body"></div></div>';
      document.body.appendChild(ov);
      var close = function () {
        ov.classList.remove("is-open");
        var u = ov.getAttribute("data-url"); if (u) { URL.revokeObjectURL(u); ov.removeAttribute("data-url"); }
        ov.querySelector(".dz-preview__body").innerHTML = "";
      };
      ov.querySelector(".dz-preview__x").addEventListener("click", close);
      ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && ov.classList.contains("is-open")) close();
      });
    }
    var prev = ov.getAttribute("data-url"); if (prev) URL.revokeObjectURL(prev);
    var url = URL.createObjectURL(file);
    ov.setAttribute("data-url", url);
    ov.querySelector(".dz-preview__cap").textContent = file.name;
    var body = ov.querySelector(".dz-preview__body");
    if (["jpg", "jpeg", "png", "gif", "webp"].indexOf(ext) !== -1) {
      body.innerHTML = '<img alt="pré-visualização">';
      body.querySelector("img").src = url;
    } else if (ext === "pdf") {
      body.innerHTML = '<iframe title="pré-visualização"></iframe>';
      body.querySelector("iframe").src = url;
    } else {
      body.innerHTML = '<a class="chd-btn" target="_blank" rel="noopener">Abrir arquivo</a>';
      body.querySelector("a").href = url;
    }
    ov.classList.add("is-open");
  }

  // Dropzone reutilizável: arrastar/soltar, vários arquivos, remover com ×.
  // Usa DataTransfer para reconstruir o FileList (input.files é read-only).
  function initDropzone() {
    document.querySelectorAll("[data-dz]").forEach(function (dz) {
      var input = dz.querySelector(".dz-input");
      var drop = dz.querySelector("[data-dz-drop]");
      var list = dz.querySelector("[data-dz-list]");
      if (!input || !drop || typeof DataTransfer === "undefined") return;
      var dt = new DataTransfer();

      function render() {
        if (!list) return;
        list.innerHTML = "";
        Array.prototype.forEach.call(dt.files, function (f, i) {
          var li = document.createElement("li");
          li.className = "dz-item";
          var name = document.createElement("button");
          name.type = "button"; name.className = "dz-item__name";
          name.title = "Clique para pré-visualizar"; name.textContent = f.name;
          name.addEventListener("click", function () { dzPreview(f); });
          var x = document.createElement("button");
          x.type = "button"; x.className = "dz-item__x"; x.title = "Remover"; x.textContent = "×";
          x.addEventListener("click", function () { remove(i); });
          li.appendChild(name); li.appendChild(x); list.appendChild(li);
        });
      }
      function sync() { input.files = dt.files; render(); }
      function add(files) {
        if (!input.multiple) {
          // Campo de 1 arquivo: o novo substitui o anterior.
          dt = new DataTransfer();
          if (files.length) dt.items.add(files[0]);
        } else {
          Array.prototype.forEach.call(files, function (f) { dt.items.add(f); });
        }
        sync();
      }
      function remove(i) {
        var keep = new DataTransfer();
        Array.prototype.forEach.call(dt.files, function (f, j) { if (j !== i) keep.items.add(f); });
        dt = keep; sync();
      }

      drop.addEventListener("click", function () { input.click(); });
      input.addEventListener("change", function () { add(input.files); });
      ["dragenter", "dragover"].forEach(function (ev) {
        dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.add("is-over"); });
      });
      ["dragleave", "dragend", "drop"].forEach(function (ev) {
        dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.remove("is-over"); });
      });
      dz.addEventListener("drop", function (e) {
        if (e.dataTransfer && e.dataTransfer.files.length) add(e.dataTransfer.files);
      });
    });
  }

  // Filtro (Unidade única + Setor multi) com dropdowns customizados de vidro.
  function initFiltroDropdowns() {
    var dds = document.querySelectorAll("[data-mkdd]");
    if (!dds.length) return;

    function fecharTodos() {
      document.querySelectorAll("[data-mkdd-panel]").forEach(function (p) { p.setAttribute("hidden", ""); });
      document.querySelectorAll("[data-mkdd-btn]").forEach(function (b) { b.setAttribute("aria-expanded", "false"); });
    }

    dds.forEach(function (dd) {
      var btn = dd.querySelector("[data-mkdd-btn]");
      var panel = dd.querySelector("[data-mkdd-panel]");
      if (!btn || !panel) return;
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var abrir = panel.hasAttribute("hidden");
        fecharTodos();
        if (abrir) { panel.removeAttribute("hidden"); btn.setAttribute("aria-expanded", "true"); }
      });
      panel.addEventListener("click", function (e) { e.stopPropagation(); });
    });
    document.addEventListener("click", fecharTodos);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") fecharTodos(); });

    // Setor com multi-seleção: "Todos" x itens, e "Aplicar" monta a URL.
    var multi = document.querySelector("[data-mkdd-multi]");
    if (multi) {
      var all = multi.querySelector("[data-mkdd-all]");
      var checks = multi.querySelectorAll('input[name="setor"]');
      if (all) {
        all.addEventListener("change", function () {
          if (all.checked) checks.forEach(function (c) { c.checked = false; });
        });
      }
      checks.forEach(function (c) {
        c.addEventListener("change", function () { if (c.checked && all) all.checked = false; });
      });
      var aplicar = multi.querySelector("[data-mkdd-apply]");
      if (aplicar) {
        aplicar.addEventListener("click", function () {
          var bar = document.querySelector(".flt-bar");
          var uni = bar ? (bar.getAttribute("data-uni") || "") : "";
          var keep = bar ? (bar.getAttribute("data-keep") || "") : "";
          var parts = [];
          if (uni) parts.push("unidade=" + encodeURIComponent(uni));
          multi.querySelectorAll('input[name="setor"]:checked').forEach(function (c) {
            parts.push("setor=" + encodeURIComponent(c.value));
          });
          if (keep) parts.push(keep);
          window.location.href = "?" + parts.join("&");
        });
      }
    }
  }

  // Preventiva: modal de concluir (descrição + checklist) + overlay do dia
  // (carrossel arrastável de "telas" das máquinas).
  function initPreventiva() {
    var dlg = document.getElementById("pv-concluir");
    var day = document.getElementById("pv-day");
    if (!dlg && !day) return;

    function abrirConcluir(kind, pk, nome) {
      if (!dlg) return;
      dlg.querySelector("#pv-kind").value = kind || "";
      dlg.querySelector("#pv-pk").value = pk || "";
      dlg.querySelector("#pv-dlg-maq").textContent = nome || "";
      dlg.querySelectorAll('input[name="checklist"]').forEach(function (c) { c.checked = true; });
      var ta = dlg.querySelector("#pv-desc"); if (ta) ta.value = "";
      dlg.removeAttribute("hidden");
      document.body.classList.add("pv-lock");
    }
    function fecharConcluir() { if (dlg) { dlg.setAttribute("hidden", ""); document.body.classList.remove("pv-lock"); } }

    // Delegação: qualquer [data-pv-open] (lista, tabela e cards do carrossel).
    document.addEventListener("click", function (e) {
      var t = e.target.closest && e.target.closest("[data-pv-open]");
      if (t) { e.preventDefault(); e.stopPropagation(); abrirConcluir(t.getAttribute("data-kind"), t.getAttribute("data-pk"), t.getAttribute("data-nome")); }
    });
    if (dlg) dlg.querySelectorAll("[data-pv-close]").forEach(function (b) { b.addEventListener("click", fecharConcluir); });

    if (!day) {
      document.addEventListener("keydown", function (e) { if (e.key === "Escape") fecharConcluir(); });
      return;
    }

    // --- Overlay do dia: carrossel com os CARDS REAIS das máquinas ---
    // Os cards ficam num "store" oculto (#pv-cards) por dia; ao abrir, clonamos
    // para o carrossel. Como os cards são `.baia`, o clique abre o MESMO monitor
    // do mapa (initMapa delega o clique em #pv-day-car).
    var car = day.querySelector("#pv-day-car");
    var tit = day.querySelector("#pv-day-tit");
    var store = document.getElementById("pv-cards");
    function abrirDia(cell) {
      var key = cell.getAttribute("data-diakey") || "";
      var src = store ? store.querySelector('[data-daycards="' + key + '"]') : null;
      car.innerHTML = src ? src.innerHTML : "";
      car.scrollLeft = 0;
      tit.textContent = "Preventivas · " + (cell.getAttribute("data-dia") || "");
      day.removeAttribute("hidden");
      document.body.classList.add("pv-lock");
    }
    function fecharDia() { day.setAttribute("hidden", ""); document.body.classList.remove("pv-lock"); }

    document.querySelectorAll("[data-cal-cell]").forEach(function (cell) {
      cell.addEventListener("click", function () { abrirDia(cell); });
      cell.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); abrirDia(cell); } });
    });
    day.querySelectorAll("[data-pvday-close]").forEach(function (b) { b.addEventListener("click", fecharDia); });

    // Setas de deslizar.
    day.querySelectorAll("[data-pv-scroll]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var dir = btn.getAttribute("data-pv-scroll") === "prev" ? -1 : 1;
        if (car) car.scrollBy({ left: dir * Math.max(280, car.clientWidth * 0.8), behavior: "smooth" });
      });
    });

    // Arrastar p/ o lado (drag-to-scroll). Os cards são draggable → cancelamos o
    // drag nativo e, se houve arrasto, cancelamos o clique (não abrir o monitor sem querer).
    if (car) {
      var down = false, moved = false, sx = 0, sl = 0;
      car.addEventListener("dragstart", function (e) { e.preventDefault(); });
      car.addEventListener("mousedown", function (e) { down = true; moved = false; sx = e.pageX; sl = car.scrollLeft; });
      window.addEventListener("mouseup", function () { down = false; car.classList.remove("is-drag"); });
      car.addEventListener("mousemove", function (e) {
        if (!down) return;
        if (Math.abs(e.pageX - sx) > 4) { moved = true; car.classList.add("is-drag"); }
        if (moved) { e.preventDefault(); car.scrollLeft = sl - (e.pageX - sx); }
      });
      car.addEventListener("click", function (e) { if (moved) { e.preventDefault(); e.stopPropagation(); moved = false; } }, true);
    }
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") { fecharDia(); fecharConcluir(); } });
  }

  // Painel de TAREFAS (saúde): modal de Concluir / Dispensar.
  function initTarefas() {
    var dlg = document.getElementById("tf-modal");
    if (!dlg) return;
    var idIn = dlg.querySelector("#tf-id");
    var acaoIn = dlg.querySelector("#tf-acao");
    var maq = dlg.querySelector("#tf-dlg-maq");
    var tit = dlg.querySelector("#tf-dlg-tit");
    var ico = dlg.querySelector("#tf-dlg-ico");
    var submit = dlg.querySelector("#tf-submit");
    var obs = dlg.querySelector("#tf-obs");

    function abrir(id, acao, nome) {
      idIn.value = id || "";
      acaoIn.value = acao || "";
      if (obs) obs.value = "";
      var dispensar = acao === "dispensar";
      var SVG_X = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/></svg>';
      var SVG_OK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';
      tit.textContent = dispensar ? "Dispensar tarefa" : "Concluir tarefa";
      if (ico) ico.innerHTML = dispensar ? SVG_X : SVG_OK;
      if (submit) submit.innerHTML = (dispensar ? SVG_X + " Dispensar" : SVG_OK + " Concluir");
      if (maq) maq.textContent = nome || "";
      dlg.removeAttribute("hidden");
      document.body.classList.add("pv-lock");
    }
    function fechar() { dlg.setAttribute("hidden", ""); document.body.classList.remove("pv-lock"); }

    document.addEventListener("click", function (e) {
      var t = e.target.closest && e.target.closest("[data-tf-open]");
      if (t) {
        e.preventDefault();
        abrir(t.getAttribute("data-id"), t.getAttribute("data-acao"), t.getAttribute("data-nome"));
      }
    });
    dlg.querySelectorAll("[data-tf-close]").forEach(function (b) { b.addEventListener("click", fechar); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") fechar(); });
  }

  // Modal de ADIAR preventiva (nova data + justificativa).
  function initAdiar() {
    var dlg = document.getElementById("adiar-modal");
    if (!dlg) return;
    var kindIn = dlg.querySelector("#adiar-kind");
    var pkIn = dlg.querySelector("#adiar-pk");
    var maq = dlg.querySelector("#adiar-maq");
    var data = dlg.querySelector("#adiar-data");
    var just = dlg.querySelector("#adiar-just");

    function abrir(kind, pk, nome) {
      kindIn.value = kind || "";
      pkIn.value = pk || "";
      if (just) just.value = "";
      if (data) data.value = "";
      if (maq) maq.textContent = nome || "";
      dlg.removeAttribute("hidden");
      document.body.classList.add("pv-lock");
    }
    function fechar() { dlg.setAttribute("hidden", ""); document.body.classList.remove("pv-lock"); }

    document.addEventListener("click", function (e) {
      var t = e.target.closest && e.target.closest("[data-adiar-open]");
      if (t) {
        e.preventDefault();
        abrir(t.getAttribute("data-kind"), t.getAttribute("data-pk"), t.getAttribute("data-nome"));
      }
    });
    dlg.querySelectorAll("[data-adiar-close]").forEach(function (b) { b.addEventListener("click", fechar); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") fechar(); });
  }

  // "Ver máquina" (painel de Tarefas) → dispara o clique no card oculto p/ abrir o zoom.
  function initVerMaquina() {
    var store = document.getElementById("tf-cards");
    if (!store) return;
    document.addEventListener("click", function (e) {
      var btn = e.target.closest && e.target.closest("[data-ver]");
      if (!btn) return;
      e.preventDefault();
      var wrap = store.querySelector('[data-verkey="' + btn.getAttribute("data-ver") + '"]');
      var baia = wrap && wrap.querySelector(".baia");
      if (baia) baia.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
  }

  // Orçamentos: modais Ver detalhes / Negar (com motivo).
  function initOrcamentos() {
    var ver = document.getElementById("orc-ver");
    var neg = document.getElementById("orc-negar");
    if (!ver && !neg) return;
    function abrirVer(b) {
      function set(id, v) { var el = document.getElementById(id); if (el) el.textContent = v || "—"; }
      set("orc-ver-tit", b.getAttribute("data-titulo"));
      set("orc-ver-valor", b.getAttribute("data-valor"));
      set("orc-ver-forn", b.getAttribute("data-fornecedor"));
      set("orc-ver-sol", b.getAttribute("data-solicitante"));
      set("orc-ver-desc", b.getAttribute("data-desc") || "Sem descrição.");
      var link = document.getElementById("orc-ver-link");
      var url = b.getAttribute("data-link");
      if (link) { if (url) { link.href = url; link.hidden = false; } else { link.hidden = true; } }
      ver.removeAttribute("hidden"); document.body.classList.add("pv-lock");
    }
    function abrirNeg(b) {
      var t = document.getElementById("orc-negar-tit");
      if (t) t.textContent = b.getAttribute("data-titulo") || "";
      var form = document.getElementById("orc-negar-form");
      if (form) form.action = "/orcamentos/" + b.getAttribute("data-pk") + "/negar/";
      var ta = document.getElementById("orc-negar-motivo"); if (ta) ta.value = "";
      neg.removeAttribute("hidden"); document.body.classList.add("pv-lock");
    }
    function fechar() {
      if (ver) ver.setAttribute("hidden", "");
      if (neg) neg.setAttribute("hidden", "");
      document.body.classList.remove("pv-lock");
    }
    document.addEventListener("click", function (e) {
      var v = e.target.closest && e.target.closest("[data-orc-ver]");
      if (v) { e.preventDefault(); abrirVer(v); return; }
      var n = e.target.closest && e.target.closest("[data-orc-negar]");
      if (n) { e.preventDefault(); abrirNeg(n); return; }
      var c = e.target.closest && e.target.closest("[data-orc-close]");
      if (c) { e.preventDefault(); fechar(); }
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") fechar(); });
  }

  // Gráfico de desempenho do usuário (boas-vindas da preventiva).
  function initPreventivaChart() {
    var canvas = document.getElementById("pv-chart");
    var raw = document.getElementById("pv-chart-data");
    if (!canvas || !raw) return;
    var cfg;
    try { cfg = JSON.parse(raw.textContent); } catch (e) { return; }
    var tentativas = 0;
    (function build() {
      if (!window.Chart) {
        if (tentativas++ < 25) return setTimeout(build, 200);
        return;
      }
      new window.Chart(canvas.getContext("2d"), {
        type: "bar",
        data: {
          labels: cfg.labels,
          datasets: [{
            label: "Pontos",
            data: cfg.data,
            backgroundColor: function (context) {
              var area = context.chart.chartArea;
              if (!area) return "#00a651";
              var g = context.chart.ctx.createLinearGradient(0, area.bottom, 0, area.top);
              g.addColorStop(0, "#00a651");
              g.addColorStop(1, "#7bc62d");
              return g;
            },
            hoverBackgroundColor: "#00c060",
            borderRadius: { topLeft: 8, topRight: 8, bottomLeft: 0, bottomRight: 0 },
            borderSkipped: false,
            maxBarThickness: 46,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false }, tooltip: { enabled: true } },
          scales: {
            y: { beginAtZero: true, ticks: { precision: 0 }, grid: { display: true } },
            x: { grid: { display: false } },
          },
        },
      });
    })();
  }

  // Cada init roda dentro de `seguro()`. Antes eram ~40 chamadas cruas em
  // sequência: se UMA lançasse, todas as seguintes morriam com ela — e o
  // controle do menu, que estava no fim da fila, era a vítima. O erro agora
  // fica isolado no widget dele e aparece no console para ser corrigido.
  //
  // A ordem também mudou: initSidebarCollapse é a PRIMEIRA. Navegar pelo
  // sistema não pode depender de nenhum widget de tela funcionar.
  function seguro(nome, fn) {
    try { fn(); }
    catch (e) { console.error("[ITAM] falhou em " + nome + ":", e); }
  }

  function init() {
    seguro("initSidebarCollapse", initSidebarCollapse);
    seguro("initVoltarSoNasSubtelas", initVoltarSoNasSubtelas);
    seguro("initVoltarNoTopo", initVoltarNoTopo);
    // initBuscaGaveta está FORA da fila. Ela transformava a busca da gaveta
    // numa lupa de 40px que expandia ao clique. O dono viu e mandou trocar:
    // "quero um campo de pesquisa meio que junto do perfil, tudo em um lugar
    // só". Agora o campo é permanente e colado no cartão do usuário (§24 do
    // make-m3.css). A função fica no arquivo: religar é uma linha aqui.
    // initBuscaUnica está FORA da fila de propósito. Ele agrupava Unidade e
    // Setor num popup dentro do campo de busca — pedido do dono numa mensagem,
    // e desfeito na seguinte, quando ele mandou a referência de layout: lá os
    // dois seletores aparecem, visíveis, dentro do cartão da faixa. Com o
    // cartão em volta a linha não fica mais poluída, que era o motivo do popup.
    // A função fica no arquivo: religar é acrescentar uma linha aqui.
    seguro("initTopoUnico", initTopoUnico);
    // initAvatarNoTopo está FORA da fila. Explicação abaixo, na função — em
    // resumo: mover o bloco quebra o menu da conta, e é lá que mora o "Sair".
    seguro("initAcessoNegado", initAcessoNegado);
    seguro("initPasswordToggles", initPasswordToggles);
    seguro("initFab", initFab);
    seguro("initMapa", initMapa);
    seguro("initMapaDnD", initMapaDnD);
    seguro("initMapaTouch", initMapaTouch);
    seguro("initMapaBusca", initMapaBusca);
    seguro("initDropzone", initDropzone);
    seguro("initChartNav", initChartNav);
    seguro("initScoreExplorer", initScoreExplorer);
    seguro("initTabelaDispositivos", initTabelaDispositivos);
    seguro("initTabelaSort", initTabelaSort);
    seguro("initReparoPecaCampos", initReparoPecaCampos);
    seguro("initPatrimonioPreview", initPatrimonioPreview);
    seguro("initTransferenciaAutofill", initTransferenciaAutofill);
    seguro("initTransferLojas", initTransferLojas);
    seguro("initTransferNotebooks", initTransferNotebooks);
    seguro("initRankingUnidades", initRankingUnidades);
    seguro("initShelf", initShelf);
    seguro("initNotebookTable", initNotebookTable);
    seguro("initNotebookZoom", initNotebookZoom);
    seguro("initMontarCaixa", initMontarCaixa);
    seguro("initTransferenciasBulk", initTransferenciasBulk);
    seguro("initTransferAutorizar", initTransferAutorizar);
    seguro("initSidebarBadges", initSidebarBadges);
    seguro("initAjudaToc", initAjudaToc);
    seguro("initFiltroDropdowns", initFiltroDropdowns);
    seguro("initCalendarioFiltro", initCalendarioFiltro);
    // Depois do initVoltarNoTopo, para medir a barra já no estado final.
    seguro("initTopoVazio", initTopoVazio);
    seguro("initTemaIcones", initTemaIcones);
    seguro("initAgendaTopo", initAgendaTopo);
    seguro("initFormularioAdmin", initFormularioAdmin);
    seguro("initFonteDosGraficos", initFonteDosGraficos);
    seguro("initSetorPopup", initSetorPopup);
    seguro("initFiltrarPopup", initFiltrarPopup);
    seguro("initPreventiva", initPreventiva);
    seguro("initTarefas", initTarefas);
    seguro("initAdiar", initAdiar);
    seguro("initPreventivaChart", initPreventivaChart);
    seguro("initVerMaquina", initVerMaquina);
    seguro("initOrcamentos", initOrcamentos);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
