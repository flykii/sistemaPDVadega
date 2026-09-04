import csv
import json
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Sum, Count, F, ExpressionWrapper, DecimalField

from apps.vendas.models import Venda, ItemVenda, PagamentoVenda
from apps.produtos.models import Produto, Categoria, MovimentacaoEstoque
from apps.financeiro.models import FluxoCaixa, ContaPagar, ContaReceber
from apps.caixas.models import Caixa, SessaoCaixa
from apps.usuarios.models import Usuario
from .services import ReportService

@login_required
def dashboard_view(request):
    empresa = request.tenant or request.user.empresa
    p_info = ReportService.parse_periodo(
        request.GET.get('periodo', 'mes_atual'),
        request.GET.get('data_inicio', ''),
        request.GET.get('data_fim', '')
    )

    data = ReportService.get_dashboard_gerencial(empresa, p_info)

    vendas_dia = data['vendas_atual']['vendas_por_dia']
    dias_labels = [d['dia_curto'] for d in vendas_dia]
    vendas_valores = [float(d['total']) for d in vendas_dia]
    lucro_valores = [float(d['lucro']) for d in vendas_dia]

    context = {
        **data,
        'chart_dias_labels': json.dumps(dias_labels),
        'chart_vendas_valores': json.dumps(vendas_valores),
        'chart_lucro_valores': json.dumps(lucro_valores),
        'chart_pag_labels': json.dumps(data['formas_data']['chart_labels']),
        'chart_pag_valores': json.dumps(data['formas_data']['chart_valores']),
    }

    return render(request, 'dashboard.html', context)


# =========================================================================
# RELATÓRIOS GERENCIAIS - HUB / VISÃO GERAL
# =========================================================================
@login_required
def relatorios_hub_view(request):
    empresa = request.tenant or request.user.empresa
    p_info = ReportService.parse_periodo(
        request.GET.get('periodo', 'mes_atual'),
        request.GET.get('data_inicio', ''),
        request.GET.get('data_fim', '')
    )

    vendas_data = ReportService.get_vendas_report(empresa, p_info['start_datetime'], p_info['end_datetime'])
    formas_data = ReportService.get_formas_pagamento_report(empresa, p_info['start_datetime'], p_info['end_datetime'])
    top_produtos = ReportService.get_produtos_ranking(empresa, p_info['start_datetime'], p_info['end_datetime'], limit=5)
    estoque_data = ReportService.get_estoque_report(empresa)

    dias_labels = [d['dia_curto'] for d in vendas_data['vendas_por_dia']]
    dias_valores = [float(d['total']) for d in vendas_data['vendas_por_dia']]

    return render(request, 'relatorios/relatorios_hub.html', {
        'p_info': p_info,
        'vendas_data': vendas_data,
        'formas_data': formas_data,
        'top_produtos': top_produtos['produtos'],
        'estoque_data': estoque_data,
        'chart_dias_labels': json.dumps(dias_labels),
        'chart_dias_valores': json.dumps(dias_valores),
        'chart_pag_labels': json.dumps(formas_data['chart_labels']),
        'chart_pag_valores': json.dumps(formas_data['chart_valores']),
    })


# =========================================================================
# RELATÓRIO DE VENDAS
# =========================================================================
@login_required
def relatorio_vendas_view(request):
    empresa = request.tenant or request.user.empresa
    p_info = ReportService.parse_periodo(
        request.GET.get('periodo', 'mes_atual'),
        request.GET.get('data_inicio', ''),
        request.GET.get('data_fim', '')
    )
    operador_id = request.GET.get('operador', '')
    caixa_id = request.GET.get('caixa', '')

    vendas_data = ReportService.get_vendas_report(
        empresa, p_info['start_datetime'], p_info['end_datetime'],
        operador_id=operador_id, caixa_id=caixa_id
    )

    operadores = Usuario.objects.filter(empresa=empresa, is_active=True).order_by('first_name', 'username')
    caixas = Caixa.objects.filter(empresa=empresa, ativo=True).order_by('nome')

    dias_labels = [d['dia_curto'] for d in vendas_data['vendas_por_dia']]
    dias_valores = [float(d['total']) for d in vendas_data['vendas_por_dia']]

    return render(request, 'relatorios/relatorio_vendas.html', {
        'p_info': p_info,
        'vendas_data': vendas_data,
        'operadores': operadores,
        'caixas': caixas,
        'operador_id': operador_id,
        'caixa_id': caixa_id,
        'chart_dias_labels': json.dumps(dias_labels),
        'chart_dias_valores': json.dumps(dias_valores),
    })


