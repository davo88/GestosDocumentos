import os
from difflib import SequenceMatcher

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import models
from django.db.models import Count, Max, Prefetch, Q
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape
from django.utils import timezone

from .document_processing import (
    DocumentProcessingError,
    convert_uploaded_file_to_markdown,
    get_extension,
    render_stored_file_to_html,
)
from .activity_service import registrar_notificacion
from .forms import (
    CarpetaForm,
    CrearUsuarioForm,
    DocumentoUploadForm,
    EditarUsuarioForm,
    ProyectoForm,
    SistemaConfiguracionForm,
    TicketCreateForm,
    TicketRevisionUsuarioForm,
    TicketResolverForm,
    WbsAdjuntoImagenForm,
    WbsComentarioForm,
    WbsDescripcionTareaForm,
    WbsEtapaForm,
    WbsProyectoForm,
    WbsSubtareaForm,
    WbsTareaForm,
)
from .github_service import GitHubSyncError, delete_text_file, ensure_directory, upsert_text_file
from .models import (
    Carpeta,
    Documento,
    DocumentoRevision,
    DocumentoVersion,
    NotificacionActividad,
    NotificacionLeida,
    Proyecto,
    SistemaConfiguracion,
    Ticket,
    TicketAdjunto,
    WbsAdjuntoImagen,
    WbsDependencia,
    TicketComentario,
    WbsComentario,
    WbsEtapa,
    WbsProyecto,
    WbsSubtarea,
    WbsTarea,
)
from .permissions import (
    can_comment_wbs_tasks,
    can_create_tickets,
    can_manage_documentacion,
    can_manage_tickets,
    can_manage_wbs_board,
    can_view_tickets,
    can_view_wbs_board,
    can_move_wbs_tasks,
    ensure_role_groups,
    forbid_if_no_view_access,
    is_admin,
    is_visualizador,
    is_wbs,
    is_wbs_desarrollo,
)


def landing(request):
    if request.user.is_authenticated:
        if can_view_wbs_board(request.user) and not _can_access_standard_dashboard(request.user):
            return redirect("wbs_project_list")
        return redirect("inicio")
    return redirect("login")


@login_required
def inicio(request):
    ensure_role_groups()
    if can_view_wbs_board(request.user) and not _can_access_standard_dashboard(request.user):
        return redirect("wbs_project_list")
    denied = forbid_if_no_view_access(request.user)
    if denied:
        return denied

    review_form = TicketCreateForm()
    review_modal_abierto = False

    if request.method == "POST" and request.POST.get("action") == "revisar_documento" and can_create_tickets(request.user):
        documento_id = request.POST.get("documento_id")
        documento = get_object_or_404(Documento, pk=documento_id)
        review_form = TicketCreateForm(request.POST, request.FILES)
        review_modal_abierto = True
        if review_form.is_valid():
            try:
                if review_form.cleaned_data["tipo"] == TicketCreateForm.TIPO_TICKET:
                    ticket = _crear_ticket_desde_documento(
                        proyecto=documento.proyecto,
                        carpeta=documento.carpeta,
                        documento=documento,
                        actor=request.user,
                        titulo=review_form.cleaned_data["titulo"],
                        descripcion=review_form.cleaned_data["descripcion"],
                        archivos=review_form.cleaned_data["adjuntos"],
                    )
                else:
                    _registrar_revision_documento(
                        documento=documento,
                        actor=request.user,
                        comentario=review_form.cleaned_data["descripcion"],
                    )
            except Exception as exc:
                messages.error(request, f"No se pudo guardar la revision: {exc}")
            else:
                if review_form.cleaned_data["tipo"] == TicketCreateForm.TIPO_TICKET:
                    messages.success(
                        request,
                        f"Se levanto el ticket {ticket.numero_ticket} para {documento.nombre}.",
                    )
                    return redirect("tickets")
                messages.success(request, f"Se registro la revision de {documento.nombre}.")
                return redirect("inicio")

    context = _build_inicio_dashboard(request.user)
    context["review_form"] = review_form
    context["review_modal_abierto"] = review_modal_abierto
    context["proximo_ticket_numero"] = _get_next_ticket_preview()
    return render(request, "gestor_documentos/inicio.html", context)


@login_required
def documentacion(request):
    ensure_role_groups()
    denied = forbid_if_no_view_access(request.user)
    if denied:
        return denied

    proyectos = Proyecto.objects.all()
    form = ProyectoForm()
    modal_abierto = False

    if request.method == "POST":
        if not can_manage_documentacion(request.user):
            messages.error(request, "No tienes permisos para crear proyectos.")
            return redirect("documentacion")
        form = ProyectoForm(request.POST)
        modal_abierto = True
        if form.is_valid():
            try:
                with transaction.atomic():
                    proyecto = form.save(commit=False)
                    proyecto.created_by = request.user
                    proyecto.updated_by = request.user
                    proyecto.save()
                    ensure_directory(
                        proyecto.github_path,
                        f"Marcador de carpeta para el proyecto {proyecto.nombre}\n",
                    )
            except GitHubSyncError as exc:
                messages.error(request, str(exc))
            else:
                registrar_notificacion(
                    NotificacionActividad.TIPO_PROYECTO_CREADO,
                    f"Proyecto creado: {proyecto.nombre}",
                    request.user,
                    f"{request.user.username} creo el proyecto {proyecto.nombre}.",
                )
                messages.success(request, "El proyecto se creo y se sincronizo con GitHub.")
                return redirect("documentacion")

    context = {
        "proyectos": proyectos,
        "form": form,
        "modal_abierto": modal_abierto,
    }
    return render(request, "gestor_documentos/documentacion.html", context)


def construir_breadcrumbs(proyecto, carpeta_actual):
    breadcrumbs = [
        {
            "label": proyecto.nombre,
            "url": None if carpeta_actual is None else reverse("documentacion_proyecto", args=[proyecto.id]),
        }
    ]
    trail = []
    carpeta = carpeta_actual
    while carpeta is not None:
        trail.append(carpeta)
        carpeta = carpeta.parent

    for carpeta in reversed(trail):
        breadcrumbs.append(
            {
                "label": carpeta.nombre,
                "url": f"?carpeta={carpeta.id}" if carpeta != carpeta_actual else None,
            }
        )
    return breadcrumbs


