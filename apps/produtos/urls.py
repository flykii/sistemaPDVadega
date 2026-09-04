from django.urls import path
from .views import (
    produtos_list, produto_form, produto_excluir, estoque_ajuste,
    estoque_baixo_list, movimentacoes_list, categorias_list, categoria_form
)

urlpatterns = [
    path('', produtos_list, name='produtos_list'),
    path('novo/', produto_form, name='produto_novo'),
    path('editar/<int:pk>/', produto_form, name='produto_editar'),
    path('excluir/<int:pk>/', produto_excluir, name='produto_excluir'),
    path('ajuste/<int:pk>/', estoque_ajuste, name='estoque_ajuste'),
    path('estoque-baixo/', estoque_baixo_list, name='estoque_baixo_list'),
    path('movimentacoes/', movimentacoes_list, name='movimentacoes_list'),
    path('categorias/', categorias_list, name='categorias_list'),
    path('categorias/nova/', categoria_form, name='categoria_nova'),
    path('categorias/editar/<int:pk>/', categoria_form, name='categoria_editar'),
]
