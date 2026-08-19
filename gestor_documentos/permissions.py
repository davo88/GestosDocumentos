from django.contrib.auth.models import Group
from django.http import HttpResponseForbidden


ROLE_GESTOR = "Gestor"
ROLE_VISUALIZADOR = "Visualizador"
ROLE_WBS = "WBS"
ROLE_WBS_DESARROLLO = "WBS_Desarrollo"


def ensure_role_groups():
    Group.objects.get_or_create(name=ROLE_GESTOR)
    Group.objects.get_or_create(name=ROLE_VISUALIZADOR)
    Group.objects.get_or_create(name=ROLE_WBS)
    Group.objects.get_or_create(name=ROLE_WBS_DESARROLLO)


def is_admin(user):
    return user.is_authenticated and user.is_superuser


def is_gestor(user):
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name=ROLE_GESTOR).exists()
    )


def is_visualizador(user):
    return user.is_authenticated and user.groups.filter(name=ROLE_VISUALIZADOR).exists()


def is_wbs(user):
    return user.is_authenticated and user.groups.filter(name=ROLE_WBS).exists()


def is_wbs_desarrollo(user):
    return user.is_authenticated and user.groups.filter(name=ROLE_WBS_DESARROLLO).exists()


def can_view_wbs_board(user):
    return user.is_authenticated and (is_admin(user) or is_wbs(user) or is_wbs_desarrollo(user))


def can_manage_wbs_board(user):
    return user.is_authenticated and (is_admin(user) or is_wbs(user))


def can_comment_wbs_tasks(user):
    return can_view_wbs_board(user)


def can_move_wbs_tasks(user):
    return can_view_wbs_board(user)


def can_view_documentacion(user):
    return user.is_authenticated and (is_admin(user) or is_gestor(user) or is_visualizador(user) or is_wbs(user))


def can_manage_documentacion(user):
    return user.is_authenticated and (is_admin(user) or is_gestor(user))


def can_create_tickets(user):
    return is_visualizador(user)


def can_view_tickets(user):
    return can_view_documentacion(user)


def can_manage_tickets(user):
    return can_manage_documentacion(user)


def forbid_if_no_view_access(user):
    if can_view_documentacion(user):
        return None
    return HttpResponseForbidden("No tienes permisos para acceder a esta seccion.")
