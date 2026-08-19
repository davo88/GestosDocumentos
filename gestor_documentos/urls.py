from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from .views import (
    buscador_documentacion,
    configuraciones,
    crear_usuarios,
    documentacion,
    documentacion_proyecto,
    documento_cambios,
    documento_visualizador,
    inicio,
    landing,
    marcar_notificacion_leida,
    ticket_detalle,
    tickets,
)


urlpatterns = [
    path("", landing, name="landing"),
    path(
        "login/",
        LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("inicio/", inicio, name="inicio"),
    path("notificaciones/<int:notificacion_id>/leida/", marcar_notificacion_leida, name="marcar_notificacion_leida"),
    path("configuraciones/", configuraciones, name="configuraciones"),
    path("usuarios/", crear_usuarios, name="crear_usuarios"),
    path("tickets/", tickets, name="tickets"),
    path("buscador-documentacion/", buscador_documentacion, name="buscador_documentacion"),
    path("tickets/<int:ticket_id>/", ticket_detalle, name="ticket_detalle"),
    path("documentacion/", documentacion, name="documentacion"),
    path(
        "documentacion/<int:proyecto_id>/",
        documentacion_proyecto,
        name="documentacion_proyecto",
    ),
    path(
        "documentacion/<int:proyecto_id>/documento/<int:documento_id>/cambios/",
        documento_cambios,
        name="documento_cambios",
    ),
    path(
        "documentacion/<int:proyecto_id>/documento/<int:documento_id>/ver/",
        documento_visualizador,
        name="documento_visualizador",
    ),
]
