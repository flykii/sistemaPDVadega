from django.urls import path
from .views import pdv_front_view, vendas_historico_view, recibo_print_view, venda_detalhe_view, cancelar_venda_view

urlpatterns = [
    path('pdv/', pdv_front_view, name='pdv_front'),
    path('historico/', vendas_historico_view, name='vendas_historico'),
    path('recibo/<int:venda_id>/', recibo_print_view, name='recibo_print'),
    path('<int:pk>/', venda_detalhe_view, name='venda_detalhe'),
    path('<int:pk>/cancelar/', cancelar_venda_view, name='venda_cancelar'),
]

