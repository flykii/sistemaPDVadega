from django.urls import path
from .views import (
    relatorios_hub_view, relatorio_vendas_view, relatorio_formas_pagamento_view,
    relatorio_produtos_view, relatorio_categorias_view, relatorio_operadores_view,
    relatorio_caixas_view, relatorio_estoque_view, relatorio_movimentacoes_estoque_view,
    relatorio_despesas_view, relatorio_crediario_view, relatorio_reposicao_view,
    exportar_relatorio_csv_view, auditoria_view
)

urlpatterns = [
    path('', relatorios_hub_view, name='relatorios_hub'),
    path('vendas/', relatorio_vendas_view, name='relatorio_vendas'),
    path('formas-pagamento/', relatorio_formas_pagamento_view, name='relatorio_formas_pagamento'),
    path('produtos/', relatorio_produtos_view, name='relatorio_produtos'),
    path('reposicao/', relatorio_reposicao_view, name='relatorio_reposicao'),
    path('categorias/', relatorio_categorias_view, name='relatorio_categorias'),
    path('operadores/', relatorio_operadores_view, name='relatorio_operadores'),
    path('caixas/', relatorio_caixas_view, name='relatorio_caixas'),
    path('estoque/', relatorio_estoque_view, name='relatorio_estoque'),
    path('movimentacoes/', relatorio_movimentacoes_estoque_view, name='relatorio_movimentacoes'),
    path('despesas/', relatorio_despesas_view, name='relatorio_despesas'),
    path('crediario/', relatorio_crediario_view, name='relatorio_crediario'),
    path('exportar/<str:relatorio_tipo>/', exportar_relatorio_csv_view, name='exportar_relatorio_csv'),
    path('auditoria/', auditoria_view, name='auditoria'),
]