# =========================================================================
# RELATÓRIO DE FORMAS DE PAGAMENTO
# =========================================================================
@login_required
def relatorio_formas_pagamento_view(request):
    empresa = request.tenant or request.user.empresa
    p_info = ReportService.parse_periodo(
        request.GET.get('periodo', 'mes_atual'),
        request.GET.get('data_inicio', ''),
        request.GET.get('data_fim', '')
    )
    formas_data = ReportService.get_formas_pagamento_report(empresa, p_info['start_datetime'], p_info['end_datetime'])

    return render(request, 'relatorios/relatorio_formas_pagamento.html', {
        'p_info': p_info,
        'formas_data': formas_data,
        'chart_pag_labels': json.dumps(formas_data['chart_labels']),
        'chart_pag_valores': json.dumps(formas_data['chart_valores']),
    })


# =========================================================================
# RELATÓRIO DE PRODUTOS & LUCRO
# =========================================================================
@login_required
def relatorio_produtos_view(request):
    empresa = request.tenant or request.user.empresa
    p_info = ReportService.parse_periodo(
        request.GET.get('periodo', 'mes_atual'),
        request.GET.get('data_inicio', ''),
        request.GET.get('data_fim', '')
    )
    sort_by = request.GET.get('sort_by', 'qtd')
    limit = int(request.GET.get('limit', 50))

    produtos_data = ReportService.get_produtos_ranking(
        empresa, p_info['start_datetime'], p_info['end_datetime'],
        limit=limit, sort_by=sort_by
    )

    return render(request, 'relatorios/relatorio_produtos.html', {
        'p_info': p_info,
        'produtos': produtos_data['produtos'],
        'total_faturamento': produtos_data['total_faturamento'],
        'sort_by': sort_by,
        'limit': limit,
    })


# =========================================================================
# RELATÓRIO DE CATEGORIAS
# =========================================================================
@login_required
def relatorio_categorias_view(request):
    empresa = request.tenant or request.user.empresa
    p_info = ReportService.parse_periodo(
        request.GET.get('periodo', 'mes_atual'),
        request.GET.get('data_inicio', ''),
        request.GET.get('data_fim', '')
    )
    categorias_data = ReportService.get_vendas_por_categoria(empresa, p_info['start_datetime'], p_info['end_datetime'])

    return render(request, 'relatorios/relatorio_categorias.html', {
        'p_info': p_info,
        'categorias_data': categorias_data,
        'chart_labels': json.dumps(categorias_data['chart_labels']),
        'chart_valores': json.dumps(categorias_data['chart_valores']),
    })


# =========================================================================
# RELATÓRIO DE OPERADORES
# =========================================================================
@login_required
def relatorio_operadores_view(request):
    empresa = request.tenant or request.user.empresa
    p_info = ReportService.parse_periodo(
        request.GET.get('periodo', 'mes_atual'),
        request.GET.get('data_inicio', ''),
        request.GET.get('data_fim', '')
    )
    operadores = ReportService.get_vendas_por_operador(empresa, p_info['start_datetime'], p_info['end_datetime'])

    return render(request, 'relatorios/relatorio_operadores.html', {
        'p_info': p_info,
        'operadores': operadores,
    })


# =========================================================================
# RELATÓRIO DE CAIXAS
# =========================================================================
@login_required
def relatorio_caixas_view(request):
    empresa = request.tenant or request.user.empresa
    p_info = ReportService.parse_periodo(
        request.GET.get('periodo', 'mes_atual'),
        request.GET.get('data_inicio', ''),
        request.GET.get('data_fim', '')
    )
    caixas = ReportService.get_vendas_por_caixa(empresa, p_info['start_datetime'], p_info['end_datetime'])

    return render(request, 'relatorios/relatorio_caixas.html', {
        'p_info': p_info,
        'caixas': caixas,
    })