@login_required
def documentacion_proyecto(request, proyecto_id):
    ensure_role_groups()
    denied = forbid_if_no_view_access(request.user)
    if denied:
        return denied

    proyecto = get_object_or_404(Proyecto, pk=proyecto_id)
    carpeta_param = request.GET.get("carpeta")
    carpeta_actual = None

    if carpeta_param and carpeta_param != "raiz":
        carpeta_actual = get_object_or_404(Carpeta, pk=carpeta_param, proyecto=proyecto)

    folder_form = CarpetaForm()
    upload_form = DocumentoUploadForm()
    ticket_form = TicketCreateForm()
    modal_abierto = False
    ticket_modal_abierto = False

    if request.method == "POST":
        action = request.POST.get("action")

        if action in {"crear_carpeta", "subir_documentos", "eliminar_documento"} and not can_manage_documentacion(request.user):
            messages.error(request, "No tienes permisos para modificar la documentacion.")
            if carpeta_actual:
                return redirect(f"{request.path}?carpeta={carpeta_actual.id}")
            return redirect("documentacion_proyecto", proyecto_id=proyecto.id)

        if action == "revisar_documento" and not can_create_tickets(request.user):
            messages.error(request, "No tienes permisos para revisar documentos.")
            if carpeta_actual:
                return redirect(f"{request.path}?carpeta={carpeta_actual.id}")
            return redirect("documentacion_proyecto", proyecto_id=proyecto.id)

        if action == "crear_carpeta":
            folder_form = CarpetaForm(request.POST)
            modal_abierto = True
            if folder_form.is_valid():
                try:
                    with transaction.atomic():
                        carpeta = folder_form.save(commit=False)
                        carpeta.proyecto = proyecto
                        carpeta.parent = carpeta_actual
                        carpeta.created_by = request.user
                        carpeta.updated_by = request.user
                        carpeta.save()
                        ensure_directory(
                            carpeta.github_path,
                            f"Marcador de carpeta para {carpeta.github_path}\n",
                        )
                except GitHubSyncError as exc:
                    messages.error(request, str(exc))
                else:
                    registrar_notificacion(
                        NotificacionActividad.TIPO_CARPETA_CREADA,
                        f"Carpeta creada: {carpeta.nombre}",
                        request.user,
                        f"{request.user.username} creo la carpeta {carpeta.github_path}.",
                    )
                    messages.success(request, "La carpeta se creo y se sincronizo con GitHub.")
                    if carpeta_actual:
                        return redirect(f"{request.path}?carpeta={carpeta_actual.id}")
                    return redirect("documentacion_proyecto", proyecto_id=proyecto.id)

        if action == "subir_documentos":
            archivos = request.FILES.getlist("archivos")
            if not archivos:
                messages.error(request, "Selecciona al menos un archivo para cargar.")
            else:
                try:
                    procesados = 0
                    ignorados = 0
                    for archivo in archivos:
                        resultado, documento, _version = _procesar_carga_documento(
                            proyecto,
                            carpeta_actual,
                            archivo,
                            request.user,
                        )
                        if resultado == "ignored":
                            ignorados += 1
                        else:
                            procesados += 1
                            if resultado == "created":
                                registrar_notificacion(
                                    NotificacionActividad.TIPO_DOCUMENTO_SUBIDO,
                                    f"Documento subido: {documento.nombre}",
                                    request.user,
                                    f"{request.user.username} subio el documento {documento.nombre}.",
                                )
                            elif resultado == "updated":
                                registrar_notificacion(
                                    NotificacionActividad.TIPO_DOCUMENTO_MODIFICADO,
                                    f"Modificaciones a {documento.nombre}",
                                    request.user,
                                    f"{request.user.username} modifico el documento {documento.nombre}.",
                                )
                except (DocumentProcessingError, GitHubSyncError) as exc:
                    messages.error(request, str(exc))
                else:
                    if procesados:
                        sufijo = "s" if procesados != 1 else ""
                        messages.success(
                            request,
                            f"Se cargaron {procesados} documento{sufijo} y se convirtieron a Markdown.",
                        )
                    if ignorados:
                        sufijo = "s" if ignorados != 1 else ""
                        messages.warning(
                            request,
                            f"Se ignoraron {ignorados} archivo{sufijo} porque no tuvieron cambios.",
                        )
                    if carpeta_actual:
                        return redirect(f"{request.path}?carpeta={carpeta_actual.id}")
                    return redirect("documentacion_proyecto", proyecto_id=proyecto.id)

        if action == "subir_documento_ajax":
            archivo = request.FILES.get("archivo")
            if archivo is None:
                return JsonResponse(
                    {
                        "ok": False,
                        "message": "No se recibio ningun archivo para procesar.",
                    },
                    status=400,
                )

            try:
                resultado, documento, version = _procesar_carga_documento(
                    proyecto,
                    carpeta_actual,
                    archivo,
                    request.user,
                )
                if resultado == "created":
                    registrar_notificacion(
                        NotificacionActividad.TIPO_DOCUMENTO_SUBIDO,
                        f"Documento subido: {documento.nombre}",
                        request.user,
                        f"{request.user.username} subio el documento {documento.nombre}.",
                    )
                elif resultado == "updated":
                    registrar_notificacion(
                        NotificacionActividad.TIPO_DOCUMENTO_MODIFICADO,
                        f"Modificaciones a {documento.nombre}",
                        request.user,
                        f"{request.user.username} modifico el documento {documento.nombre}.",
                    )
            except (DocumentProcessingError, GitHubSyncError) as exc:
                return JsonResponse(
                    {
                        "ok": False,
                        "message": str(exc),
                        "document_name": os.path.basename(archivo.name),
                    },
                    status=400,
                )
            except Exception as exc:
                return JsonResponse(
                    {
                        "ok": False,
                        "message": f"Error interno al procesar {os.path.basename(archivo.name)}: {exc}",
                        "document_name": os.path.basename(archivo.name),
                    },
                    status=500,
                )

            return JsonResponse(
                {
                    "ok": True,
                    "result": resultado,
                    "document_name": documento.nombre,
                    "version": None if version is None else version.version,
                    "message": _build_upload_result_message(resultado, documento.nombre, version),
                }
            )

        if action == "eliminar_documento":
            documento_id = request.POST.get("documento_id")
            documento = get_object_or_404(
                Documento.objects.select_for_update(),
                pk=documento_id,
                proyecto=proyecto,
                carpeta=carpeta_actual,
            )
            archivo_path = documento.archivo.name
            nombre_documento = documento.nombre
            github_path = documento.github_markdown_path
            try:
                with transaction.atomic():
                    delete_text_file(
                        github_path,
                        f"Eliminar documento {github_path}",
                    )
                    documento.delete()
            except GitHubSyncError as exc:
                messages.error(request, str(exc))
            else:
                if archivo_path:
                    documento.archivo.storage.delete(archivo_path)
                messages.success(
                    request,
                    f"El documento {nombre_documento} se elimino del sistema y de GitHub.",
                )
                if carpeta_actual:
                    return redirect(f"{request.path}?carpeta={carpeta_actual.id}")
                return redirect("documentacion_proyecto", proyecto_id=proyecto.id)

        if action == "revisar_documento":
            documento_id = request.POST.get("documento_id")
            documento = get_object_or_404(
                Documento,
                pk=documento_id,
                proyecto=proyecto,
                carpeta=carpeta_actual,
            )
            ticket_form = TicketCreateForm(request.POST, request.FILES)
            ticket_modal_abierto = True
            if ticket_form.is_valid():
                try:
                    if ticket_form.cleaned_data["tipo"] == TicketCreateForm.TIPO_TICKET:
                        ticket = _crear_ticket_desde_documento(
                            proyecto=proyecto,
                            carpeta=carpeta_actual,
                            documento=documento,
                            actor=request.user,
                            titulo=ticket_form.cleaned_data["titulo"],
                            descripcion=ticket_form.cleaned_data["descripcion"],
                            archivos=ticket_form.cleaned_data["adjuntos"],
                        )
                    else:
                        _registrar_revision_documento(
                            documento=documento,
                            actor=request.user,
                            comentario=ticket_form.cleaned_data["descripcion"],
                        )
                except Exception as exc:
                    messages.error(request, f"No se pudo guardar la revision: {exc}")
                else:
                    if ticket_form.cleaned_data["tipo"] == TicketCreateForm.TIPO_TICKET:
                        messages.success(
                            request,
                            f"Se levanto el ticket {ticket.numero_ticket} para {documento.nombre}.",
                        )
                        return redirect("tickets")
                    else:
                        messages.success(
                            request,
                            f"Se registro la revision de {documento.nombre}.",
                        )
                        if carpeta_actual:
                            return redirect(f"{request.path}?carpeta={carpeta_actual.id}")
                        return redirect("documentacion_proyecto", proyecto_id=proyecto.id)

    carpetas = Carpeta.objects.filter(proyecto=proyecto, parent=carpeta_actual)
    documentos = (
        Documento.objects.filter(proyecto=proyecto, carpeta=carpeta_actual)
        .prefetch_related("versiones")
        .prefetch_related("revisiones__version", "revisiones__created_by")
        .prefetch_related(
            Prefetch(
                "tickets",
                queryset=Ticket.objects.order_by("-fecha_creacion"),
                to_attr="tickets_cache",
            )
        )
    )
    for documento in documentos:
        _attach_document_status(documento)
    breadcrumbs = construir_breadcrumbs(proyecto, carpeta_actual)

    context = {
        "proyecto": proyecto,
        "carpetas": carpetas,
        "documentos": documentos,
        "carpeta_actual": carpeta_actual,
        "breadcrumbs": breadcrumbs,
        "folder_form": folder_form,
        "upload_form": upload_form,
        "ticket_form": ticket_form,
        "modal_abierto": modal_abierto,
        "ticket_modal_abierto": ticket_modal_abierto,
        "proximo_ticket_numero": _get_next_ticket_preview(),
    }
    return render(request, "gestor_documentos/documentacion_proyecto.html", context)


@login_required
def documento_cambios(request, proyecto_id, documento_id):
    ensure_role_groups()
    denied = forbid_if_no_view_access(request.user)
    if denied:
        return denied

    proyecto = get_object_or_404(Proyecto, pk=proyecto_id)
    documento = get_object_or_404(
        Documento.objects.prefetch_related("versiones"),
        pk=documento_id,
        proyecto=proyecto,
    )
    versiones = list(documento.versiones.order_by("-version"))

    if not versiones:
        messages.error(request, "Este documento aun no tiene versiones para comparar.")
        return redirect("documentacion_proyecto", proyecto_id=proyecto.id)

    version_actual = _resolver_version(versiones, request.GET.get("actual"), default=versiones[0])
    version_base_default = versiones[1] if len(versiones) > 1 else versiones[0]
    version_base = _resolver_version(versiones, request.GET.get("base"), default=version_base_default)

    diff_rows, diff_summary = _build_diff_rows(
        version_base.contenido_markdown,
        version_actual.contenido_markdown,
    )

    breadcrumbs = construir_breadcrumbs(proyecto, documento.carpeta)
    breadcrumbs.append({"label": documento.nombre, "url": None})

    context = {
        "proyecto": proyecto,
        "documento": documento,
        "versiones": versiones,
        "version_base": version_base,
        "version_actual": version_actual,
        "diff_rows": diff_rows,
        "diff_summary": diff_summary,
        "breadcrumbs": breadcrumbs,
        "base_preview_html": _build_document_preview_html(diff_rows, side="old"),
        "actual_preview_html": _build_document_preview_html(diff_rows, side="new"),
    }
    return render(request, "gestor_documentos/documento_cambios.html", context)


@login_required
def documento_visualizador(request, proyecto_id, documento_id):
    ensure_role_groups()
    denied = forbid_if_no_view_access(request.user)
    if denied:
        return denied

    proyecto = get_object_or_404(Proyecto, pk=proyecto_id)
    documento = get_object_or_404(
        Documento.objects.select_related("proyecto", "carpeta", "created_by", "updated_by").prefetch_related("versiones"),
        pk=documento_id,
        proyecto=proyecto,
    )
    breadcrumbs = construir_breadcrumbs(proyecto, documento.carpeta)
    breadcrumbs.append({"label": documento.nombre, "url": None})

    try:
        preview_html = render_stored_file_to_html(documento.archivo, documento.extension_original)
    except DocumentProcessingError as exc:
        messages.error(request, str(exc))
        return redirect("documentacion_proyecto", proyecto_id=proyecto.id)

    latest_version = next(iter(documento.versiones.all()), None)
    context = {
        "proyecto": proyecto,
        "documento": documento,
        "breadcrumbs": breadcrumbs,
        "preview_html": preview_html,
        "latest_version": latest_version,
        "download_url": documento.archivo.url,
        "back_url": reverse("documentacion_proyecto", args=[proyecto.id])
        + (f"?carpeta={documento.carpeta_id}" if documento.carpeta_id else ""),
    }
    return render(request, "gestor_documentos/documento_visualizador.html", context)


