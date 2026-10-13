"""Tag de estático VERSIONADO para templates.

Por que existe: o `{% static %}` do Django devolve a URL sem nada que mude
quando o arquivo muda. Nas telas de autenticação o CSS era linkado assim, e o
navegador ficava com a versão antiga em cache — foi o que fez a tela de entrada
continuar aparecendo com o estilo velho depois de trocado. As telas do admin já
tinham versão porque o `UNFOLD["STYLES"]` usa `_asset_versionado`; aqui a mesma
regra fica disponível para qualquer template.

O mtime é lido do arquivo QUE VAI SER SERVIDO (o STATIC_ROOT, quando existe).
Ler da origem criava o pior dos mundos: a URL anunciava versão nova enquanto o
servidor entregava o arquivo velho, e o navegador guardava conteúdo velho sob
URL nova — sem jeito de sair dali sem limpar o cache à mão.
"""

import os
from pathlib import Path

from django import template
from django.conf import settings
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def mkstatic(caminho_relativo):
    url = static(caminho_relativo)
    candidatos = []
    if getattr(settings, "STATIC_ROOT", None):
        candidatos.append(Path(settings.STATIC_ROOT) / caminho_relativo)
    candidatos.append(Path(settings.BASE_DIR) / "static" / caminho_relativo)
    for caminho in candidatos:
        try:
            return f"{url}?v={int(os.path.getmtime(caminho))}"
        except OSError:
            continue
    return url
