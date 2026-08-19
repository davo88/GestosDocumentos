from django import forms
from django.contrib.auth.models import Group, User

from .models import (
    Carpeta,
    Proyecto,
    SistemaConfiguracion,
    WbsAdjuntoImagen,
    WbsDependencia,
    WbsComentario,
    WbsEtapa,
    WbsProyecto,
    WbsSubtarea,
    WbsTarea,
)


TICKET_ATTACHMENT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".docx", ".txt", ".md"}


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class ProyectoForm(forms.ModelForm):
    class Meta:
        model = Proyecto
        fields = ["nombre"]
        widgets = {
            "nombre": forms.TextInput(
                attrs={
                    "placeholder": "Ej. Portal de contratos",
                    "autocomplete": "off",
                }
            ),
        }


class CarpetaForm(forms.ModelForm):
    class Meta:
        model = Carpeta
        fields = ["nombre"]
        widgets = {
            "nombre": forms.TextInput(
                attrs={
                    "placeholder": "Ej. Contratos 2026",
                    "autocomplete": "off",
                }
            ),
        }


class DocumentoUploadForm(forms.Form):
    archivos = forms.FileField(
        widget=MultipleFileInput(
            attrs={
                "class": "upload-input",
                "accept": ".docx,.txt,.md",
            }
        ),
        required=True,
    )


class TicketAttachmentInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class TicketCreateForm(forms.Form):
    TIPO_TICKET = "ticket"
    TIPO_REVISION = "revision"

    TIPO_CHOICES = [
        (TIPO_TICKET, "Ticket"),
        (TIPO_REVISION, "Documento revisado"),
    ]

    tipo = forms.ChoiceField(
        label="Tipo de revision",
        choices=TIPO_CHOICES,
    )
    titulo = forms.CharField(
        label="Titulo del ticket",
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "placeholder": "Ej. Ajustar alcance del flujo de aprobacion",
            }
        ),
    )
    descripcion = forms.CharField(
        label="Descripcion del ticket",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "placeholder": "Describe con claridad que encontraste y que necesita revision.",
            }
        ),
    )
    adjuntos = forms.FileField(
        required=False,
        widget=TicketAttachmentInput(
            attrs={
                "multiple": True,
                "accept": ".png,.jpg,.jpeg,.webp,.gif,.pdf,.docx,.txt,.md",
            }
        ),
    )

    def clean_adjuntos(self):
        archivos = self.files.getlist("adjuntos")
        for archivo in archivos:
            extension = f".{archivo.name.split('.')[-1].lower()}" if "." in archivo.name else ""
            if extension not in TICKET_ATTACHMENT_EXTENSIONS:
                allowed = ", ".join(sorted(TICKET_ATTACHMENT_EXTENSIONS))
                raise forms.ValidationError(
                    f"El archivo {archivo.name} no es compatible para tickets. Solo se permiten: {allowed}."
                )
        return archivos

    def clean(self):
        cleaned_data = super().clean()
        tipo = cleaned_data.get("tipo")
        titulo = (cleaned_data.get("titulo") or "").strip()
        descripcion = (cleaned_data.get("descripcion") or "").strip()

        if tipo == self.TIPO_TICKET:
            if not titulo:
                self.add_error("titulo", "Captura el titulo del ticket.")
            if not descripcion:
                self.add_error("descripcion", "Captura la descripcion del ticket.")
        elif tipo == self.TIPO_REVISION and not descripcion:
            self.add_error("descripcion", "Agrega un comentario corto para registrar la revision.")

        cleaned_data["titulo"] = titulo
        cleaned_data["descripcion"] = descripcion
        return cleaned_data


class TicketResolverForm(forms.Form):
    comentario = forms.CharField(
        label="Comentarios de resolucion",
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "placeholder": "Explica que se ajusto y como debe revisarlo el visualizador.",
            }
        ),
    )
    archivo_version = forms.FileField(
        label="Nueva version del documento",
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".docx,.txt,.md",
            }
        ),
    )


class TicketRevisionUsuarioForm(forms.Form):
    comentario = forms.CharField(
        label="Comentarios de revision",
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "placeholder": "Confirma si quedo bien o explica que sigue faltando para continuar con el mismo ticket.",
            }
        ),
    )


class SistemaConfiguracionForm(forms.ModelForm):
    class Meta:
        model = SistemaConfiguracion
        fields = ["github_owner", "github_repo", "github_token"]
        widgets = {
            "github_owner": forms.TextInput(
                attrs={
                    "placeholder": "Ej. davo88 o mi-organizacion",
                    "autocomplete": "off",
                    "spellcheck": "false",
                }
            ),
            "github_repo": forms.TextInput(
                attrs={
                    "placeholder": "Ej. Gestor-Documental",
                    "autocomplete": "off",
                    "spellcheck": "false",
                }
            ),
            "github_token": forms.Textarea(
                attrs={
                    "rows": 6,
                    "placeholder": "Pega aqui el token de GitHub que usara el sistema.",
                    "spellcheck": "false",
                }
            ),
        }