@login_required
def crear_usuarios(request):
    ensure_role_groups()
    if not is_admin(request.user):
        return redirect("documentacion")

    role_filter = request.GET.get("rol", "todos")
    edit_user_id = request.GET.get("editar")

    form = CrearUsuarioForm()
    usuarios_base = User.objects.filter(is_superuser=False).prefetch_related("groups")
    usuarios = usuarios_base.order_by("username")
    if role_filter == "gestor":
        usuarios = usuarios.filter(groups__name="Gestor")
    elif role_filter == "visualizador":
        usuarios = usuarios.filter(groups__name="Visualizador")
    elif role_filter == "wbs":
        usuarios = usuarios.filter(groups__name="WBS")
    elif role_filter == "wbs_desarrollo":
        usuarios = usuarios.filter(groups__name="WBS_Desarrollo")
    usuarios = usuarios.distinct()

    edit_user = None
    edit_form = None
    if edit_user_id and str(edit_user_id).isdigit():
        edit_user = usuarios_base.filter(pk=int(edit_user_id)).first()
        if edit_user:
            edit_form = EditarUsuarioForm(user_instance=edit_user)

    if request.method == "POST":
        action = request.POST.get("action", "crear")

        if action == "crear":
            form = CrearUsuarioForm(request.POST)
            if form.is_valid():
                user = form.save()
                messages.success(request, f"Se creo el usuario {user.username} correctamente.")
                return redirect("crear_usuarios")

        if action == "editar":
            user_id = request.POST.get("user_id")
            edit_user = get_object_or_404(User, pk=user_id, is_superuser=False)
            edit_form = EditarUsuarioForm(request.POST, user_instance=edit_user)
            if edit_form.is_valid():
                updated_user = edit_form.save()
                messages.success(request, f"Se actualizo el usuario {updated_user.username}.")
                return redirect(f"{reverse('crear_usuarios')}?rol={role_filter}")

        if action == "eliminar":
            user_id = request.POST.get("user_id")
            user_to_delete = get_object_or_404(User, pk=user_id, is_superuser=False)
            username = user_to_delete.username
            user_to_delete.delete()
            messages.success(request, f"Se elimino el usuario {username}.")
            return redirect(f"{reverse('crear_usuarios')}?rol={role_filter}")

    context = {
        "form": form,
        "usuarios": usuarios,
        "edit_user": edit_user,
        "edit_form": edit_form,
        "role_filter": role_filter,
    }
    return render(request, "gestor_documentos/crear_usuarios.html", context)


@login_required
def wbs_project_list(request):
    ensure_role_groups()
    if not can_view_wbs_board(request.user):
        return redirect("inicio")

    form = WbsProyectoForm(prefix="project")
    edit_project = None
    edit_project_form = None

    edit_project_id = request.GET.get("editar")
    if edit_project_id and str(edit_project_id).isdigit():
        edit_project = WbsProyecto.objects.filter(pk=int(edit_project_id)).first()
        if edit_project and can_manage_wbs_board(request.user):
            edit_project_form = WbsProyectoForm(instance=edit_project, prefix="edit-project")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "crear_proyecto":
            if not can_manage_wbs_board(request.user):
                messages.error(request, "No tienes permisos para crear proyectos WBS.")
                return redirect("wbs_project_list")
            form = WbsProyectoForm(request.POST, prefix="project")
            if form.is_valid():
                proyecto = form.save(commit=False)
                proyecto.created_by = request.user
                proyecto.updated_by = request.user
                proyecto.save()
                messages.success(request, f"El proyecto WBS {proyecto.nombre} se creo correctamente.")
                return redirect("wbs_board", project_id=proyecto.id)

        if action == "editar_proyecto":
            if not can_manage_wbs_board(request.user):
                messages.error(request, "No tienes permisos para editar proyectos WBS.")
                return redirect("wbs_project_list")
            project_id = request.POST.get("project_id")
            edit_project = get_object_or_404(WbsProyecto, pk=project_id)
            edit_project_form = WbsProyectoForm(request.POST, instance=edit_project, prefix="edit-project")
            if edit_project_form.is_valid():
                proyecto = edit_project_form.save(commit=False)
                proyecto.updated_by = request.user
                proyecto.save()
                messages.success(request, f"El proyecto WBS {proyecto.nombre} se actualizo correctamente.")
                return redirect("wbs_project_list")

        if action == "eliminar_proyecto":
            if not can_manage_wbs_board(request.user):
                messages.error(request, "No tienes permisos para eliminar proyectos WBS.")
                return redirect("wbs_project_list")
            project_id = request.POST.get("project_id")
            proyecto = get_object_or_404(WbsProyecto, pk=project_id)
            nombre = proyecto.nombre
            proyecto.delete()
            messages.success(request, f"El proyecto WBS {nombre} y todo su tablero se eliminaron correctamente.")
            return redirect("wbs_project_list")

    proyectos = (
        WbsProyecto.objects.order_by("nombre", "id")
        .annotate(
            total_listas=Count("etapas", distinct=True),
            total_tarjetas=Count("etapas__tareas", distinct=True),
            total_comentarios=Count("etapas__tareas__comentarios", distinct=True),
        )
        .prefetch_related("etapas__tareas")
    )
    context = {
        "form": form,
        "edit_project": edit_project,
        "edit_project_form": edit_project_form,
        "proyectos": proyectos,
        "can_manage_wbs_board": can_manage_wbs_board(request.user),
    }
    return render(request, "gestor_documentos/wbs_projects.html", context)


