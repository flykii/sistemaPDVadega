from django.urls import path
from .views import clientes_list, cliente_form, cliente_ficha

urlpatterns = [
    path('', clientes_list, name='clientes_list'),
    path('novo/', cliente_form, name='cliente_novo'),
    path('editar/<int:pk>/', cliente_form, name='cliente_editar'),
    path('ficha/<int:pk>/', cliente_ficha, name='cliente_ficha'),
]
