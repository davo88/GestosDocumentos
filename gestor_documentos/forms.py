from django import forms
from django.contrib.auth.models import Group, User

from .models import Carpeta, Proyecto, SistemaConfiguracion


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

    ROLE_CHOICES = [
        (ROLE_GESTOR, "Gestor"),
        (ROLE_VISUALIZADOR, "Visualizador"),
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
    role = forms.ChoiceField(
        label="Rol",
        choices=ROLE_CHOICES,
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
        role = self.cleaned_data["role"]
        user = User.objects.create_user(
            username=self.cleaned_data["username"],
            password=self.cleaned_data["password"],
            first_name=self.cleaned_data["first_name"].strip(),
            last_name=self.cleaned_data["last_name"].strip(),
            is_staff=False,
            is_superuser=False,
        )
        group_name = "Gestor" if role == self.ROLE_GESTOR else "Visualizador"
        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)
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
    role = forms.ChoiceField(
        label="Rol",
        choices=CrearUsuarioForm.ROLE_CHOICES,
    )

    def __init__(self, *args, user_instance=None, **kwargs):
        self.user_instance = user_instance
        initial = kwargs.setdefault("initial", {})
        if user_instance is not None:
            initial.setdefault("username", user_instance.username)
            initial.setdefault("first_name", user_instance.first_name)
            initial.setdefault("last_name", user_instance.last_name)
            initial.setdefault("role", _get_user_role_value(user_instance))
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
        role = self.cleaned_data["role"]
        user = self.user_instance
        user.username = self.cleaned_data["username"]
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        password = self.cleaned_data["password"]
        if password:
            user.set_password(password)
        user.save()
        user.groups.clear()
        group_name = "Gestor" if role == CrearUsuarioForm.ROLE_GESTOR else "Visualizador"
        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)
        return user


def _get_user_role_value(user):
    if user.groups.filter(name="Gestor").exists():
        return CrearUsuarioForm.ROLE_GESTOR
    return CrearUsuarioForm.ROLE_VISUALIZADOR
