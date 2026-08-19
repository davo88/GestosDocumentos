from .models import NotificacionActividad
from .permissions import (
    can_manage_documentacion,
    can_view_wbs_board,
    is_admin,
    is_gestor,
    is_visualizador,
    is_wbs,
    is_wbs_desarrollo,
)


def role_flags(request):
    user = request.user
    notifications = []
    notifications_count = 0
    if getattr(user, "is_authenticated", False):
        queryset = NotificacionActividad.objects.select_related("actor", "destinatario").filter(
            destinatario__isnull=True
        ) | NotificacionActividad.objects.select_related("actor", "destinatario").filter(
            destinatario=user
        )
        queryset = queryset.exclude(lecturas__usuario=user)
        queryset = queryset.order_by("-fecha_creacion")
        notifications = list(queryset[:8])
        notifications_count = queryset.count()
    return {
        "is_admin_user": is_admin(user),
        "is_gestor_user": is_gestor(user),
        "is_visualizador_user": is_visualizador(user),
        "is_wbs_user": is_wbs(user),
        "is_wbs_desarrollo_user": is_wbs_desarrollo(user),
        "can_view_wbs_board": can_view_wbs_board(user),
        "can_manage_documentacion": can_manage_documentacion(user),
        "recent_notifications": notifications,
        "recent_notifications_count": notifications_count,
    }
