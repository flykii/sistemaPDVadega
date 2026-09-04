from django.urls import path
from .views import (
    contas_receber_list, receber_conta_view, baixar_conta_receber_view, cancelar_conta_receber_view,
    contas_pagar_list, despesa_form, pagar_despesa_view, cancelar_despesa_view,
    baixar_conta_pagar_view, despesas_recorrentes_list, despesa_recorrente_form,
    gerar_previsoes_view, categorias_despesa_list, categoria_despesa_form,
    fluxo_mensal_view, fluxo_caixa_list
)

urlpatterns = [
    # Contas a Receber (Crediário)
    path('receber/', contas_receber_list, name='contas_receber_list'),
    path('receber/<int:pk>/pagar/', receber_conta_view, name='receber_conta_pagar'),
    path('receber/<int:pk>/baixar/', baixar_conta_receber_view, name='baixar_conta_receber'),
    path('receber/<int:pk>/cancelar/', cancelar_conta_receber_view, name='cancelar_conta_receber'),


    # Despesas Avulsas e Contas a Pagar
    path('despesas/', contas_pagar_list, name='contas_pagar_list'),
    path('despesas/nova/', despesa_form, name='despesa_nova'),
    path('despesas/editar/<int:pk>/', despesa_form, name='despesa_editar'),
    path('despesas/<int:pk>/pagar/', pagar_despesa_view, name='pagar_despesa'),
    path('despesas/<int:pk>/cancelar/', cancelar_despesa_view, name='cancelar_despesa'),
    path('despesas/<int:pk>/baixar/', baixar_conta_pagar_view, name='baixar_conta_pagar'),

    # Despesas Recorrentes e Previsões
    path('recorrentes/', despesas_recorrentes_list, name='despesas_recorrentes_list'),
    path('recorrentes/nova/', despesa_recorrente_form, name='despesa_recorrente_nova'),
    path('recorrentes/editar/<int:pk>/', despesa_recorrente_form, name='despesa_recorrente_editar'),
    path('recorrentes/gerar/', gerar_previsoes_view, name='gerar_previsoes'),

    # Categorias de Despesas
    path('categorias/', categorias_despesa_list, name='categorias_despesa_list'),
    path('categorias/nova/', categoria_despesa_form, name='categoria_despesa_nova'),
    path('categorias/editar/<int:pk>/', categoria_despesa_form, name='categoria_despesa_editar'),

    # Fluxo Mensal e Fluxo de Caixa Geral
    path('mensal/', fluxo_mensal_view, name='fluxo_mensal'),
    path('fluxo-caixa/', fluxo_caixa_list, name='fluxo_caixa_list'),
]