# =========================================================================
# RELATÓRIO DE ESTOQUE
# =========================================================================
@login_required
def relatorio_estoque_view(request):
    empresa = request.tenant or request.user.empresa
    status_filtro = request.GET.get('status', 'todos')
    categoria_id = request.GET.get('categoria', '')

    estoque_data = ReportService.get_estoque_report(empresa, status_filtro=status_filtro, categoria_id=categoria_id)
    categorias = Categoria.objects.filter(empresa=empresa).order_by('nome')

    return render(request, 'relatorios/relatorio_estoque.html', {
        'estoque_data': estoque_data,
        'status_filtro': status_filtro,
        'categoria_id': categoria_id,
        'categorias': categorias,
    })


# =========================================================================
# RELATÓRIO DE MOVIMENTAÇÕES DE ESTOQUE
# =========================================================================
@login_required
def relatorio_movimentacoes_estoque_view(request):
    empresa = request.tenant or request.user.empresa
    p_info = ReportService.parse_periodo(
        request.GET.get('periodo', 'mes_atual'),
        request.GET.get('data_inicio', ''),
        request.GET.get('data_fim', '')
    )
    produto_id = request.GET.get('produto', '')
    tipo = request.GET.get('tipo', '')

    movimentacoes = ReportService.get_movimentacoes_estoque_report(
        empresa, p_info['start_datetime'], p_info['end_datetime'],
        produto_id=produto_id, tipo=tipo
    )
    produtos = Produto.objects.filter(empresa=empresa, ativo=True).order_by('nome')

    return render(request, 'relatorios/relatorio_movimentacoes.html', {
        'p_info': p_info,
        'movimentacoes': movimentacoes,
        'produtos': produtos,
        'produto_id': produto_id,
        'tipo': tipo,
    })


# =========================================================================
# RELATÓRIO DE DESPESAS
# =========================================================================
@login_required
def relatorio_despesas_view(request):
    empresa = request.tenant or request.user.empresa
    p_info = ReportService.parse_periodo(
        request.GET.get('periodo', 'mes_atual'),
        request.GET.get('data_inicio', ''),
        request.GET.get('data_fim', '')
    )
    despesas_data = ReportService.get_despesas_report(empresa, p_info['start_datetime'], p_info['end_datetime'])

    return render(request, 'relatorios/relatorio_despesas.html', {
        'p_info': p_info,
        'despesas_data': despesas_data,
    })


# =========================================================================
# RELATÓRIO DE CREDIÁRIO
# =========================================================================
@login_required
def relatorio_crediario_view(request):
    empresa = request.tenant or request.user.empresa
    crediario_data = ReportService.get_crediario_report(empresa)

    return render(request, 'relatorios/relatorio_crediario.html', {
        'crediario_data': crediario_data,
    })


# =========================================================================
# RELATÓRIO DE REPOSIÇÃO SEMANAL DE ESTOQUE
# =========================================================================
@login_required
def relatorio_reposicao_view(request):
    empresa = request.tenant or request.user.empresa
    semanas = ReportService.get_semanas_ultimos_18_meses()

    semana_codigo = request.GET.get('semana', '')
    semana_selecionada = None
    if semana_codigo:
        for s in semanas:
            if s['codigo'] == semana_codigo or s['data_inicio_iso'] == semana_codigo:
                semana_selecionada = s
                break

    if not semana_selecionada and semanas:
        semana_selecionada = semanas[0]

    from apps.core.operational_day import get_operational_datetime_range
    start_dt, end_dt = get_operational_datetime_range(
        semana_selecionada['data_inicio'], semana_selecionada['data_fim']
    )

    dados = ReportService.get_reposicao_report(empresa, start_dt, end_dt)

    return render(request, 'relatorios/relatorio_reposicao.html', {
        'semanas': semanas,
        'semana_selecionada': semana_selecionada,
        'dados': dados,
    })


