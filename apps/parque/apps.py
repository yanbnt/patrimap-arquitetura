from django.apps import AppConfig


class ParqueConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.parque'
    verbose_name = 'Parque de Máquinas'

    def ready(self):
        from . import signals  # noqa: F401
