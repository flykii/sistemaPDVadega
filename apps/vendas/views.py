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

    if sessao_ativa.is_sessao_dia_anterior:
        messages.error(
            request,
            f"Atenção: A Sessão #{sessao_ativa.id} do Caixa '{sessao_ativa.caixa.nome}' foi aberta no dia operacional anterior ({sessao_ativa.dia_operacional_abertura.strftime('%d/%m/%Y')}). É obrigatório realizar o fechamento desta sessão antes de iniciar novas operações no dia de hoje."
        )
        return redirect('fechar_caixa', sessao_id=sessao_ativa.id)

    from .services import SaleService
    grupos_produtos_rapidos = SaleService.obter_produtos_rapidos_agrupados(empresa)
    clientes = Cliente.objects.filter(empresa=empresa, ativo=True)

    import json
    from apps.empresas.models import ConfiguracaoAtalhoPDV
    atalhos_dict = ConfiguracaoAtalhoPDV.get_atalhos_empresa(empresa)

    return render(request, 'vendas/pdv.html', {
        'sessao': sessao_ativa,
        'grupos_produtos_rapidos': grupos_produtos_rapidos,
        'clientes': clientes,
        'atalhos_pdv': atalhos_dict,
        'atalhos_pdv_json': json.dumps(atalhos_dict),
    })

@login_required
def vendas_historico_view(request):
    from datetime import datetime, time
    from django.utils import timezone
    from django.core.paginator import Paginator
    from django.db.models import Q
    from apps.usuarios.models import Usuario

    empresa = request.tenant or request.user.empresa

    # Queryset base estritamente isolado pelo tenant
    vendas_qs = (
        Venda.objects.filter(empresa=empresa)
        .select_related('cliente', 'operador')
        .prefetch_related('itens__produto', 'pagamentos')
        .order_by('-data_venda')
    )

    # 1. Filtro de busca textual (Código da Venda ou Nome do Cliente)
    q = request.GET.get('q', '').strip()
    if q:
        q_clean = q.lstrip('#')
        vendas_qs = vendas_qs.filter(
            Q(codigo_venda__icontains=q_clean) |
            Q(cliente__nome__icontains=q)
        )

    # 2. Filtro por Operador
    operador_id = request.GET.get('operador', '').strip()
    if operador_id:
        vendas_qs = vendas_qs.filter(operador_id=operador_id, operador__empresa=empresa)

    # 3. Filtro por Forma de Pagamento
    forma_pagamento = request.GET.get('pagamento', '').strip().upper()
    if forma_pagamento:
        vendas_qs = vendas_qs.filter(pagamentos__forma_pagamento=forma_pagamento).distinct()

    # 4. Filtro por Status da Venda
    status_venda = request.GET.get('status', '').strip().upper()
    if status_venda:
        vendas_qs = vendas_qs.filter(status=status_venda)

    # 5. Filtro por Período / Datas
    periodo = request.GET.get('periodo', '').strip().lower()
    data_inicio_str = request.GET.get('data_inicio', '').strip()
    data_fim_str = request.GET.get('data_fim', '').strip()

    agora = timezone.now()
    hoje = agora.date()

    if periodo == 'hoje':
        inicio_dt = timezone.make_aware(datetime.combine(hoje, time.min))
        fim_dt = timezone.make_aware(datetime.combine(hoje, time.max))
        vendas_qs = vendas_qs.filter(data_venda__range=(inicio_dt, fim_dt))
    elif periodo == 'ontem':
        ontem = hoje - timezone.timedelta(days=1)
        inicio_dt = timezone.make_aware(datetime.combine(ontem, time.min))
        fim_dt = timezone.make_aware(datetime.combine(ontem, time.max))
        vendas_qs = vendas_qs.filter(data_venda__range=(inicio_dt, fim_dt))
    elif periodo == 'ultimos_7_dias':
        inicio = hoje - timezone.timedelta(days=7)
        inicio_dt = timezone.make_aware(datetime.combine(inicio, time.min))
        fim_dt = timezone.make_aware(datetime.combine(hoje, time.max))
        vendas_qs = vendas_qs.filter(data_venda__range=(inicio_dt, fim_dt))
    elif periodo == 'ultimos_30_dias':
        inicio = hoje - timezone.timedelta(days=30)
        inicio_dt = timezone.make_aware(datetime.combine(inicio, time.min))
        fim_dt = timezone.make_aware(datetime.combine(hoje, time.max))
        vendas_qs = vendas_qs.filter(data_venda__range=(inicio_dt, fim_dt))
    elif periodo == 'este_mes':
        inicio_mes = hoje.replace(day=1)
        inicio_dt = timezone.make_aware(datetime.combine(inicio_mes, time.min))
        fim_dt = timezone.make_aware(datetime.combine(hoje, time.max))
        vendas_qs = vendas_qs.filter(data_venda__range=(inicio_dt, fim_dt))
    elif periodo == 'mes_anterior':
        primeiro_dia_este_mes = hoje.replace(day=1)
        ultimo_dia_mes_ant = primeiro_dia_este_mes - timezone.timedelta(days=1)
        primeiro_dia_mes_ant = ultimo_dia_mes_ant.replace(day=1)
        inicio_dt = timezone.make_aware(datetime.combine(primeiro_dia_mes_ant, time.min))
        fim_dt = timezone.make_aware(datetime.combine(ultimo_dia_mes_ant, time.max))
        vendas_qs = vendas_qs.filter(data_venda__range=(inicio_dt, fim_dt))
    else:
        # Período personalizado com data_inicio e data_fim
        if data_inicio_str:
            try:
                dt_ini = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
                inicio_dt = timezone.make_aware(datetime.combine(dt_ini, time.min))
                vendas_qs = vendas_qs.filter(data_venda__gte=inicio_dt)
            except ValueError:
                pass
        if data_fim_str:
            try:
                dt_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
                fim_dt = timezone.make_aware(datetime.combine(dt_fim, time.max))
                vendas_qs = vendas_qs.filter(data_venda__lte=fim_dt)
            except ValueError:
                pass

    # Operadores da empresa para dropdown
    operadores = Usuario.objects.filter(empresa=empresa, is_active=True).order_by('first_name', 'username')

    # Paginação (25 por página)
    paginator = Paginator(vendas_qs, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Constrói querystring para paginação sem perder os filtros
    query_dict = request.GET.copy()
    if 'page' in query_dict:
        del query_dict['page']
    querystring_filtros = query_dict.urlencode()

    total_filtrado = vendas_qs.count()

    context = {
        'vendas': page_obj,
        'page_obj': page_obj,
        'operadores': operadores,
        'total_filtrado': total_filtrado,
        'querystring_filtros': querystring_filtros,
        'filtros_ativos': {
            'q': q,
            'operador': operador_id,
            'pagamento': forma_pagamento,
            'status': status_venda,
            'periodo': periodo,
            'data_inicio': data_inicio_str,
            'data_fim': data_fim_str,
        }
    }
    return render(request, 'vendas/historico.html', context)

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