class CrearUsuarioForm(forms.Form):
    ROLE_GESTOR = "gestor"
    ROLE_VISUALIZADOR = "visualizador"
    ROLE_WBS = "wbs"
    ROLE_WBS_DESARROLLO = "wbs_desarrollo"

    ROLE_CHOICES = [
        (ROLE_GESTOR, "Gestor"),
        (ROLE_VISUALIZADOR, "Visualizador"),
        (ROLE_WBS, "WBS"),
        (ROLE_WBS_DESARROLLO, "WBS_Desarrollo"),
    ]

    username = forms.CharField(
        label="Usuario",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "placeholder": "Ej. maria.garcia",
            }
        ),
    )
    first_name = forms.CharField(
        label="Nombre",
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "placeholder": "Ej. Maria",
            }
        ),
    )
    last_name = forms.CharField(
        label="Apellidos",
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "placeholder": "Ej. Garcia Lopez",
            }
        ),
    )
    password = forms.CharField(
        label="Contrasena",
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "new-password",
                "placeholder": "Minimo 8 caracteres",
            }
        ),
    )
    roles = forms.MultipleChoiceField(
        label="Roles",
        choices=ROLE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ya existe un usuario con ese nombre.")
        return username

    def clean_password(self):
        password = self.cleaned_data["password"]
        if len(password) < 8:
            raise forms.ValidationError("La contrasena debe tener al menos 8 caracteres.")
        return password

    def save(self):
        roles = self.cleaned_data["roles"]
        user = User.objects.create_user(
            username=self.cleaned_data["username"],
            password=self.cleaned_data["password"],
            first_name=self.cleaned_data["first_name"].strip(),
            last_name=self.cleaned_data["last_name"].strip(),
            is_staff=False,
            is_superuser=False,
        )
        user.groups.set(_get_group_objects_from_role_values(roles))
        return user


class EditarUsuarioForm(forms.Form):
    username = forms.CharField(
        label="Usuario",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
            }
        ),
    )
    first_name = forms.CharField(
        label="Nombre",
        max_length=150,
        required=False,
    )
    last_name = forms.CharField(
        label="Apellidos",
        max_length=150,
        required=False,
    )
    password = forms.CharField(
        label="Nueva contrasena",
        required=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "new-password",
                "placeholder": "Dejar vacio para conservar la actual",
            }
        ),
    )
    roles = forms.MultipleChoiceField(
        label="Roles",
        choices=CrearUsuarioForm.ROLE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, user_instance=None, **kwargs):
        self.user_instance = user_instance
        initial = kwargs.setdefault("initial", {})
        if user_instance is not None:
            initial.setdefault("username", user_instance.username)
            initial.setdefault("first_name", user_instance.first_name)
            initial.setdefault("last_name", user_instance.last_name)
            initial.setdefault("roles", _get_user_role_values(user_instance))
        super().__init__(*args, **kwargs)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        qs = User.objects.filter(username__iexact=username)
        if self.user_instance is not None:
            qs = qs.exclude(pk=self.user_instance.pk)
        if qs.exists():
            raise forms.ValidationError("Ya existe un usuario con ese nombre.")
        return username

    def clean_password(self):
        password = self.cleaned_data["password"]
        if password and len(password) < 8:
            raise forms.ValidationError("La contrasena debe tener al menos 8 caracteres.")
        return password

    def save(self):
        roles = self.cleaned_data["roles"]
        user = self.user_instance
        user.username = self.cleaned_data["username"]
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        password = self.cleaned_data["password"]
        if password:
            user.set_password(password)
        user.save()
        user.groups.set(_get_group_objects_from_role_values(roles))
        return user


def _get_group_objects_from_role_values(role_values):
    role_to_group = {
        CrearUsuarioForm.ROLE_GESTOR: "Gestor",
        CrearUsuarioForm.ROLE_VISUALIZADOR: "Visualizador",
        CrearUsuarioForm.ROLE_WBS: "WBS",
        CrearUsuarioForm.ROLE_WBS_DESARROLLO: "WBS_Desarrollo",
    }
    groups = []
    for role_value in role_values:
        group_name = role_to_group[role_value]
        group, _ = Group.objects.get_or_create(name=group_name)
        groups.append(group)
    return groups


