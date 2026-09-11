"""
Context processor para injetar a configuração visual da empresa ativa em todos os templates.
"""
from apps.empresas.models import ConfiguracaoVisual

def configuracao_visual_context(request):
    empresa = getattr(request, 'tenant', None)
    if not empresa and hasattr(request, 'user') and request.user.is_authenticated:
        empresa = getattr(request.user, 'empresa', None)

    if empresa:
        config = getattr(empresa, 'configuracao_visual', None)
        if not config:
            config = empresa.get_configuracao_visual()
        return {
            'config_visual': config,
            'css_variables': config.to_css_variables()
        }

    # Valores padrão de fallback
    return {
        'config_visual': None,
        'css_variables': """
        :root {
            --cor-principal: #2563eb;
            --cor-secundaria: #475569;
            --cor-destaque: #f59e0b;
            --cor-menu-sidebar: #0f172a;
            --cor-fundo: #f8fafc;
            --cor-cards: #ffffff;
            --cor-texto: #1e293b;
            --cor-texto-secundario: #64748b;
            --cor-botoes: #2563eb;
            --cor-botoes-acao: #10b981;
            --cor-links: #2563eb;
            --cor-sucesso: #16a34a;
            --cor-alerta: #d97706;
            --cor-erro: #dc2626;

            --cor-pdv-fundo: #0f172a;
            --cor-pdv-texto: #ffffff;
            --cor-pdv-preco: #22c55e;
            --cor-pdv-total: #eab308;
            --cor-pdv-botao-finalizar: #16a34a;
            --cor-pdv-botao-cancelar: #dc2626;
            --cor-pdv-botoes-pagamento: #3b82f6;
            --cor-pdv-botao-pausar: #d97706;
            --cor-pdv-botao-espera: #2563eb;
            --cor-pdv-botao-divida: #7c3aed;

            --pdv-fonte-preco: 1.25rem;
            --pdv-fonte-total: 2.0rem;
            --pdv-fonte-itens: 1.0rem;
        }
        """
    }

