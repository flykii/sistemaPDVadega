"""
Decoradores de permissão por cargo para views.
"""
from functools import wraps
from django.http import HttpResponseForbidden, JsonResponse


def cargo_required(*cargos_permitidos):
    """
    Decorador que restringe acesso à view apenas para os cargos listados.
    Superusers sempre têm acesso.
    Uso: @cargo_required('ADMIN', 'GERENTE')
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                from django.shortcuts import redirect
                return redirect('login')
            if user.is_superuser or user.cargo in cargos_permitidos:
                return view_func(request, *args, **kwargs)

            if request.headers.get('Content-Type') == 'application/json' or request.META.get('HTTP_ACCEPT') == 'application/json':
                return JsonResponse({'error': 'Sem permissão para esta operação.'}, status=403)

            return HttpResponseForbidden(
                '<h3>Acesso negado</h3>'
                '<p>Você não tem permissão para acessar esta funcionalidade.</p>'
                f'<p>Cargos permitidos: {", ".join(cargos_permitidos)}</p>'
                '<p><a href="/">Voltar ao Dashboard</a></p>'
            )
        return _wrapped
    return decorator


def permissao_required(atributo_permissao: str):
    """
    Decorador que verifica uma propriedade de permissão no Usuario.
    Uso: @permissao_required('pode_cancelar_venda')
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                from django.shortcuts import redirect
                return redirect('login')
            if getattr(user, atributo_permissao, False):
                return view_func(request, *args, **kwargs)

            if request.headers.get('Content-Type') == 'application/json' or request.META.get('HTTP_ACCEPT') == 'application/json':
                return JsonResponse({'error': 'Sem permissão para esta operação.'}, status=403)

            return HttpResponseForbidden(
                '<h3>Acesso negado</h3>'
                '<p>Você não tem permissão para acessar esta funcionalidade.</p>'
                '<p><a href="/">Voltar ao Dashboard</a></p>'
            )
        return _wrapped
    return decorator
