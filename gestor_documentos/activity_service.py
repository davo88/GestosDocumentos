from .models import NotificacionActividad


def registrar_notificacion(tipo, titulo, actor, detalle="", destinatario=None):
    return NotificacionActividad.objects.create(
        tipo=tipo,
        titulo=titulo,
        detalle=detalle,
        actor=actor,
        destinatario=destinatario,
    )