@login_required
def wbs_board(request, project_id):
    ensure_role_groups()
    if not can_view_wbs_board(request.user):
        return redirect("inicio")

    proyecto = get_object_or_404(WbsProyecto, pk=project_id)
    assignable_users = _get_wbs_assignable_users()
    stage_form = WbsEtapaForm(prefix="stage")
    comment_form = WbsComentarioForm(prefix="comment")
    description_form = WbsDescripcionTareaForm(prefix="description")
    subtask_form = WbsSubtareaForm(prefix="subtask")
    image_form = WbsAdjuntoImagenForm(prefix="image")

    edit_stage = None
    edit_stage_form = None
    edit_task = None
    edit_task_form = None

    edit_stage_id = request.GET.get("editar_etapa")
    edit_task_id = request.GET.get("editar_tarea")
    selected_task_id = request.GET.get("tarea")
    active_stage_id = request.GET.get("columna")

    task_form = WbsTareaForm(prefix="task", assignable_users=assignable_users, proyecto=proyecto)
    if active_stage_id and str(active_stage_id).isdigit():
        task_form.fields["etapa"].initial = int(active_stage_id)

    if edit_stage_id and str(edit_stage_id).isdigit():
        edit_stage = WbsEtapa.objects.filter(pk=int(edit_stage_id), proyecto=proyecto).first()
        if edit_stage:
            edit_stage_form = WbsEtapaForm(instance=edit_stage, prefix="edit-stage")

    if edit_task_id and str(edit_task_id).isdigit():
        edit_task = (
            WbsTarea.objects.select_related("etapa", "asignado_a")
            .filter(pk=int(edit_task_id), etapa__proyecto=proyecto)
            .first()
        )
        if edit_task:
            edit_task_form = WbsTareaForm(
                instance=edit_task,
                assignable_users=assignable_users,
                proyecto=proyecto,
                prefix="edit-task",
            )

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "crear_etapa":
            if not can_manage_wbs_board(request.user):
                messages.error(request, "No tienes permisos para crear etapas.")
                return redirect("wbs_board", project_id=proyecto.id)
            stage_form = WbsEtapaForm(request.POST, prefix="stage")
            if stage_form.is_valid():
                etapa = stage_form.save(commit=False)
                etapa.proyecto = proyecto
                etapa.created_by = request.user
                etapa.updated_by = request.user
                etapa.posicion = _get_next_stage_position(proyecto)
                etapa.save()
                messages.success(request, f"La etapa {etapa.nombre} se creo correctamente.")
                return redirect("wbs_board", project_id=proyecto.id)

        if action == "editar_etapa":
            if not can_manage_wbs_board(request.user):
                messages.error(request, "No tienes permisos para editar etapas.")
                return redirect("wbs_board", project_id=proyecto.id)
            stage_id = request.POST.get("stage_id")
            edit_stage = get_object_or_404(WbsEtapa, pk=stage_id, proyecto=proyecto)
            edit_stage_form = WbsEtapaForm(request.POST, instance=edit_stage, prefix="edit-stage")
            if edit_stage_form.is_valid():
                etapa = edit_stage_form.save(commit=False)
                etapa.updated_by = request.user
                etapa.save()
                messages.success(request, f"La etapa {etapa.nombre} se actualizo correctamente.")
                return redirect("wbs_board", project_id=proyecto.id)

        if action == "crear_tarea":
            if not can_manage_wbs_board(request.user):
                messages.error(request, "No tienes permisos para crear tareas.")
                return redirect("wbs_board", project_id=proyecto.id)
            task_form = WbsTareaForm(request.POST, assignable_users=assignable_users, proyecto=proyecto, prefix="task")
            if task_form.is_valid():
                tarea = task_form.save(commit=False)
                tarea.numero_secuencial = _get_next_task_sequence(proyecto)
                tarea.codigo = _build_wbs_task_code(proyecto.prefijo, tarea.numero_secuencial)
                tarea.created_by = request.user
                tarea.updated_by = request.user
                tarea.posicion = _get_next_task_position(tarea.etapa)
                tarea.save()
                _sync_wbs_task_dependencies(
                    tarea,
                    task_form.cleaned_data.get("dependencias"),
                    request.user,
                )
                messages.success(request, f"La tarea {tarea.titulo} se creo correctamente.")
                return redirect(f"{reverse('wbs_board', args=[proyecto.id])}?tarea={tarea.id}")

        if action == "editar_tarea":
            if not can_manage_wbs_board(request.user):
                messages.error(request, "No tienes permisos para editar tareas.")
                return redirect("wbs_board", project_id=proyecto.id)
            task_id = request.POST.get("task_id")
            edit_task = get_object_or_404(WbsTarea, pk=task_id, etapa__proyecto=proyecto)
            previous_stage = edit_task.etapa
            edit_task_form = WbsTareaForm(
                request.POST,
                instance=edit_task,
                assignable_users=assignable_users,
                proyecto=proyecto,
                prefix="edit-task",
            )
            if edit_task_form.is_valid():
                tarea = edit_task_form.save(commit=False)
                tarea.updated_by = request.user
                if tarea.etapa_id != previous_stage.id:
                    tarea.posicion = _get_next_task_position(tarea.etapa)
                tarea.save()
                _sync_wbs_task_dependencies(
                    tarea,
                    edit_task_form.cleaned_data.get("dependencias"),
                    request.user,
                )
                if tarea.etapa_id != previous_stage.id:
                    _normalize_task_positions(previous_stage)
                messages.success(request, f"La tarea {tarea.titulo} se actualizo correctamente.")
                return redirect(f"{reverse('wbs_board', args=[proyecto.id])}?tarea={tarea.id}")

        if action == "comentar_tarea":
            if not can_comment_wbs_tasks(request.user):
                messages.error(request, "No tienes permisos para comentar tareas.")
                return redirect("wbs_board", project_id=proyecto.id)
            task_id = request.POST.get("task_id")
            tarea = get_object_or_404(WbsTarea, pk=task_id, etapa__proyecto=proyecto)
            comment_form = WbsComentarioForm(request.POST, prefix="comment")
            if comment_form.is_valid():
                comentario = comment_form.save(commit=False)
                comentario.tarea = tarea
                comentario.created_by = request.user
                comentario.save()
                messages.success(request, "El comentario se guardo correctamente.")
                return redirect(f"{reverse('wbs_board', args=[proyecto.id])}?tarea={tarea.id}")

        if action == "actualizar_descripcion_tarea":
            if not can_manage_wbs_board(request.user):
                messages.error(request, "No tienes permisos para editar la descripcion de la tarjeta.")
                return redirect("wbs_board", project_id=proyecto.id)
            task_id = request.POST.get("task_id")
            tarea = get_object_or_404(WbsTarea, pk=task_id, etapa__proyecto=proyecto)
            description_form = WbsDescripcionTareaForm(request.POST, instance=tarea, prefix="description")
            if description_form.is_valid():
                tarea = description_form.save(commit=False)
                tarea.updated_by = request.user
                tarea.save(update_fields=["descripcion", "updated_by", "fecha_actualizacion"])
                messages.success(request, "La descripcion de la tarjeta se actualizo correctamente.")
                return redirect(f"{reverse('wbs_board', args=[proyecto.id])}?tarea={tarea.id}")

        if action == "crear_subtarea":
            if not can_manage_wbs_board(request.user):
                messages.error(request, "No tienes permisos para crear subtareas.")
                return redirect("wbs_board", project_id=proyecto.id)
            task_id = request.POST.get("task_id")
            tarea = get_object_or_404(WbsTarea, pk=task_id, etapa__proyecto=proyecto)
            subtask_form = WbsSubtareaForm(request.POST, prefix="subtask")
            if subtask_form.is_valid():
                subtarea = subtask_form.save(commit=False)
                subtarea.tarea = tarea
                subtarea.posicion = _get_next_subtask_position(tarea)
                subtarea.created_by = request.user
                subtarea.updated_by = request.user
                subtarea.save()
                messages.success(request, "La subtarea se creo correctamente.")
                return redirect(f"{reverse('wbs_board', args=[proyecto.id])}?tarea={tarea.id}")

        if action == "toggle_subtarea":
            if not can_comment_wbs_tasks(request.user):
                messages.error(request, "No tienes permisos para actualizar subtareas.")
                return redirect("wbs_board", project_id=proyecto.id)
            task_id = request.POST.get("task_id")
            subtask_id = request.POST.get("subtask_id")
            tarea = get_object_or_404(WbsTarea, pk=task_id, etapa__proyecto=proyecto)
            subtarea = get_object_or_404(WbsSubtarea, pk=subtask_id, tarea=tarea)
            subtarea.completada = request.POST.get("completada") == "1"
            subtarea.updated_by = request.user
            subtarea.save(update_fields=["completada", "updated_by", "fecha_actualizacion"])
            return redirect(f"{reverse('wbs_board', args=[proyecto.id])}?tarea={tarea.id}")

        if action == "adjuntar_imagen_tarea":
            if not can_manage_wbs_board(request.user):
                messages.error(request, "No tienes permisos para adjuntar archivos en tareas.")
                return redirect("wbs_board", project_id=proyecto.id)
            task_id = request.POST.get("task_id")
            tarea = get_object_or_404(WbsTarea, pk=task_id, etapa__proyecto=proyecto)
            image_form = WbsAdjuntoImagenForm(request.POST, request.FILES, prefix="image")
            if image_form.is_valid():
                adjunto = image_form.save(commit=False)
                adjunto.tarea = tarea
                adjunto.nombre = os.path.basename(adjunto.archivo.name)
                adjunto.created_by = request.user
                adjunto.save()
                messages.success(request, "El archivo se adjunto correctamente a la tarjeta.")
                return redirect(f"{reverse('wbs_board', args=[proyecto.id])}?tarea={tarea.id}")

    selected_task = None
    if selected_task_id and str(selected_task_id).isdigit():
        selected_task = (
            WbsTarea.objects.select_related("etapa", "asignado_a", "created_by", "updated_by")
            .prefetch_related(
                "comentarios__created_by",
                "adjuntos",
                "subtareas",
                Prefetch(
                    "dependencias",
                    queryset=WbsDependencia.objects.select_related("depende_de", "depende_de__etapa", "etapa_inicial_dependencia"),
                ),
            )
            .filter(pk=int(selected_task_id), etapa__proyecto=proyecto)
            .first()
        )
        if selected_task and not comment_form.is_bound:
            comment_form = WbsComentarioForm(prefix="comment")
        if selected_task and not description_form.is_bound:
            description_form = WbsDescripcionTareaForm(instance=selected_task, prefix="description")
        if selected_task and not subtask_form.is_bound:
            subtask_form = WbsSubtareaForm(prefix="subtask")
        if selected_task and not image_form.is_bound:
            image_form = WbsAdjuntoImagenForm(prefix="image")

    etapas = list(
        WbsEtapa.objects.filter(proyecto=proyecto).order_by("posicion", "id").prefetch_related(
            Prefetch(
                "tareas",
                queryset=(
                    WbsTarea.objects.select_related("asignado_a", "created_by", "updated_by")
                    .prefetch_related(
                        Prefetch(
                            "dependencias",
                            queryset=WbsDependencia.objects.select_related("depende_de", "depende_de__etapa"),
                        )
                    )
                    .annotate(
                        total_adjuntos=Count("adjuntos", distinct=True),
                        total_comentarios=Count("comentarios", distinct=True),
                    )
                    .order_by("posicion", "id")
                ),
            )
        )
    )

    context = {
        "proyecto": proyecto,
        "etapas": etapas,
        "stage_form": stage_form,
        "task_form": task_form,
        "comment_form": comment_form,
        "description_form": description_form,
        "subtask_form": subtask_form,
        "image_form": image_form,
        "edit_stage": edit_stage,
        "edit_stage_form": edit_stage_form,
        "edit_task": edit_task,
        "edit_task_form": edit_task_form,
        "selected_task": selected_task,
        "active_stage_id": int(active_stage_id) if active_stage_id and str(active_stage_id).isdigit() else None,
        "task_modal_abierto": bool((active_stage_id and str(active_stage_id).isdigit()) or task_form.errors),
        "next_task_code": _build_wbs_task_code(proyecto.prefijo, _get_next_task_sequence(proyecto)),
        "can_manage_wbs_board": can_manage_wbs_board(request.user),
        "can_move_wbs_tasks": can_move_wbs_tasks(request.user),
        "can_comment_wbs_tasks": can_comment_wbs_tasks(request.user),
    }
    return render(request, "gestor_documentos/wbs_board.html", context)


@login_required
def wbs_move_task(request, project_id, task_id):
    ensure_role_groups()
    if request.method != "POST" or not can_move_wbs_tasks(request.user):
        return JsonResponse({"ok": False, "message": "No tienes permisos para mover tareas."}, status=403)

    proyecto = get_object_or_404(WbsProyecto, pk=project_id)
    task = get_object_or_404(WbsTarea, pk=task_id, etapa__proyecto=proyecto)
    stage_id = request.POST.get("stage_id")
    position_value = request.POST.get("position", "0")

    if not str(stage_id).isdigit():
        return JsonResponse({"ok": False, "message": "La etapa de destino no es valida."}, status=400)
    if not str(position_value).isdigit():
        return JsonResponse({"ok": False, "message": "La posicion enviada no es valida."}, status=400)

    target_stage = get_object_or_404(WbsEtapa, pk=int(stage_id), proyecto=proyecto)
    target_position = int(position_value)

    if target_stage.id != task.etapa_id:
        blocking_dependencies = _get_wbs_blocking_dependencies(task)
        if blocking_dependencies:
            return JsonResponse(
                {
                    "ok": False,
                    "message": _build_wbs_dependency_block_message(blocking_dependencies),
                },
                status=409,
            )

    with transaction.atomic():
        _move_wbs_task(task, target_stage, target_position, request.user)

    return JsonResponse(
        {
            "ok": True,
            "task_id": task.id,
            "stage_id": target_stage.id,
            "position": task.posicion,
        }
    )


