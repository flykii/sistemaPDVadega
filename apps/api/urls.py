from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ProdutoViewSet, ClienteViewSet, VendaViewSet,
    PDVSyncAPIView, PingAPIView, PDVCatalogOfflineAPIView,
    TEFSimulateAPIView, PixGenerateAPIView,
    ContasPendentesClienteAPIView, ReceberDividaAPIView
)

router = DefaultRouter()
router.register(r'produtos', ProdutoViewSet, basename='api-produto')
router.register(r'clientes', ClienteViewSet, basename='api-cliente')
router.register(r'vendas', VendaViewSet, basename='api-venda')

urlpatterns = [
    path('', include(router.urls)),
    path('ping/', PingAPIView.as_view(), name='api-ping'),
    path('pdv/ping/', PingAPIView.as_view(), name='api-pdv-ping'),
    path('pdv/sync/', PDVSyncAPIView.as_view(), name='api-pdv-sync'),
    path('pdv/produtos-offline/', PDVCatalogOfflineAPIView.as_view(), name='api-pdv-produtos-offline'),
    path('hardware/tef/', TEFSimulateAPIView.as_view(), name='api-tef-simulate'),
    path('hardware/pix/', PixGenerateAPIView.as_view(), name='api-pix-generate'),
    path('financeiro/contas-pendentes/<int:cliente_id>/', ContasPendentesClienteAPIView.as_view(), name='api-contas-pendentes'),
    path('financeiro/receber-divida/', ReceberDividaAPIView.as_view(), name='api-receber-divida'),
]

