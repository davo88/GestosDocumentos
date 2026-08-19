from django.conf import settings
from django.db import models


def documento_upload_to(instance, filename):
    proyecto_id = instance.proyecto_id or "sin-proyecto"
    carpeta_id = instance.carpeta_id or "raiz"
    return f"documentos/proyecto_{proyecto_id}/carpeta_{carpeta_id}/{filename}"


def ticket_attachment_upload_to(instance, filename):
    ticket_number = instance.ticket.numero_ticket or "sin-ticket"
    return f"tickets/{ticket_number}/{filename}"


import os


def wbs_task_attachment_upload_to(instance, filename):
    proyecto_id = instance.tarea.etapa.proyecto_id or "sin-proyecto"
    task_code = instance.tarea.codigo or f"tarea_{instance.tarea_id or 'sin-id'}"
    return f"wbs/proyecto_{proyecto_id}/{task_code}/{filename}"


def wbs_task_image_upload_to(instance, filename):
    return wbs_task_attachment_upload_to(instance, filename)


class Proyecto(models.Model):
    nombre = models.CharField("Nombre de proyecto", max_length=150)
    fecha_creacion = models.DateTimeField("Fecha de creacion", auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proyectos_creados",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proyectos_actualizados",
    )

    class Meta:
        ordering = ["-fecha_creacion"]
        verbose_name = "Proyecto"
        verbose_name_plural = "Proyectos"

    def __str__(self):
        return self.nombre

    @property
    def github_path(self):
        return self.nombre.strip()


class Carpeta(models.Model):
    proyecto = models.ForeignKey(
        Proyecto,
        on_delete=models.CASCADE,
        related_name="carpetas",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subcarpetas",
    )
    nombre = models.CharField("Nombre de carpeta", max_length=150)
    fecha_creacion = models.DateTimeField("Fecha de creacion", auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="carpetas_creadas",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="carpetas_actualizadas",
    )

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Carpeta"
        verbose_name_plural = "Carpetas"

    def __str__(self):
        return self.nombre

    @property
    def github_path(self):
        segmentos = [self.nombre.strip()]
        carpeta = self.parent
        while carpeta is not None:
            segmentos.append(carpeta.nombre.strip())
            carpeta = carpeta.parent
        segmentos.append(self.proyecto.github_path)
        return "/".join(reversed(segmentos))


class Documento(models.Model):
    proyecto = models.ForeignKey(
        Proyecto,
        on_delete=models.CASCADE,
        related_name="documentos",
    )
    carpeta = models.ForeignKey(
        Carpeta,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="documentos",
    )
    archivo = models.FileField("Archivo", upload_to=documento_upload_to)
    nombre = models.CharField("Nombre", max_length=255)
    extension_original = models.CharField("Extension original", max_length=10, default="")
    fecha_creacion = models.DateTimeField("Fecha de creacion", auto_now_add=True)
    fecha_actualizacion = models.DateTimeField("Fecha de actualizacion", auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documentos_creados",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documentos_actualizados",
    )

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Documento"
        verbose_name_plural = "Documentos"
        constraints = [
            models.UniqueConstraint(
                fields=["proyecto", "carpeta", "nombre"],
                name="unique_documento_por_carpeta",
            )
        ]

    def __str__(self):
        return self.nombre

    @property
    def markdown_filename(self):
        if self.extension_original == ".md":
            return self.nombre
        return f"{self.nombre}.md"

    @property
    def github_markdown_path(self):
        if self.carpeta_id:
            return f"{self.carpeta.github_path}/{self.markdown_filename}"
        return f"{self.proyecto.github_path}/{self.markdown_filename}"


