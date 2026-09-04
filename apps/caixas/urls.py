from django.urls import path
from .views import (
    caixas_list, abrir_caixa_view, fechar_caixa_view,
    movimentacao_caixa_view, relatorio_caixa_view, relatorio_caixa_print_view
)

urlpatterns = [
    path('', caixas_list, name='caixas_list'),
    path('abrir/<int:caixa_id>/', abrir_caixa_view, name='abrir_caixa'),
    path('fechar/<int:sessao_id>/', fechar_caixa_view, name='fechar_caixa'),
    path('movimentacao/<int:sessao_id>/', movimentacao_caixa_view, name='movimentacao_caixa'),
    path('relatorio/<int:sessao_id>/', relatorio_caixa_view, name='relatorio_caixa'),
    path('relatorio/<int:sessao_id>/imprimir/', relatorio_caixa_print_view, name='relatorio_caixa_print'),
]