@login_required
def wbs_move_stage(request, project_id, stage_id):
    ensure_role_groups()
    if request.method != "POST" or not can_manage_wbs_board(request.user):
        return JsonResponse({"ok": False, "message": "No tienes permisos para mover listas."}, status=403)

    proyecto = get_object_or_404(WbsProyecto, pk=project_id)
    stage = get_object_or_404(WbsEtapa, pk=stage_id, proyecto=proyecto)
    position_value = request.POST.get("position", "0")

    if not str(position_value).isdigit():
        return JsonResponse({"ok": False, "message": "La posicion enviada no es valida."}, status=400)

    with transaction.atomic():
        _move_wbs_stage(stage, int(position_value), request.user)

    return JsonResponse(
        {
            "ok": True,
            "stage_id": stage.id,
            "position": stage.posicion,
        }
    )


@login_required
def configuraciones(request):
    ensure_role_groups()
    if not is_admin(request.user):
        return redirect("inicio")

    configuracion = SistemaConfiguracion.get_solo()
    if request.method == "POST":
        form = SistemaConfiguracionForm(request.POST, instance=configuracion)
        if form.is_valid():
            configuracion = form.save(commit=False)
            configuracion.updated_by = request.user
            configuracion.save()
            messages.success(request, "La configuracion de GitHub se actualizo correctamente.")
            return redirect("configuraciones")
    else:
        if not configuracion.github_owner:
            configuracion.github_owner = settings.GITHUB_OWNER
        if not configuracion.github_repo:
            configuracion.github_repo = settings.GITHUB_REPO
        if not configuracion.github_token:
            configuracion.github_token = settings.GITHUB_TOKEN
        form = SistemaConfiguracionForm(instance=configuracion)

    context = {
        "form": form,
        "configuracion": configuracion,
    }
    return render(request, "gestor_documentos/configuraciones.html", context)


@login_required
def buscador_documentacion(request):
    ensure_role_groups()
    denied = forbid_if_no_view_access(request.user)
    if denied:
        return denied

    query = (request.GET.get("q") or "").strip()
    resultados = []

    if query:
        documentos = (
            Documento.objects.select_related("proyecto", "carpeta")
            .prefetch_related("versiones")
            .filter(
                Q(nombre__icontains=query)
                | Q(versiones__contenido_markdown__icontains=query)
            )
            .distinct()
        )
        resultados = _build_search_results(documentos, query)

    context = {
        "search_query": query,
        "search_results": resultados,
        "search_total": len(resultados),
    }
    return render(request, "gestor_documentos/buscador_documentacion.html", context)


@login_required
def tickets(request):
    ensure_role_groups()
    if not can_view_tickets(request.user):
        return redirect("inicio")

    estado = request.GET.get("estado", "activos")
    tickets_qs = _get_tickets_queryset(request.user).select_related(
        "documento",
        "proyecto",
        "carpeta",
        "created_by",
        "closed_by",
    )

    if estado == "cerrado":
        tickets_qs = tickets_qs.filter(estado=Ticket.ESTADO_CERRADO)
    elif estado == "revision":
        tickets_qs = tickets_qs.filter(estado=Ticket.ESTADO_EN_REVISION)
    elif estado == "todos":
        pass
    else:
        estado = "activos"
        tickets_qs = tickets_qs.exclude(estado=Ticket.ESTADO_CERRADO)

    tickets_list = list(tickets_qs)
    for ticket in tickets_list:
        ticket.pending_label = _get_ticket_pending_label(ticket)
        ticket.pending_class = _get_ticket_pending_class(ticket)

    context = {
        "tickets": tickets_list,
        "estado": estado,
    }
    return render(request, "gestor_documentos/tickets.html", context)


@login_required
def ticket_detalle(request, ticket_id):
    ensure_role_groups()
    if not can_view_tickets(request.user):
        return redirect("inicio")

    ticket = get_object_or_404(
        _get_tickets_queryset(request.user)
        .select_related("documento", "proyecto", "carpeta", "created_by", "closed_by", "reviewed_by")
        .prefetch_related("adjuntos", "documento__versiones", "comentarios__created_by", "comentarios__documento_version"),
        pk=ticket_id,
    )
    resolver_form = TicketResolverForm()
    revision_form = TicketRevisionUsuarioForm()

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "resolver_ticket":
            if not can_manage_tickets(request.user):
                messages.error(request, "No tienes permisos para responder tickets.")
                return redirect("ticket_detalle", ticket_id=ticket.id)
            if ticket.estado == Ticket.ESTADO_CERRADO:
                messages.warning(request, "Este ticket ya esta cerrado.")
                return redirect("ticket_detalle", ticket_id=ticket.id)
            if ticket.estado != Ticket.ESTADO_ABIERTO:
                messages.warning(request, "Este ticket ya fue enviado a revision y ahora debe validarlo el usuario.")
                return redirect("ticket_detalle", ticket_id=ticket.id)

            resolver_form = TicketResolverForm(request.POST, request.FILES)
            if resolver_form.is_valid():
                try:
                    version = _resolver_ticket(
                        ticket=ticket,
                        actor=request.user,
                        comentario=resolver_form.cleaned_data["comentario"],
                        archivo_version=resolver_form.cleaned_data.get("archivo_version"),
                    )
                except (DocumentProcessingError, GitHubSyncError) as exc:
                    messages.error(request, str(exc))
                else:
                    if version is not None:
                        messages.success(
                            request,
                            f"El ticket {ticket.numero_ticket} se envio a revision con la version {version.version}.",
                        )
                    else:
                        messages.success(
                            request,
                            f"El ticket {ticket.numero_ticket} se envio a revision del usuario.",
                        )
                    return redirect("ticket_detalle", ticket_id=ticket.id)

        if action in {"aceptar_ticket", "regresar_ticket"}:
            if request.user != ticket.created_by:
                messages.error(request, "Solo quien levanto el ticket puede validar esta revision.")
                return redirect("ticket_detalle", ticket_id=ticket.id)
            if ticket.estado != Ticket.ESTADO_EN_REVISION:
                messages.warning(request, "Este ticket no esta esperando validacion del usuario.")
                return redirect("ticket_detalle", ticket_id=ticket.id)

            revision_form = TicketRevisionUsuarioForm(request.POST)
            if revision_form.is_valid():
                if action == "aceptar_ticket":
                    _aceptar_ticket(
                        ticket=ticket,
                        actor=request.user,
                        comentario=revision_form.cleaned_data["comentario"],
                    )
                    messages.success(request, f"Se cerro el ticket {ticket.numero_ticket}.")
                else:
                    _regresar_ticket_a_gestor(
                        ticket=ticket,
                        actor=request.user,
                        comentario=revision_form.cleaned_data["comentario"],
                    )
                    messages.success(request, f"El ticket {ticket.numero_ticket} regreso a trabajo del gestor.")
                return redirect("ticket_detalle", ticket_id=ticket.id)

    context = {
        "ticket": ticket,
        "resolver_form": resolver_form,
        "revision_form": revision_form,
        "can_manage_tickets": can_manage_tickets(request.user),
        "is_ticket_owner": request.user == ticket.created_by,
    }
    return render(request, "gestor_documentos/ticket_detalle.html", context)


@login_required
def marcar_notificacion_leida(request, notificacion_id):
    if request.method != "POST":
        return redirect("inicio")

    notificacion = get_object_or_404(NotificacionActividad, pk=notificacion_id)
    visible_para_usuario = (
        notificacion.destinatario_id is None or notificacion.destinatario_id == request.user.id
    )
    if not visible_para_usuario:
        return redirect("inicio")

    NotificacionLeida.objects.get_or_create(
        notificacion=notificacion,
        usuario=request.user,
    )
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("inicio")
    return redirect(next_url)


def _procesar_carga_documento(proyecto, carpeta_actual, archivo, actor):
    nombre_archivo = os.path.basename(archivo.name)
    extension = get_extension(nombre_archivo)
    contenido_markdown = convert_uploaded_file_to_markdown(archivo)

    with transaction.atomic():
        documento = (
            Documento.objects.select_for_update()
            .filter(
                proyecto=proyecto,
                carpeta=carpeta_actual,
                nombre=nombre_archivo,
            )
            .first()
        )

        if documento is None:
            documento = Documento.objects.create(
                proyecto=proyecto,
                carpeta=carpeta_actual,
                nombre=nombre_archivo,
                archivo=archivo,
                extension_original=extension,
                created_by=actor,
                updated_by=actor,
            )
            upsert_text_file(
                documento.github_markdown_path,
                contenido_markdown,
                f"Actualizar {documento.github_markdown_path} a version 1",
            )
            version = DocumentoVersion.objects.create(
                documento=documento,
                version=1,
                contenido_markdown=contenido_markdown,
                created_by=actor,
            )
            return "created", documento, version

        latest_version = documento.versiones.order_by("-version").first()
        if latest_version and latest_version.contenido_markdown == contenido_markdown:
            return "ignored", documento, None

        previous_file_name = documento.archivo.name
        latest_number = 1 if latest_version is None else latest_version.version
        nueva_version = latest_number + 1
        documento.archivo = archivo
        documento.extension_original = extension
        documento.updated_by = actor
        documento.save(update_fields=["archivo", "extension_original", "updated_by", "fecha_actualizacion"])
        upsert_text_file(
            documento.github_markdown_path,
            contenido_markdown,
            f"Actualizar {documento.github_markdown_path} a version {nueva_version}",
        )

        version = DocumentoVersion.objects.create(
            documento=documento,
            version=nueva_version,
            contenido_markdown=contenido_markdown,
            created_by=actor,
        )

    if previous_file_name and previous_file_name != documento.archivo.name:
        documento.archivo.storage.delete(previous_file_name)
    return "updated", documento, version


def _get_next_ticket_preview():
    max_value = Ticket.objects.aggregate(max_value=Max("numero_secuencial"))["max_value"] or 0
    return _format_ticket_number(max_value + 1)


def _format_ticket_number(numero):
    return f"TCK-{numero:06d}"