class DocumentoVersion(models.Model):
    documento = models.ForeignKey(
        Documento,
        on_delete=models.CASCADE,
        related_name="versiones",
    )
    version = models.PositiveIntegerField("Version")
    contenido_markdown = models.TextField("Contenido markdown")
    fecha_creacion = models.DateTimeField("Fecha de creacion", auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="versiones_documento_creadas",
    )

    class Meta:
        ordering = ["-version"]
        verbose_name = "Version de documento"
        verbose_name_plural = "Versiones de documento"
        constraints = [
            models.UniqueConstraint(
                fields=["documento", "version"],
                name="unique_version_por_documento",
            )
        ]

    def __str__(self):
        return f"{self.documento.nombre} v{self.version}"


class DocumentoRevision(models.Model):
    documento = models.ForeignKey(
        Documento,
        on_delete=models.CASCADE,
        related_name="revisiones",
    )
    version = models.ForeignKey(
        DocumentoVersion,
        on_delete=models.CASCADE,
        related_name="revisiones",
    )
    comentario = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revisiones_documento_creadas",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha_creacion"]
        verbose_name = "Revision de documento"
        verbose_name_plural = "Revisiones de documento"

    def __str__(self):
        return f"{self.documento.nombre} revisado en v{self.version.version}"


class NotificacionActividad(models.Model):
    TIPO_PROYECTO_CREADO = "proyecto_creado"
    TIPO_CARPETA_CREADA = "carpeta_creada"
    TIPO_DOCUMENTO_SUBIDO = "documento_subido"
    TIPO_DOCUMENTO_MODIFICADO = "documento_modificado"
    TIPO_DOCUMENTO_REVISADO = "documento_revisado"
    TIPO_TICKET_CREADO = "ticket_creado"
    TIPO_TICKET_CERRADO = "ticket_cerrado"
    TIPO_TICKET_REVISION = "ticket_revision"
    TIPO_TICKET_REABIERTO = "ticket_reabierto"

    TIPO_CHOICES = [
        (TIPO_PROYECTO_CREADO, "Proyecto creado"),
        (TIPO_CARPETA_CREADA, "Carpeta creada"),
        (TIPO_DOCUMENTO_SUBIDO, "Documento subido"),
        (TIPO_DOCUMENTO_MODIFICADO, "Documento modificado"),
        (TIPO_DOCUMENTO_REVISADO, "Documento revisado"),
        (TIPO_TICKET_CREADO, "Ticket creado"),
        (TIPO_TICKET_CERRADO, "Ticket cerrado"),
        (TIPO_TICKET_REVISION, "Ticket en revision"),
        (TIPO_TICKET_REABIERTO, "Ticket reabierto"),
    ]

    tipo = models.CharField(max_length=40, choices=TIPO_CHOICES)
    titulo = models.CharField(max_length=255)
    detalle = models.TextField(blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notificaciones_actividad",
    )
    destinatario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notificaciones_recibidas",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha_creacion"]
        verbose_name = "Notificacion de actividad"
        verbose_name_plural = "Notificaciones de actividad"

    def __str__(self):
        return self.titulo


class NotificacionLeida(models.Model):
    notificacion = models.ForeignKey(
        NotificacionActividad,
        on_delete=models.CASCADE,
        related_name="lecturas",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notificaciones_leidas",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha_creacion"]
        verbose_name = "Notificacion leida"
        verbose_name_plural = "Notificaciones leidas"
        constraints = [
            models.UniqueConstraint(
                fields=["notificacion", "usuario"],
                name="unique_notificacion_leida_por_usuario",
            )
        ]

    def __str__(self):
        return f"{self.usuario} - {self.notificacion}"


class SistemaConfiguracion(models.Model):
    github_owner = models.CharField(max_length=255, blank=True, default="")
    github_repo = models.CharField(max_length=255, blank=True, default="")
    github_token = models.TextField(blank=True, default="")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="configuraciones_actualizadas",
    )
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuracion del sistema"
        verbose_name_plural = "Configuraciones del sistema"

    def __str__(self):
        return "Configuracion del sistema"

    @classmethod
    def get_solo(cls):
        config, _created = cls.objects.get_or_create(pk=1)
        return config


