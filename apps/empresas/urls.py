from django.urls import path
from .views import configuracoes_view

urlpatterns = [
    path('', configuracoes_view, name='configuracoes'),
]