def _crear_ticket_desde_documento(proyecto, carpeta, documento, actor, titulo, descripcion, archivos):
    with transaction.atomic():
        next_sequence = (Ticket.objects.select_for_update().aggregate(max_value=Max("numero_secuencial"))["max_value"] or 0) + 1
        ticket = Ticket.objects.create(
            numero_secuencial=next_sequence,
            numero_ticket=_format_ticket_number(next_sequence),
            documento=documento,
            proyecto=proyecto,
            carpeta=carpeta,
            titulo=titulo,
            descripcion=descripcion,
            created_by=actor,
        )
        for archivo in archivos:
            TicketAdjunto.objects.create(
                ticket=ticket,
                archivo=archivo,
                nombre=archivo.name,
                created_by=actor,
            )

    detalle = (
        f"{actor.username} levanto el ticket {ticket.numero_ticket} sobre {documento.nombre}: {titulo}."
    )
    gestores = User.objects.filter(Q(is_superuser=True) | Q(groups__name="Gestor")).distinct()
    for gestor in gestores:
        registrar_notificacion(
            NotificacionActividad.TIPO_TICKET_CREADO,
            f"Ticket nuevo {ticket.numero_ticket}",
            actor,
            detalle,
            destinatario=gestor,
        )
    return ticket


def _registrar_revision_documento(documento, actor, comentario):
    latest_version = documento.versiones.order_by("-version").first()
    if latest_version is None:
        raise DocumentProcessingError("Este documento aun no tiene versiones para revisar.")

    revision = DocumentoRevision.objects.create(
        documento=documento,
        version=latest_version,
        comentario=comentario,
        created_by=actor,
    )
    detalle = (
        f"{actor.username} marco como revisada la version {latest_version.version} del documento {documento.nombre}."
    )
    if comentario:
        detalle += f" Comentario: {comentario}"
    gestores = User.objects.filter(Q(is_superuser=True) | Q(groups__name="Gestor")).distinct()
    for gestor in gestores:
        registrar_notificacion(
            NotificacionActividad.TIPO_DOCUMENTO_REVISADO,
            f"Documento revisado: {documento.nombre}",
            actor,
            detalle,
            destinatario=gestor,
        )
    return revision


def _resolver_ticket(ticket, actor, comentario, archivo_version):
    version = None
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if archivo_version:
            if os.path.basename(archivo_version.name) != ticket.documento.nombre:
                raise DocumentProcessingError(
                    "La nueva version debe conservar exactamente el mismo nombre del documento original."
                )
            resultado, documento, version = _procesar_carga_documento(
                ticket.proyecto,
                ticket.carpeta,
                archivo_version,
                actor,
            )
            if resultado == "created":
                registrar_notificacion(
                    NotificacionActividad.TIPO_DOCUMENTO_SUBIDO,
                    f"Documento subido: {documento.nombre}",
                    actor,
                    f"{actor.username} subio el documento {documento.nombre} desde el ticket {ticket.numero_ticket}.",
                )
            elif resultado == "updated":
                registrar_notificacion(
                    NotificacionActividad.TIPO_DOCUMENTO_MODIFICADO,
                    f"Modificaciones a {documento.nombre}",
                    actor,
                    f"{actor.username} modifico el documento {documento.nombre} desde el ticket {ticket.numero_ticket}.",
                )

        TicketComentario.objects.create(
            ticket=ticket,
            tipo=TicketComentario.TIPO_RESPUESTA_GESTOR,
            comentario=comentario,
            documento_version=version,
            created_by=actor,
        )
        ticket.estado = Ticket.ESTADO_EN_REVISION
        ticket.reviewed_by = actor
        ticket.fecha_revision = timezone.now()
        ticket.save(update_fields=["estado", "reviewed_by", "fecha_revision"])

    detalle = f"{actor.username} respondio el ticket {ticket.numero_ticket} y lo envio a revision del usuario."
    if version is not None:
        detalle += f" Se genero la version {version.version} del documento."
    registrar_notificacion(
        NotificacionActividad.TIPO_TICKET_REVISION,
        f"Ticket en revision {ticket.numero_ticket}",
        actor,
        detalle,
        destinatario=ticket.created_by,
    )
    return version


def _aceptar_ticket(ticket, actor, comentario):
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        TicketComentario.objects.create(
            ticket=ticket,
            tipo=TicketComentario.TIPO_ACEPTACION_USUARIO,
            comentario=comentario,
            created_by=actor,
        )
        ticket.estado = Ticket.ESTADO_CERRADO
        ticket.closed_by = actor
        ticket.fecha_cierre = timezone.now()
        ticket.save(update_fields=["estado", "closed_by", "fecha_cierre"])

    detalle = f"{actor.username} acepto la solucion y cerro el ticket {ticket.numero_ticket}."
    gestores = User.objects.filter(Q(is_superuser=True) | Q(groups__name="Gestor")).distinct()
    for gestor in gestores:
        registrar_notificacion(
            NotificacionActividad.TIPO_TICKET_CERRADO,
            f"Ticket cerrado {ticket.numero_ticket}",
            actor,
            detalle,
            destinatario=gestor,
        )


def _regresar_ticket_a_gestor(ticket, actor, comentario):
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        TicketComentario.objects.create(
            ticket=ticket,
            tipo=TicketComentario.TIPO_RECHAZO_USUARIO,
            comentario=comentario,
            created_by=actor,
        )
        ticket.estado = Ticket.ESTADO_ABIERTO
        ticket.save(update_fields=["estado"])

    detalle = f"{actor.username} regreso el ticket {ticket.numero_ticket} con nuevas observaciones."
    gestores = User.objects.filter(Q(is_superuser=True) | Q(groups__name="Gestor")).distinct()
    for gestor in gestores:
        registrar_notificacion(
            NotificacionActividad.TIPO_TICKET_REABIERTO,
            f"Ticket reabierto {ticket.numero_ticket}",
            actor,
            detalle,
            destinatario=gestor,
        )


def _get_tickets_queryset(user):
    queryset = Ticket.objects.all()
    if can_manage_tickets(user):
        return queryset
    if is_visualizador(user):
        return queryset.filter(created_by=user)
    return queryset.none()


def _get_ticket_pending_label(ticket):
    if ticket.estado == Ticket.ESTADO_ABIERTO:
        return "Pendiente gestor"
    if ticket.estado == Ticket.ESTADO_EN_REVISION:
        return "Pendiente usuario"
    return "Completado"


def _get_ticket_pending_class(ticket):
    if ticket.estado == Ticket.ESTADO_ABIERTO:
        return "gestor"
    if ticket.estado == Ticket.ESTADO_EN_REVISION:
        return "usuario"
    return "completado"


def _attach_document_status(documento):
    latest_version = next(iter(documento.versiones.all()), None)
    latest_revision = next(iter(documento.revisiones.all()), None)

    if latest_version is None:
        documento.status_label = "Sin versiones disponibles"
        documento.status_class = "neutral"
        documento.status_detail = ""
        return

    if latest_revision is None:
        documento.status_label = f"Pendiente revision de v{latest_version.version}"
        documento.status_class = "pending"
        documento.status_detail = "Aun no hay una revision registrada para este documento."
        return

    reviewed_version = latest_revision.version.version
    if reviewed_version == latest_version.version:
        documento.status_label = f"Version revisada: v{reviewed_version}"
        documento.status_class = "reviewed"
        documento.status_detail = (
            f"Revisada por {latest_revision.created_by.username if latest_revision.created_by else 'Sistema'} "
            f"el {timezone.localtime(latest_revision.fecha_creacion).strftime('%d/%m/%Y %H:%M')}."
        )
        return

    documento.status_label = f"Revisada v{reviewed_version} | pendiente v{latest_version.version}"
    documento.status_class = "outdated"
    documento.status_detail = (
        f"La ultima revision fue de {latest_revision.created_by.username if latest_revision.created_by else 'Sistema'} "
        f"y ya existe una version nueva por validar."
    )


def _build_document_status_snapshot():
    documentos = (
        Documento.objects.all()
        .prefetch_related("versiones", "revisiones__version", "revisiones__created_by")
    )
    snapshot = []
    for documento in documentos:
        latest_version = next(iter(documento.versiones.all()), None)
        latest_revision = next(iter(documento.revisiones.all()), None)
        reviewed_version = latest_revision.version.version if latest_revision else None

        snapshot.append(
            {
                "documento_id": documento.id,
                "has_version": latest_version is not None,
                "is_pending": latest_version is not None and reviewed_version != latest_version.version,
                "is_reviewed": latest_version is not None and reviewed_version == latest_version.version,
            }
        )
    return snapshot


def _can_access_standard_dashboard(user):
    return user.is_authenticated and (is_admin(user) or is_visualizador(user) or is_wbs(user))


def _get_wbs_assignable_users():
    return (
        User.objects.filter(
            Q(groups__name="WBS") | Q(groups__name="WBS_Desarrollo")
        )
        .distinct()
        .order_by("username")
    )


def _get_next_stage_position(proyecto):
    return (
        WbsEtapa.objects.filter(proyecto=proyecto).aggregate(max_position=Max("posicion"))["max_position"] or 0
    ) + 1


def _get_next_task_position(stage):
    return (
        WbsTarea.objects.filter(etapa=stage).aggregate(max_position=Max("posicion"))["max_position"] or 0
    ) + 1


def _get_next_subtask_position(task):
    return (
        WbsSubtarea.objects.filter(tarea=task).aggregate(max_position=Max("posicion"))["max_position"] or 0
    ) + 1