class Ticket(models.Model):
    ESTADO_ABIERTO = "abierto"
    ESTADO_EN_REVISION = "en_revision"
    ESTADO_CERRADO = "cerrado"

    ESTADO_CHOICES = [
        (ESTADO_ABIERTO, "Abierto"),
        (ESTADO_EN_REVISION, "En revision de usuario"),
        (ESTADO_CERRADO, "Cerrado"),
    ]

    numero_secuencial = models.PositiveIntegerField(unique=True)
    numero_ticket = models.CharField(max_length=20, unique=True)
    documento = models.ForeignKey(
        Documento,
        on_delete=models.CASCADE,
        related_name="tickets",
    )
    proyecto = models.ForeignKey(
        Proyecto,
        on_delete=models.CASCADE,
        related_name="tickets",
    )
    carpeta = models.ForeignKey(
        Carpeta,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )
    titulo = models.CharField(max_length=255)
    descripcion = models.TextField()
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default=ESTADO_ABIERTO)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_creados",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_cerrados",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_revisados",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_revision = models.DateTimeField(null=True, blank=True)
    fecha_cierre = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-fecha_creacion"]
        verbose_name = "Ticket"
        verbose_name_plural = "Tickets"

    def __str__(self):
        return self.numero_ticket


class TicketComentario(models.Model):
    TIPO_MENSAJE = "mensaje"
    TIPO_RESPUESTA_GESTOR = "respuesta_gestor"
    TIPO_RECHAZO_USUARIO = "rechazo_usuario"
    TIPO_ACEPTACION_USUARIO = "aceptacion_usuario"

    TIPO_CHOICES = [
        (TIPO_MENSAJE, "Mensaje"),
        (TIPO_RESPUESTA_GESTOR, "Respuesta de gestor"),
        (TIPO_RECHAZO_USUARIO, "Revision rechazada"),
        (TIPO_ACEPTACION_USUARIO, "Revision aceptada"),
    ]

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="comentarios",
    )
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES, default=TIPO_MENSAJE)
    comentario = models.TextField()
    documento_version = models.ForeignKey(
        "DocumentoVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comentarios_ticket",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comentarios_ticket_creados",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fecha_creacion"]
        verbose_name = "Comentario de ticket"
        verbose_name_plural = "Comentarios de ticket"

    def __str__(self):
        return f"{self.ticket.numero_ticket} - comentario"


class TicketAdjunto(models.Model):
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="adjuntos",
    )
    archivo = models.FileField(upload_to=ticket_attachment_upload_to)
    nombre = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="adjuntos_ticket_creados",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fecha_creacion"]
        verbose_name = "Adjunto de ticket"
        verbose_name_plural = "Adjuntos de ticket"

    def __str__(self):
        return self.nombre


