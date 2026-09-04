import os
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from apps.relatorios.views import dashboard_view
from apps.usuarios.views import login_view, logout_view

def service_worker_view(request):
    sw_path = os.path.join(settings.BASE_DIR, 'static', 'sw.js')
    if os.path.exists(sw_path):
        with open(sw_path, 'rb') as f:
            resp = HttpResponse(f.read(), content_type='application/javascript')
            resp['Service-Worker-Allowed'] = '/'
            return resp
    return HttpResponse("// sw not found", content_type='application/javascript', status=404)

def manifest_view(request):
    manifest_path = os.path.join(settings.BASE_DIR, 'static', 'manifest.json')
    if os.path.exists(manifest_path):
        with open(manifest_path, 'rb') as f:
            return HttpResponse(f.read(), content_type='application/manifest+json')
    return HttpResponse("{}", content_type='application/manifest+json', status=404)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', dashboard_view, name='dashboard'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('sw.js', service_worker_view, name='service-worker'),
    path('manifest.json', manifest_view, name='pwa-manifest'),

    path('caixas/', include('apps.caixas.urls')),
    path('produtos/', include('apps.produtos.urls')),
    path('clientes/', include('apps.clientes.urls')),
    path('vendas/', include('apps.vendas.urls')),
    path('compras/', include('apps.compras.urls')),
    path('financeiro/', include('apps.financeiro.urls')),
    path('relatorios/', include('apps.relatorios.urls')),
    path('configuracoes/', include('apps.empresas.urls')),
    path('importacao/', include('apps.importacao.urls')),

    path('api/v1/', include('apps.api.urls')),
]



if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