def _sync_wbs_task_dependencies(task, dependency_tasks, actor):
    dependency_tasks = list(dependency_tasks or [])
    dependency_ids = {dependency.pk for dependency in dependency_tasks}
    existing_dependencies = {
        dependency.depende_de_id: dependency
        for dependency in WbsDependencia.objects.filter(tarea=task).select_related("depende_de", "etapa_inicial_dependencia")
    }

    for dependency_id, dependency in existing_dependencies.items():
        if dependency_id not in dependency_ids:
            dependency.delete()

    for dependency_task in dependency_tasks:
        if dependency_task.pk in existing_dependencies:
            continue
        WbsDependencia.objects.create(
            tarea=task,
            depende_de=dependency_task,
            etapa_inicial_dependencia=dependency_task.etapa,
            created_by=actor,
        )


def _get_wbs_blocking_dependencies(task):
    return list(
        WbsDependencia.objects.select_related("depende_de", "depende_de__etapa", "etapa_inicial_dependencia")
        .filter(
            tarea=task,
            depende_de__etapa_id=models.F("etapa_inicial_dependencia_id"),
        )
        .order_by("depende_de__numero_secuencial", "depende_de__id")
    )


def _build_wbs_dependency_block_message(blocking_dependencies):
    if not blocking_dependencies:
        return "Existe una dependencia que hay que terminar antes de mover esta tarjeta."

    dependency_names = [
        f"{dependency.depende_de.codigo} ({dependency.depende_de.etapa.nombre})"
        for dependency in blocking_dependencies[:3]
    ]
    dependency_text = ", ".join(dependency_names)
    if len(blocking_dependencies) == 1:
        return f"Existe una dependencia que hay que terminar antes de mover esta tarjeta: {dependency_text}."
    if len(blocking_dependencies) > 3:
        dependency_text += f" y {len(blocking_dependencies) - 3} mas"
    return f"Existen dependencias pendientes que debes terminar antes de mover esta tarjeta: {dependency_text}."


def _get_next_task_sequence(proyecto):
    return (
        WbsTarea.objects.filter(etapa__proyecto=proyecto).aggregate(max_sequence=Max("numero_secuencial"))[
            "max_sequence"
        ]
        or 0
    ) + 1


def _build_wbs_task_code(prefijo, numero_secuencial):
    return f"{prefijo}-{numero_secuencial:03d}"


def _normalize_task_positions(stage):
    tareas = list(WbsTarea.objects.filter(etapa=stage).order_by("posicion", "id"))
    for index, tarea in enumerate(tareas):
        if tarea.posicion != index:
            WbsTarea.objects.filter(pk=tarea.pk).update(posicion=index)


def _normalize_stage_positions(proyecto):
    etapas = list(WbsEtapa.objects.filter(proyecto=proyecto).order_by("posicion", "id"))
    for index, etapa in enumerate(etapas):
        if etapa.posicion != index:
            WbsEtapa.objects.filter(pk=etapa.pk).update(posicion=index)


def _move_wbs_stage(stage, target_position, actor):
    proyecto = stage.proyecto
    stages = list(WbsEtapa.objects.filter(proyecto=proyecto).exclude(pk=stage.pk).order_by("posicion", "id"))
    bounded_position = max(0, min(target_position, len(stages)))
    stages.insert(bounded_position, stage)

    for index, current_stage in enumerate(stages):
        current_stage.posicion = index
        if current_stage.pk == stage.pk:
            current_stage.updated_by = actor
        current_stage.save(update_fields=["posicion", "updated_by", "fecha_actualizacion"])

    _normalize_stage_positions(proyecto)
    stage.refresh_from_db(fields=["posicion"])


def _move_wbs_task(task, target_stage, target_position, actor):
    source_stage = task.etapa
    current_stage_tasks = list(WbsTarea.objects.filter(etapa=target_stage).exclude(pk=task.pk).order_by("posicion", "id"))
    bounded_position = max(0, min(target_position, len(current_stage_tasks)))
    current_stage_tasks.insert(bounded_position, task)

    task.etapa = target_stage
    task.updated_by = actor

    for index, stage_task in enumerate(current_stage_tasks):
        stage_task.posicion = index
        if stage_task.pk == task.pk:
            stage_task.etapa = target_stage
            stage_task.updated_by = actor
        stage_task.save(update_fields=["etapa", "posicion", "updated_by", "fecha_actualizacion"])

    if source_stage_id := getattr(source_stage, "id", None):
        if source_stage_id != target_stage.id:
            _normalize_task_positions(source_stage)

    task.refresh_from_db(fields=["posicion", "etapa"])


def _build_inicio_dashboard(user):
    if is_visualizador(user) or (is_wbs(user) and not user.is_superuser and not user.groups.filter(name="Gestor").exists()):
        return _build_visualizador_dashboard(user)
    return _build_gestor_dashboard(user)


def _build_visualizador_dashboard(user):
    document_statuses = _build_document_status_snapshot()
    tickets_usuario = Ticket.objects.filter(created_by=user)
    tickets_en_revision = tickets_usuario.filter(estado=Ticket.ESTADO_EN_REVISION)
    tickets_reabiertos = (
        tickets_usuario.filter(estado=Ticket.ESTADO_ABIERTO, comentarios__tipo=TicketComentario.TIPO_RECHAZO_USUARIO)
        .distinct()
        .count()
    )
    documentos_con_cambios = sum(1 for item in document_statuses if item["is_pending"])
    documentos_revisados = sum(1 for item in document_statuses if item["is_reviewed"])

    stats = [
        {
            "tone": "blue",
            "value": documentos_con_cambios,
            "label": "documentos con cambios sin revisar",
        },
        {
            "tone": "orange",
            "value": tickets_en_revision.count(),
            "label": "tickets respondidos pendientes de validar",
        },
        {
            "tone": "red",
            "value": tickets_reabiertos,
            "label": "tickets reabiertos",
        },
        {
            "tone": "green",
            "value": documentos_revisados,
            "label": "documentos revisados sin cambios",
        },
    ]

    pending_documents = _build_pending_documents()

    return {
        "dashboard_title": "Mi trabajo",
        "dashboard_role": "Visualizador",
        "dashboard_stats": stats,
        "recent_activity": _build_recent_activity(),
        "pending_documents": pending_documents,
    }


def _build_gestor_dashboard(user):
    document_statuses = _build_document_status_snapshot()
    tickets_abiertos = Ticket.objects.filter(estado=Ticket.ESTADO_ABIERTO)
    tickets_reabiertos = tickets_abiertos.filter(comentarios__tipo=TicketComentario.TIPO_RECHAZO_USUARIO).distinct()
    documentos_pendientes_validacion = sum(1 for item in document_statuses if item["is_pending"])
    documentos_revisados = sum(1 for item in document_statuses if item["is_reviewed"])

    stats = [
        {
            "tone": "red",
            "value": tickets_abiertos.count(),
            "label": "tickets abiertos",
        },
        {
            "tone": "orange",
            "value": tickets_reabiertos.count(),
            "label": "tickets esperando correccion",
        },
        {
            "tone": "blue",
            "value": documentos_pendientes_validacion,
            "label": "documentos pendientes de validacion",
        },
        {
            "tone": "green",
            "value": documentos_revisados,
            "label": "documentos revisados sin cambios",
        },
    ]

    return {
        "dashboard_title": "Mi trabajo",
        "dashboard_role": "Gestor",
        "dashboard_stats": stats,
        "recent_activity": _build_recent_activity(),
    }


def _build_pending_documents(limit=12):
    documentos = (
        Documento.objects.select_related("proyecto", "carpeta")
        .prefetch_related("versiones", "revisiones__version", "revisiones__created_by")
        .order_by("-fecha_actualizacion")
    )
    pending = []
    for documento in documentos:
        _attach_document_status(documento)
        latest_version = next(iter(documento.versiones.all()), None)
        latest_revision = next(iter(documento.revisiones.all()), None)
        reviewed_version = latest_revision.version.version if latest_revision else None
        if latest_version is None or reviewed_version == latest_version.version:
            continue
        pending.append(
            {
                "id": documento.id,
                "nombre": documento.nombre,
                "proyecto_nombre": documento.proyecto.nombre,
                "ubicacion": documento.carpeta.nombre if documento.carpeta_id else "Raiz",
                "status_label": documento.status_label,
                "status_class": documento.status_class,
                "status_detail": documento.status_detail,
                "archivo_url": documento.archivo.url,
                "cambios_url": reverse("documento_cambios", args=[documento.proyecto_id, documento.id]),
            }
        )
        if len(pending) >= limit:
            break
    return pending


def _build_recent_activity(limit=8):
    notifications = list(
        NotificacionActividad.objects.select_related("actor").order_by("-fecha_creacion")[:30]
    )
    recent = []
    seen = set()
    for notification in notifications:
        key = (
            notification.tipo,
            notification.titulo,
            notification.detalle,
            notification.actor_id,
            notification.fecha_creacion.replace(microsecond=0),
        )
        if key in seen:
            continue
        seen.add(key)
        recent.append(
            {
                "eyebrow": notification.get_tipo_display(),
                "title": notification.titulo,
                "subtitle": notification.detalle,
                "timestamp": notification.fecha_creacion,
                "action_label": _get_notification_action_label(notification),
                "action_url": _get_notification_action_url(notification),
            }
        )
        if len(recent) >= limit:
            break
    return recent


def _build_search_results(documentos, query, limit=40):
    normalized_query = query.casefold()
    resultados = []

    for documento in documentos:
        latest_version = next(iter(documento.versiones.all()), None)
        contenido = latest_version.contenido_markdown if latest_version else ""
        nombre_score = _score_search_match(documento.nombre, normalized_query)
        contenido_score = _score_search_match(contenido, normalized_query)
        score = max(nombre_score, contenido_score)
        if score <= 0:
            continue

        resultados.append(
            {
                "documento": documento,
                "score": score,
                "snippet": _build_search_snippet(contenido, query),
                "path_label": _build_document_system_path(documento),
                "latest_version": latest_version.version if latest_version else None,
                "open_url": documento.archivo.url,
                "explorer_url": reverse("documentacion_proyecto", args=[documento.proyecto_id])
                + (f"?carpeta={documento.carpeta_id}" if documento.carpeta_id else ""),
            }
        )

    resultados.sort(key=lambda item: (-item["score"], item["documento"].nombre.lower()))
    return resultados[:limit]