def _get_user_role_values(user):
    role_values = []
    if user.groups.filter(name="Gestor").exists():
        role_values.append(CrearUsuarioForm.ROLE_GESTOR)
    if user.groups.filter(name="Visualizador").exists():
        role_values.append(CrearUsuarioForm.ROLE_VISUALIZADOR)
    if user.groups.filter(name="WBS").exists():
        role_values.append(CrearUsuarioForm.ROLE_WBS)
    if user.groups.filter(name="WBS_Desarrollo").exists():
        role_values.append(CrearUsuarioForm.ROLE_WBS_DESARROLLO)
    return role_values


class WbsEtapaForm(forms.ModelForm):
    class Meta:
        model = WbsEtapa
        fields = ["nombre"]
        widgets = {
            "nombre": forms.TextInput(
                attrs={
                    "autocomplete": "off",
                    "placeholder": "Ej. En analisis",
                }
            ),
        }


class WbsProyectoForm(forms.ModelForm):
    class Meta:
        model = WbsProyecto
        fields = ["nombre", "prefijo", "descripcion"]
        widgets = {
            "nombre": forms.TextInput(
                attrs={
                    "autocomplete": "off",
                    "placeholder": "Ej. Plataforma de onboarding",
                }
            ),
            "prefijo": forms.TextInput(
                attrs={
                    "autocomplete": "off",
                    "placeholder": "Ej. ONB",
                }
            ),
            "descripcion": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Contexto breve del proyecto, objetivo y alcance del tablero.",
                }
            ),
        }

    def clean_prefijo(self):
        prefijo = (self.cleaned_data.get("prefijo") or "").strip().upper()
        if not prefijo:
            raise forms.ValidationError("Captura un prefijo para el proyecto.")
        return prefijo


class WbsTareaForm(forms.ModelForm):
    dependencias = forms.ModelMultipleChoiceField(
        label="Dependencia",
        queryset=WbsTarea.objects.none(),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "size": 6,
            }
        ),
    )

    class Meta:
        model = WbsTarea
        fields = ["titulo", "etapa", "asignado_a", "prioridad"]
        widgets = {
            "titulo": forms.TextInput(
                attrs={
                    "autocomplete": "off",
                    "placeholder": "Ej. Definir flujo de aprobacion",
                }
            ),
        }

    def __init__(self, *args, assignable_users=None, proyecto=None, **kwargs):
        super().__init__(*args, **kwargs)
        stage_queryset = WbsEtapa.objects.order_by("posicion", "id")
        if proyecto is not None:
            stage_queryset = stage_queryset.filter(proyecto=proyecto)
        self.fields["etapa"].queryset = stage_queryset
        queryset = assignable_users if assignable_users is not None else User.objects.none()
        self.fields["asignado_a"].queryset = queryset
        self.fields["asignado_a"].required = False
        self.fields["asignado_a"].empty_label = "Sin asignar"
        dependency_queryset = WbsTarea.objects.select_related("etapa").order_by("numero_secuencial", "id")
        if proyecto is not None:
            dependency_queryset = dependency_queryset.filter(etapa__proyecto=proyecto)
        if self.instance.pk:
            dependency_queryset = dependency_queryset.exclude(pk=self.instance.pk)
            self.fields["dependencias"].initial = list(
                WbsDependencia.objects.filter(tarea=self.instance).values_list("depende_de_id", flat=True)
            )
        self.fields["dependencias"].queryset = dependency_queryset

    def clean_dependencias(self):
        dependencias = self.cleaned_data.get("dependencias")
        if self.instance.pk and dependencias.filter(pk=self.instance.pk).exists():
            raise forms.ValidationError("Una tarjeta no puede depender de si misma.")
        return dependencias


class WbsDescripcionTareaForm(forms.ModelForm):
    class Meta:
        model = WbsTarea
        fields = ["descripcion"]
        widgets = {
            "descripcion": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": "Agrega el detalle de la tarjeta, alcance, dependencias y criterio de terminado.",
                }
            ),
        }


class WbsComentarioForm(forms.ModelForm):
    class Meta:
        model = WbsComentario
        fields = ["comentario"]
        widgets = {
            "comentario": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Agrega contexto, bloqueo o siguiente paso.",
                }
            ),
        }


class WbsSubtareaForm(forms.ModelForm):
    class Meta:
        model = WbsSubtarea
        fields = ["titulo"]
        widgets = {
            "titulo": forms.TextInput(
                attrs={
                    "autocomplete": "off",
                    "placeholder": "Ej. Validar alcance con el usuario",
                }
            ),
        }


class WbsAdjuntoImagenForm(forms.ModelForm):
    class Meta:
        model = WbsAdjuntoImagen
        fields = ["archivo"]
        widgets = {
            "archivo": forms.ClearableFileInput(),
        }