class WbsProyecto(models.Model):
    nombre = models.CharField("Nombre de proyecto", max_length=150)
    prefijo = models.CharField("Prefijo", max_length=20, default="")
    descripcion = models.TextField("Descripcion", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wbs_proyectos_creados",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wbs_proyectos_actualizados",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre", "id"]
        verbose_name = "Proyecto WBS"
        verbose_name_plural = "Proyectos WBS"
        constraints = [
            models.UniqueConstraint(
                fields=["nombre"],
                name="unique_wbs_proyecto_nombre",
            ),
            models.UniqueConstraint(
                fields=["prefijo"],
                name="unique_wbs_proyecto_prefijo",
            ),
        ]

    def __str__(self):
        return self.nombre


class WbsEtapa(models.Model):
    proyecto = models.ForeignKey(
        WbsProyecto,
        on_delete=models.CASCADE,
        related_name="etapas",
        null=True,
        blank=True,
    )
    nombre = models.CharField("Nombre de etapa", max_length=120)
    posicion = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wbs_etapas_creadas",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wbs_etapas_actualizadas",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["posicion", "id"]
        verbose_name = "Etapa WBS"
        verbose_name_plural = "Etapas WBS"
        constraints = [
            models.UniqueConstraint(
                fields=["proyecto", "nombre"],
                name="unique_wbs_etapa_nombre_por_proyecto",
            )
        ]

    def __str__(self):
        return self.nombre


class WbsTarea(models.Model):
    PRIORIDAD_BAJA = "baja"
    PRIORIDAD_MEDIA = "media"
    PRIORIDAD_ALTA = "alta"
    PRIORIDAD_CHOICES = [
        (PRIORIDAD_BAJA, "Baja"),
        (PRIORIDAD_MEDIA, "Media"),
        (PRIORIDAD_ALTA, "Alta"),
    ]

    titulo = models.CharField(max_length=255)
    codigo = models.CharField(max_length=40, default="", blank=True)
    numero_secuencial = models.PositiveIntegerField(default=0)
    descripcion = models.TextField(blank=True)
    etapa = models.ForeignKey(
        WbsEtapa,
        on_delete=models.CASCADE,
        related_name="tareas",
    )
    asignado_a = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wbs_tareas_asignadas",
    )
    prioridad = models.CharField(max_length=10, choices=PRIORIDAD_CHOICES, default=PRIORIDAD_MEDIA)
    posicion = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wbs_tareas_creadas",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wbs_tareas_actualizadas",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["posicion", "-fecha_actualizacion", "-id"]
        verbose_name = "Tarea WBS"
        verbose_name_plural = "Tareas WBS"

    def __str__(self):
        return self.codigo or self.titulo


class WbsDependencia(models.Model):
    tarea = models.ForeignKey(
        WbsTarea,
        on_delete=models.CASCADE,
        related_name="dependencias",
    )
    depende_de = models.ForeignKey(
        WbsTarea,
        on_delete=models.CASCADE,
        related_name="tareas_bloqueadas",
    )
    etapa_inicial_dependencia = models.ForeignKey(
        WbsEtapa,
        on_delete=models.CASCADE,
        related_name="dependencias_iniciales",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wbs_dependencias_creadas",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "Dependencia WBS"
        verbose_name_plural = "Dependencias WBS"
        constraints = [
            models.UniqueConstraint(
                fields=["tarea", "depende_de"],
                name="unique_wbs_dependencia_por_tarea",
            ),
            models.CheckConstraint(
                condition=~models.Q(tarea=models.F("depende_de")),
                name="wbs_dependencia_no_self",
            ),
        ]

    def __str__(self):
        return f"{self.tarea} depende de {self.depende_de}"


class WbsComentario(models.Model):
    tarea = models.ForeignKey(
        WbsTarea,
        on_delete=models.CASCADE,
        related_name="comentarios",
    )
    comentario = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wbs_comentarios_creados",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fecha_creacion", "id"]
        verbose_name = "Comentario WBS"
        verbose_name_plural = "Comentarios WBS"

    def __str__(self):
        return f"{self.tarea.titulo} - comentario"


class WbsSubtarea(models.Model):
    tarea = models.ForeignKey(
        WbsTarea,
        on_delete=models.CASCADE,
        related_name="subtareas",
    )
    titulo = models.CharField(max_length=255)
    completada = models.BooleanField(default=False)
    posicion = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wbs_subtareas_creadas",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wbs_subtareas_actualizadas",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["posicion", "id"]
        verbose_name = "Subtarea WBS"
        verbose_name_plural = "Subtareas WBS"

    def __str__(self):
        return self.titulo


class WbsAdjuntoImagen(models.Model):
    tarea = models.ForeignKey(
        WbsTarea,
        on_delete=models.CASCADE,
        related_name="adjuntos",
    )
    archivo = models.FileField(upload_to=wbs_task_attachment_upload_to)
    nombre = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wbs_adjuntos_creados",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fecha_creacion", "id"]
        verbose_name = "Adjunto WBS"
        verbose_name_plural = "Adjuntos WBS"

    def __str__(self):
        return self.nombre

    @property
    def extension(self):
        return os.path.splitext(self.nombre or self.archivo.name)[1].lower()

    @property
    def is_image(self):
        return self.extension in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}