def _score_search_match(text, normalized_query):
    if not text:
        return 0

    normalized_text = text.casefold()
    if normalized_query in normalized_text:
        position = normalized_text.find(normalized_query)
        proximity_bonus = max(0, 150 - position)
        return 500 + proximity_bonus

    words = [segment for segment in normalized_text.replace("\n", " ").split(" ") if segment]
    best_ratio = 0
    for word in words:
        best_ratio = max(best_ratio, SequenceMatcher(None, normalized_query, word).ratio())
    return int(best_ratio * 100)


def _build_search_snippet(content, query, radius=180):
    if not content:
        return "Este documento no tiene contenido Markdown disponible todavia."

    normalized_content = content.casefold()
    normalized_query = query.casefold()
    match_index = normalized_content.find(normalized_query)

    if match_index == -1:
        compact = " ".join(content.split())
        return compact[: radius + 40] + ("..." if len(compact) > radius + 40 else "")

    start = max(0, match_index - radius // 2)
    end = min(len(content), match_index + len(query) + radius)
    snippet = " ".join(content[start:end].split())
    if start > 0:
        snippet = f"...{snippet}"
    if end < len(content):
        snippet = f"{snippet}..."
    return snippet


def _build_document_system_path(documento):
    segmentos = [documento.proyecto.nombre]
    carpeta = documento.carpeta
    ruta_carpetas = []

    while carpeta is not None:
        ruta_carpetas.append(carpeta.nombre)
        carpeta = carpeta.parent

    if ruta_carpetas:
        segmentos.extend(reversed(ruta_carpetas))
    segmentos.append(documento.nombre)
    return " / ".join(segmentos)


def _get_notification_action_label(notification):
    if "ticket" in notification.tipo:
        return "Abrir tickets"
    if notification.tipo in {
        NotificacionActividad.TIPO_DOCUMENTO_SUBIDO,
        NotificacionActividad.TIPO_DOCUMENTO_MODIFICADO,
        NotificacionActividad.TIPO_DOCUMENTO_REVISADO,
    }:
        return "Ir a documentacion"
    return "Ver actividad"


def _get_notification_action_url(notification):
    if "ticket" in notification.tipo:
        return reverse("tickets")
    if notification.tipo in {
        NotificacionActividad.TIPO_DOCUMENTO_SUBIDO,
        NotificacionActividad.TIPO_DOCUMENTO_MODIFICADO,
        NotificacionActividad.TIPO_DOCUMENTO_REVISADO,
        NotificacionActividad.TIPO_PROYECTO_CREADO,
        NotificacionActividad.TIPO_CARPETA_CREADA,
    }:
        return reverse("documentacion")
    return reverse("inicio")


def _resolver_version(versiones, requested_value, default):
    if requested_value and str(requested_value).isdigit():
        requested_number = int(requested_value)
        for version in versiones:
            if version.version == requested_number:
                return version
    return default


def _build_upload_result_message(resultado, document_name, version):
    if resultado == "created" and version is not None:
        return f"{document_name} se cargo y se convirtio a Markdown como version {version.version}."
    if resultado == "updated" and version is not None:
        return f"{document_name} se actualizo y se sincronizo como version {version.version}."
    if resultado == "ignored":
        return f"{document_name} no tuvo cambios y se ignoro."
    return f"{document_name} se proceso correctamente."


def _build_document_preview_html(diff_rows, side):
    annotated_lines = []
    text_key = "old_text" if side == "old" else "new_text"
    skip_kind = "added" if side == "old" else "removed"

    for row in diff_rows:
        if row["kind"] == skip_kind:
            continue

        text = row.get(text_key) or ""
        if row["kind"] == "changed":
            line_kind = "changed"
        elif row["kind"] == "equal":
            line_kind = "equal"
        elif row["kind"] == "added":
            line_kind = "added"
        else:
            line_kind = "removed"
        annotated_lines.append({"text": text, "kind": line_kind})

    return _render_annotated_markdown_html(annotated_lines)


def _render_annotated_markdown_html(annotated_lines):
    html_parts = []
    index = 0

    while index < len(annotated_lines):
        current = annotated_lines[index]
        text = current["text"]
        stripped = text.strip()

        if not stripped:
            html_parts.append(f'<div class="doc-preview-spacer state-{current["kind"]}"></div>')
            index += 1
            continue

        if _is_markdown_table_row(stripped):
            table_rows = []
            while index < len(annotated_lines) and _is_markdown_table_row(annotated_lines[index]["text"].strip()):
                table_rows.append(annotated_lines[index])
                index += 1
            html_parts.append(_render_annotated_table_html(table_rows))
            continue

        if stripped.startswith("#"):
            level = min(len(stripped) - len(stripped.lstrip("#")), 6)
            content = stripped[level:].strip() or stripped
            html_parts.append(
                f'<div class="doc-preview-block state-{current["kind"]}"><h{level}>{escape(content)}</h{level}></div>'
            )
            index += 1
            continue

        list_marker = _extract_list_marker(stripped)
        if list_marker:
            tag = "ol" if list_marker["ordered"] else "ul"
            items = []
            while index < len(annotated_lines):
                item_line = annotated_lines[index]
                marker = _extract_list_marker((item_line["text"] or "").strip())
                if not marker:
                    break
                items.append(
                    f'<li class="state-{item_line["kind"]}">{escape(marker["content"])}</li>'
                )
                index += 1
            html_parts.append(f'<div class="doc-preview-list-wrap"><{tag} class="doc-preview-list">{"".join(items)}</{tag}></div>')
            continue

        html_parts.append(
            f'<div class="doc-preview-block state-{current["kind"]}"><p>{escape(text)}</p></div>'
        )
        index += 1

    return "".join(html_parts)


def _is_markdown_table_row(text):
    return text.startswith("|") and text.endswith("|")


def _render_annotated_table_html(table_rows):
    parsed_rows = []
    for row in table_rows:
        cells = [escape(cell.strip()) for cell in row["text"].strip().strip("|").split("|")]
        parsed_rows.append({"kind": row["kind"], "cells": cells})

    if len(parsed_rows) >= 2 and all(cell.replace("-", "").replace(":", "") == "" for cell in parsed_rows[1]["cells"]):
        header = parsed_rows[0]
        body = parsed_rows[2:]
    else:
        header = parsed_rows[0]
        body = parsed_rows[1:]

    column_count = len(header["cells"])
    thead = "".join(f"<th>{cell}</th>" for cell in header["cells"])
    body_rows = []
    for row in body:
        cells = row["cells"] + [""] * (column_count - len(row["cells"]))
        body_rows.append(
            f'<tr class="state-{row["kind"]}">{"".join(f"<td>{cell}</td>" for cell in cells)}</tr>'
        )

    return (
        '<div class="doc-preview-table-wrap">'
        '<table class="doc-preview-table">'
        f'<thead><tr class="state-{header["kind"]}">{thead}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody>'
        "</table></div>"
    )


def _extract_list_marker(text):
    if text.startswith(("- ", "* ")):
        return {"ordered": False, "content": text[2:].strip()}

    parts = text.split(". ", 1)
    if len(parts) == 2 and parts[0].isdigit():
        return {"ordered": True, "content": parts[1].strip()}
    return None


def _build_diff_rows(base_text, actual_text):
    base_lines = base_text.splitlines()
    actual_lines = actual_text.splitlines()
    matcher = SequenceMatcher(a=base_lines, b=actual_lines)

    rows = []
    summary = {
        "added": 0,
        "removed": 0,
        "changed": 0,
        "unchanged": 0,
    }

    old_line_no = 1
    new_line_no = 1

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_chunk = base_lines[i1:i2]
        new_chunk = actual_lines[j1:j2]

        if tag == "equal":
            for old_text, new_text in zip(old_chunk, new_chunk):
                rows.append(
                    {
                        "kind": "equal",
                        "old_number": old_line_no,
                        "new_number": new_line_no,
                        "old_text": old_text,
                        "new_text": new_text,
                    }
                )
                summary["unchanged"] += 1
                old_line_no += 1
                new_line_no += 1
            continue

        if tag == "delete":
            for old_text in old_chunk:
                rows.append(
                    {
                        "kind": "removed",
                        "old_number": old_line_no,
                        "new_number": "",
                        "old_text": old_text,
                        "new_text": "",
                    }
                )
                summary["removed"] += 1
                old_line_no += 1
            continue

        if tag == "insert":
            for new_text in new_chunk:
                rows.append(
                    {
                        "kind": "added",
                        "old_number": "",
                        "new_number": new_line_no,
                        "old_text": "",
                        "new_text": new_text,
                    }
                )
                summary["added"] += 1
                new_line_no += 1
            continue

        if tag == "replace":
            max_len = max(len(old_chunk), len(new_chunk))
            for index in range(max_len):
                old_text = old_chunk[index] if index < len(old_chunk) else ""
                new_text = new_chunk[index] if index < len(new_chunk) else ""
                old_number = old_line_no if old_text != "" else ""
                new_number = new_line_no if new_text != "" else ""
                rows.append(
                    {
                        "kind": "changed",
                        "old_number": old_number,
                        "new_number": new_number,
                        "old_text": old_text,
                        "new_text": new_text,
                    }
                )
                summary["changed"] += 1
                if old_text != "":
                    old_line_no += 1
                if new_text != "":
                    new_line_no += 1

    return rows, summary
