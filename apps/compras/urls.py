from django.urls import path
from .views import (
    compras_list, nova_compra_view, compra_detalhe_view,
    receber_compra_view, cancelar_compra_view,
    fornecedores_list, fornecedor_form
)

urlpatterns = [
    path('', compras_list, name='compras_list'),
    path('nova/', nova_compra_view, name='compra_nova'),
    path('nova-compra/', nova_compra_view, name='nova_compra'),
    path('detalhe/<int:pk>/', compra_detalhe_view, name='compra_detalhe'),
    path('receber/<int:pk>/', receber_compra_view, name='compra_receber'),
    path('cancelar/<int:pk>/', cancelar_compra_view, name='compra_cancelar'),
    path('fornecedores/', fornecedores_list, name='fornecedores_list'),
    path('fornecedores/novo/', fornecedor_form, name='fornecedor_novo'),
    path('fornecedores/editar/<int:pk>/', fornecedor_form, name='fornecedor_editar'),
]
