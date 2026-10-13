"""Middleware de no-cache — usado no acesso pelo túnel.

Força o navegador a SEMPRE revalidar (CSS/JS/HTML), evitando o problema de
"as mudanças não aparecem" por cache do navegador/edge ao servir pelo túnel.
Só é ativado em config.settings.tunnel (não afeta prod/dev normais).
"""


class NoCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        return response
