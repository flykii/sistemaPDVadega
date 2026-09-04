from django.utils.deprecation import MiddlewareMixin
from .models import set_current_tenant, clear_current_tenant

class TenantMiddleware(MiddlewareMixin):
    """
    Middleware responsável por identificar e injetar a Empresa (Tenant) ativa no contexto da requisição.
    """
    def process_request(self, request):
        tenant = None
        if hasattr(request, 'user') and request.user.is_authenticated:
            tenant = getattr(request.user, 'empresa', None)
        
        request.tenant = tenant
        set_current_tenant(tenant)

    def process_response(self, request, response):
        clear_current_tenant()
        return response

    def process_exception(self, request, exception):
        clear_current_tenant()
        return None
