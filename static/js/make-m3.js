/* =============================================================================
   make-m3.js — comportamento de movimento do Material Design 3.

   Duas coisas que CSS sozinho não faz:
     1. RIPPLE: o círculo que cresce a partir do ponto exato do clique. É a
        assinatura tátil do Material — sem ele, o botão parece só mudar de cor.
     2. TOP APP BAR "on scroll": no M3 a barra superior sai de `surface` e passa
        a `surface-container` quando a página rola, para separar do conteúdo sem
        precisar de sombra ou borda permanente.

   Delegação de evento: um listener no documento cobre tudo, inclusive o que o
   próprio sistema injeta depois (barra flutuante, cartões do kanban, modais).

   Respeita `prefers-reduced-motion`: com movimento reduzido, o ripple não roda.
   ========================================================================== */

(function () {
  "use strict";

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else {
    iniciar();
  }

  function iniciar() {
    var semMovimento = window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    /* ------------------------------------------------------------- ripple */

    // Onde o ripple faz sentido: superfície que responde ao toque.
    var ALVOS = [
      ".pvx-btn", ".make-btn", ".make-fab", ".mkauth__btn", ".mkasst__abrir",
      "#main .button", "#main input[type=submit]", "#main button[type=submit]",
      "#nav-sidebar-apps ol li a", ".estoque-card", ".kanban-card",
      ".make-loja", ".mkasst__sug button", ".mkpro-chip", ".md-st"
    ].join(",");

    if (!semMovimento) {
      document.addEventListener("pointerdown", function (e) {
        var alvo = e.target.closest && e.target.closest(ALVOS);
        if (!alvo || alvo.disabled) return;

        // O ripple precisa de um contêiner que recorte: garante isso sem
        // quebrar layout de quem já é `position: static`.
        var estilo = getComputedStyle(alvo);
        if (estilo.position === "static") alvo.style.position = "relative";
        if (estilo.overflow === "visible") alvo.style.overflow = "hidden";

        var r = alvo.getBoundingClientRect();
        // Diâmetro = duas vezes a maior distância do clique até um canto.
        var dx = Math.max(e.clientX - r.left, r.right - e.clientX);
        var dy = Math.max(e.clientY - r.top, r.bottom - e.clientY);
        var d = 2 * Math.sqrt(dx * dx + dy * dy);

        var onda = document.createElement("span");
        onda.className = "m3-ripple";
        onda.style.width = onda.style.height = d + "px";
        onda.style.left = (e.clientX - r.left - d / 2) + "px";
        onda.style.top = (e.clientY - r.top - d / 2) + "px";
        alvo.appendChild(onda);
        onda.addEventListener("animationend", function () { onda.remove(); });
        // Rede de segurança: se a animação não disparar, não deixa lixo no DOM.
        setTimeout(function () { if (onda.parentNode) onda.remove(); }, 900);
      }, { passive: true });
    }

    /* ------------------------------------------------- top app bar on scroll */

    var barra = document.querySelector("#main > header") ||
                document.querySelector("#main header");
    if (barra) {
      var rolando = false;
      var aplicar = function () {
        rolando = false;
        var y = window.scrollY || document.documentElement.scrollTop || 0;
        barra.classList.toggle("m3-bar--rolada", y > 4);
      };
      window.addEventListener("scroll", function () {
        if (!rolando) { rolando = true; requestAnimationFrame(aplicar); }
      }, { passive: true });
      aplicar();
    }
  }
})();
