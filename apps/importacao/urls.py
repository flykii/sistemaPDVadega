from django.urls import path
from .views import (
    importacao_hub,
    importacao_upload,
    importacao_mapeamento,
    importacao_validar_api,
    importacao_executar,
    importacao_detalhe
)

urlpatterns = [
    path('', importacao_hub, name='importacao_hub'),
    path('upload/', importacao_upload, name='importacao_upload'),
    path('mapeamento/', importacao_mapeamento, name='importacao_mapeamento'),
    path('api/validar/', importacao_validar_api, name='importacao_validar_api'),
    path('executar/', importacao_executar, name='importacao_executar'),
    path('detalhe/<int:importacao_id>/', importacao_detalhe, name='importacao_detalhe'),
]
