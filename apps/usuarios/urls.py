from django.urls import path
from .views import (
    login_view,
    logout_view,
    cadastro_empresa_view,
    usuarios_list_view,
    usuario_create_view,
    usuario_edit_view,
    usuario_toggle_ativo_view,
    usuario_redefinir_senha_view,
)

urlpatterns = [
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('cadastro/', cadastro_empresa_view, name='cadastro_empresa'),
    path('', usuarios_list_view, name='usuarios_list'),
    path('novo/', usuario_create_view, name='usuario_novo'),
    path('<int:pk>/editar/', usuario_edit_view, name='usuario_editar'),
    path('<int:pk>/toggle-ativo/', usuario_toggle_ativo_view, name='usuario_toggle_ativo'),
    path('<int:pk>/redefinir-senha/', usuario_redefinir_senha_view, name='usuario_redefinir_senha'),
]