# =========================================================================
# EXPORTAÇÃO UNIVERSAL CSV
# =========================================================================
@login_required
def exportar_relatorio_csv_view(request, relatorio_tipo):
    empresa = request.tenant or request.user.empresa
    p_info = ReportService.parse_periodo(
        request.GET.get('periodo', 'mes_atual'),
        request.GET.get('data_inicio', ''),
        request.GET.get('data_fim', '')
    )

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="relatorio_{relatorio_tipo}_{p_info["data_inicio_str"]}_{p_info["data_fim_str"]}.csv"'

    writer = csv.writer(response, delimiter=';')

    if relatorio_tipo == 'vendas':
        writer.writerow(['Código', 'Data/Hora', 'Cliente', 'Operador', 'Subtotal (R$)', 'Desconto (R$)', 'Total Líquido (R$)', 'Status'])
        vendas = Venda.objects.filter(
            empresa=empresa, status='CONCLUIDA',
            data_venda__gte=p_info['start_datetime'], data_venda__lte=p_info['end_datetime']
        ).select_related('cliente', 'operador')
        for v in vendas:
            writer.writerow([
                v.codigo_venda,
                v.data_venda.strftime('%d/%m/%Y %H:%M'),
                v.cliente.nome if v.cliente else 'Cliente Não Identificado',
                v.operador.username if v.operador else '-',
                f"{v.subtotal:.2f}".replace('.', ','),
                f"{v.desconto:.2f}".replace('.', ','),
                f"{v.total:.2f}".replace('.', ','),
                v.get_status_display()
            ])

    elif relatorio_tipo == 'produtos':
        writer.writerow(['Posição', 'Código Barras', 'Produto', 'Categoria', 'Qtd Vendida', 'Preço Médio (R$)', 'Custo Médio (R$)', 'Faturamento (R$)', 'Lucro Bruto (R$)', 'Margem %'])
        res = ReportService.get_produtos_ranking(empresa, p_info['start_datetime'], p_info['end_datetime'], limit=500)
        for p in res['produtos']:
            writer.writerow([
                p['posicao'],
                p['codigo_barras'] or '-',
                p['nome'],
                p['categoria'],
                f"{p['quantidade']:.3f}".replace('.', ','),
                f"{p['preco_medio']:.2f}".replace('.', ','),
                f"{p['custo_medio']:.2f}".replace('.', ','),
                f"{p['faturamento']:.2f}".replace('.', ','),
                f"{p['lucro_bruto']:.2f}".replace('.', ','),
                f"{p['margem_pct']:.2f}%".replace('.', ',')
            ])

    elif relatorio_tipo == 'estoque':
        writer.writerow(['Código Barras', 'Produto', 'Categoria', 'Estoque Atual', 'Estoque Mínimo', 'Custo Unitário (R$)', 'Preço Venda (R$)', 'Valor em Estoque (R$)'])
        res = ReportService.get_estoque_report(empresa)
        for p in res['produtos']:
            writer.writerow([
                p.codigo_barras or '-',
                p.nome,
                p.categoria.nome if p.categoria else 'Sem Categoria',
                f"{p.estoque_atual:.3f}".replace('.', ','),
                f"{p.estoque_minimo:.3f}".replace('.', ','),
                f"{p.preco_custo:.2f}".replace('.', ','),
                f"{p.preco_venda:.2f}".replace('.', ','),
                f"{p.estoque_atual * p.preco_custo:.2f}".replace('.', ',')
            ])

    elif relatorio_tipo == 'despesas':
        writer.writerow(['ID', 'Descrição', 'Categoria', 'Fornecedor', 'Vencimento', 'Valor (R$)', 'Valor Pago (R$)', 'Saldo (R$)', 'Status'])
        res = ReportService.get_despesas_report(empresa, p_info['start_datetime'], p_info['end_datetime'])
        for d in res['despesas']:
            writer.writerow([
                d.id,
                d.descricao,
                d.categoria.nome if d.categoria else 'Geral',
                d.fornecedor.nome_fantasia if d.fornecedor else '-',
                d.data_vencimento.strftime('%d/%m/%Y'),
                f"{d.valor:.2f}".replace('.', ','),
                f"{d.valor_pago:.2f}".replace('.', ','),
                f"{d.saldo:.2f}".replace('.', ','),
                d.status_display_calculado
            ])

    elif relatorio_tipo == 'crediario':
        writer.writerow(['Cliente', 'CPF/CNPJ', 'Telefone', 'Limite de Crédito (R$)', 'Saldo Devedor (R$)', 'Crédito Disponível (R$)', 'Valor Vencido (R$)'])
        res = ReportService.get_crediario_report(empresa)
        for c in res['clientes_devedores']:
            cli = c['cliente']
            writer.writerow([
                cli.nome,
                cli.cpf_cnpj or '-',
                cli.telefone or cli.celular or '-',
                f"{c['limite_credito']:.2f}".replace('.', ','),
                f"{c['saldo_devedor']:.2f}".replace('.', ','),
                f"{c['credito_disponivel']:.2f}".replace('.', ','),
                f"{c['saldo_vencido']:.2f}".replace('.', ',')
            ])

    elif relatorio_tipo == 'reposicao':
        semanas = ReportService.get_semanas_ultimos_18_meses()
        semana_codigo = request.GET.get('semana', '')
        semana_selecionada = None
        if semana_codigo:
            for s in semanas:
                if s['codigo'] == semana_codigo or s['data_inicio_iso'] == semana_codigo:
                    semana_selecionada = s
                    break
        if not semana_selecionada and semanas:
            semana_selecionada = semanas[0]

        from apps.core.operational_day import get_operational_datetime_range
        start_dt, end_dt = get_operational_datetime_range(
            semana_selecionada['data_inicio'], semana_selecionada['data_fim']
        )

        response['Content-Disposition'] = f'attachment; filename="relatorio_reposicao_{semana_selecionada["codigo"]}_{semana_selecionada["data_inicio_iso"]}_{semana_selecionada["data_fim_iso"]}.csv"'

        writer.writerow([
            'Posição', 'Produto', 'Código', 'Categoria', 'Custo Unitário (R$)',
            'Preço Venda Unitário (R$)', 'Qtde. Vendida', 'Total Vendido (R$)',
            'Lucro Obtido (R$)', 'Estoque Atual', 'Estoque Mínimo', 'Status Reposição'
        ])
        res = ReportService.get_reposicao_report(empresa, start_dt, end_dt)
        for p in res['produtos']:
            writer.writerow([
                p['posicao'],
                p['nome'],
                p['codigo'],
                p['categoria'],
                f"{p['preco_custo_unitario']:.2f}".replace('.', ','),
                f"{p['preco_venda_unitario']:.2f}".replace('.', ','),
                f"{p['quantidade']:.3f}".replace('.', ','),
                f"{p['total_vendido']:.2f}".replace('.', ','),
                f"{p['lucro_obtido']:.2f}".replace('.', ','),
                f"{p['estoque_atual']:.3f}".replace('.', ','),
                f"{p['estoque_minimo']:.3f}".replace('.', ','),
                p['status_reposicao']
            ])

    return response


