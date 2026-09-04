from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from apps.caixas.models import SessaoCaixa
from apps.produtos.models import Produto
from apps.clientes.models import Cliente
from .models import Venda

@login_required
def pdv_front_view(request):
    empresa = request.tenant or request.user.empresa
    sessao_ativa = SessaoCaixa.objects.filter(empresa=empresa, operador=request.user, status='ABERTA').first() or SessaoCaixa.objects.filter(empresa=empresa, status='ABERTA').first()

    if not sessao_ativa:
        messages.warning(request, "Você precisa abrir uma Sessão de Caixa antes de acessar o PDV Rápido.")
        return redirect('caixas_list')

    produtos = Produto.objects.filter(empresa=empresa, ativo=True).order_by('nome')[:100]
    clientes = Cliente.objects.filter(empresa=empresa, ativo=True)

    import json
    from apps.empresas.models import ConfiguracaoAtalhoPDV
    atalhos_dict = ConfiguracaoAtalhoPDV.get_atalhos_empresa(empresa)

    return render(request, 'vendas/pdv.html', {
        'sessao': sessao_ativa,
        'produtos': produtos,
        'clientes': clientes,
        'atalhos_pdv': atalhos_dict,
        'atalhos_pdv_json': json.dumps(atalhos_dict),
    })

@login_required
def vendas_historico_view(request):
    empresa = request.tenant or request.user.empresa
    vendas = (
        Venda.objects.filter(empresa=empresa)
        .order_by('-data_venda')
        .select_related('cliente', 'operador')
        .prefetch_related('itens__produto', 'pagamentos')
    )
    return render(request, 'vendas/historico.html', {'vendas': vendas})

@login_required
def venda_detalhe_view(request, pk):
    empresa = request.tenant or request.user.empresa
    venda = get_object_or_404(
        Venda.objects.select_related('cliente', 'operador', 'sessao_caixa__caixa')
        .prefetch_related('itens__produto', 'pagamentos'),
        pk=pk,
        empresa=empresa
    )
    return render(request, 'vendas/recibo_termico.html', {'venda': venda, 'empresa': empresa})

@login_required
def recibo_print_view(request, venda_id):
    return venda_detalhe_view(request, pk=venda_id)


@login_required
def cancelar_venda_view(request, pk):
    """View para cancelar uma venda via POST com motivo obrigatório."""
    from django.http import JsonResponse
    from .services import SaleService

    if request.method != 'POST':
        return JsonResponse({'error': 'Método não permitido.'}, status=405)

    empresa = request.tenant or request.user.empresa
    motivo = request.POST.get('motivo', '').strip()

    if not motivo:
        return JsonResponse({'error': 'O motivo do cancelamento é obrigatório.'}, status=400)

    try:
        venda = SaleService.cancelar_venda(
            venda_id=pk,
            empresa=empresa,
            usuario=request.user,
            motivo=motivo
        )
        return JsonResponse({
            'success': True,
            'message': f'Venda #{venda.codigo_venda} cancelada com sucesso.',
            'venda_id': venda.id
        })
    except PermissionError as e:
        return JsonResponse({'error': str(e)}, status=403)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

