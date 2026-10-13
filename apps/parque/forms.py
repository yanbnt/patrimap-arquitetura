"""Formulários do app parque."""

from django import forms

from apps.orgs.models import Location

from .models import Baia, Computador, Notebook, Reparo


class ComputadorForm(forms.ModelForm):
    """No cadastro, a LOJA é obrigatória e o patrimônio é gerado automaticamente
    (PC-<sigla><NNNN>) — único, não digitável."""

    loja = forms.ModelChoiceField(
        queryset=Location.objects.filter(setores__isnull=False).distinct().order_by("name"),
        required=False, label="Loja (gera o patrimônio)",
        help_text="O patrimônio é gerado automaticamente pela loja (ex.: PC-B0105).",
    )

    class Meta:
        model = Computador
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        # No cadastro (sem pk) a loja é obrigatória — ela define o patrimônio.
        if not self.instance.pk and not cleaned.get("loja"):
            self.add_error("loja", "Escolha a loja para gerar o patrimônio.")
        return cleaned


class BaiaForm(forms.ModelForm):
    """A mesa aceita UM dispositivo: um computador do estoque OU um notebook livre.
    Limita cada campo aos disponíveis (+ o já vinculado) e bloqueia os dois juntos."""

    class Meta:
        model = Baia
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "computador" in self.fields:
            qs = Computador.objects.filter(status=Computador.Status.EM_ESTOQUE)
            atual = getattr(self.instance, "computador_id", None)
            if atual:
                qs = qs | Computador.objects.filter(pk=atual)
            self.fields["computador"].queryset = qs.distinct()
        if "notebook" in self.fields:
            # Notebooks disponíveis = livres (sem colaborador e fora de mesa) + o já vinculado.
            qs = Notebook.objects.filter(baia__isnull=True, colaborador__isnull=True)
            atual = getattr(self.instance, "notebook_id", None)
            if atual:
                qs = qs | Notebook.objects.filter(pk=atual)
            self.fields["notebook"].queryset = qs.distinct()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("computador") and cleaned.get("notebook"):
            raise forms.ValidationError(
                "A mesa aceita apenas UM dispositivo: escolha um computador OU um "
                "notebook, não os dois."
            )
        return cleaned


class ReparoForm(forms.ModelForm):
    """
    Quando a peça a trocar é 'Outra peça', o campo de descrição ('peca_outro')
    fica habilitado e é OBRIGATÓRIO. Nas demais opções o campo é ignorado/zerado.
    """

    class Meta:
        model = Reparo
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        # Desativação para troca: não há peça nem cotação.
        if cleaned.get("tipo") == Reparo.Tipo.DESATIVACAO:
            cleaned["peca"] = ""
            cleaned["peca_outro"] = ""
            cleaned["realizar_cotacao"] = False
            cleaned["bitrix_task_id"] = ""
            return cleaned
        peca = cleaned.get("peca")
        if peca == Reparo.Peca.OUTRO:
            if not (cleaned.get("peca_outro") or "").strip():
                self.add_error("peca_outro", "Descreva qual é a peça.")
        else:
            cleaned["peca_outro"] = ""
        # "Nenhuma" (sem troca de peça): sem cotação, sem tarefa Bitrix e sem custo.
        if peca == Reparo.Peca.NENHUMA:
            cleaned["realizar_cotacao"] = False
            cleaned["bitrix_task_id"] = ""
            cleaned["custo"] = None
        return cleaned