@login_required
def auditoria_view(request):
    """Visualização da trilha de auditoria."""
    from apps.core.models import AuditLog
    from apps.usuarios.permissions import cargo_required

    empresa = request.tenant or request.user.empresa

    # Verificação de permissão
    if not request.user.pode_visualizar_auditoria:
        return HttpResponseForbidden(
            '<h3>Acesso negado</h3>'
            '<p>Apenas Administradores e Gerentes podem visualizar a auditoria.</p>'
            '<p><a href="/">Voltar ao Dashboard</a></p>'
        )

    logs = AuditLog.objects.filter(empresa=empresa).select_related('usuario').order_by('-data_hora')

    # Filtros
    acao = request.GET.get('acao', '')
    if acao:
        logs = logs.filter(acao=acao)

    usuario_id = request.GET.get('usuario', '')
    if usuario_id:
        logs = logs.filter(usuario_id=usuario_id)

    entidade = request.GET.get('entidade', '')
    if entidade:
        logs = logs.filter(entidade__icontains=entidade)

    data_inicio = request.GET.get('data_inicio', '')
    data_fim = request.GET.get('data_fim', '')
    if data_inicio:
        from datetime import datetime
        dt = datetime.strptime(data_inicio, '%Y-%m-%d')
        logs = logs.filter(data_hora__date__gte=dt.date())
    if data_fim:
        from datetime import datetime
        dt = datetime.strptime(data_fim, '%Y-%m-%d')
        logs = logs.filter(data_hora__date__lte=dt.date())

    # Paginação simples - últimos 200
    logs = logs[:200]

    acoes = AuditLog.ACAO_CHOICES
    from apps.usuarios.models import Usuario as UsuarioModel
    usuarios_list = UsuarioModel.objects.filter(empresa=empresa).order_by('username')

    return render(request, 'relatorios/auditoria.html', {
        'logs': logs,
        'acoes': acoes,
        'usuarios_list': usuarios_list,
        'filtros': {
            'acao': acao,
            'usuario': usuario_id,
            'entidade': entidade,
            'data_inicio': data_inicio,
            'data_fim': data_fim,
        }
    })

