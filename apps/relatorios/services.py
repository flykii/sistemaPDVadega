import calendar
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from django.utils import timezone
from django.db.models import (
    Sum, Count, Avg, Min, Max, F, Q, ExpressionWrapper, DecimalField
)

from apps.vendas.models import Venda, ItemVenda, PagamentoVenda
from apps.produtos.models import Produto, Categoria, MovimentacaoEstoque
from apps.clientes.models import Cliente
from apps.caixas.models import Caixa, SessaoCaixa, MovimentacaoCaixa
from apps.financeiro.models import ContaPagar, ContaReceber, PagamentoContaReceber, CategoriaDespesa, FluxoCaixa
from apps.core.operational_day import (
    get_operational_date, get_operational_today, get_operational_datetime_range
)

class ReportService:
    # =========================================================================
    # PARSER DE PERÍODOS (COM VIRADA OPERACIONAL ÀS 02:00 DA MANHÃ)
    # =========================================================================
    @staticmethod
    def parse_periodo(periodo_str: str = 'mes_atual', data_inicio_str: str = '', data_fim_str: str = ''):
        hoje = get_operational_today()
        dt_inicio = hoje
        dt_fim = hoje

        periodo_str = (periodo_str or 'mes_atual').lower().strip()

        if periodo_str == 'hoje':
            dt_inicio = hoje
            dt_fim = hoje
        elif periodo_str == 'ontem':
            dt_inicio = hoje - timedelta(days=1)
            dt_fim = dt_inicio
        elif periodo_str == '7dias':
            dt_inicio = hoje - timedelta(days=6)
            dt_fim = hoje
        elif periodo_str == '30dias':
            dt_inicio = hoje - timedelta(days=29)
            dt_fim = hoje
        elif periodo_str == 'mes_atual':
            dt_inicio = date(hoje.year, hoje.month, 1)
            _, ultimo_dia = calendar.monthrange(hoje.year, hoje.month)
            dt_fim = date(hoje.year, hoje.month, ultimo_dia)
        elif periodo_str == 'mes_anterior':
            primeiro_mes_atual = date(hoje.year, hoje.month, 1)
            ultimo_mes_anterior = primeiro_mes_atual - timedelta(days=1)
            dt_inicio = date(ultimo_mes_anterior.year, ultimo_mes_anterior.month, 1)
            dt_fim = ultimo_mes_anterior
        elif periodo_str == 'ano_atual':
            dt_inicio = date(hoje.year, 1, 1)
            dt_fim = date(hoje.year, 12, 31)
        elif periodo_str == 'personalizado':
            if data_inicio_str:
                try:
                    dt_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
                except ValueError:
                    dt_inicio = hoje
            if data_fim_str:
                try:
                    dt_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
                except ValueError:
                    dt_fim = hoje

        start_dt, end_dt = get_operational_datetime_range(dt_inicio, dt_fim)

        return {
            'periodo': periodo_str,
            'data_inicio': dt_inicio,
            'data_fim': dt_fim,
            'start_datetime': start_dt,
            'end_datetime': end_dt,
            'data_inicio_str': dt_inicio.strftime('%Y-%m-%d'),
            'data_fim_str': dt_fim.strftime('%Y-%m-%d'),
        }

    @staticmethod
    def get_periodo_anterior(periodo_str: str, dt_inicio: date, dt_fim: date):
        if periodo_str == 'hoje':
            ant_inicio = dt_inicio - timedelta(days=1)
            ant_fim = ant_inicio
        elif periodo_str == 'ontem':
            ant_inicio = dt_inicio - timedelta(days=1)
            ant_fim = ant_inicio
        elif periodo_str == 'mes_atual':
            primeiro_mes_atual = date(dt_inicio.year, dt_inicio.month, 1)
            ultimo_mes_anterior = primeiro_mes_atual - timedelta(days=1)
            ant_inicio = date(ultimo_mes_anterior.year, ultimo_mes_anterior.month, 1)
            ant_fim = ultimo_mes_anterior
        elif periodo_str == 'ano_atual':
            ant_inicio = date(dt_inicio.year - 1, 1, 1)
            ant_fim = date(dt_inicio.year - 1, 12, 31)
        else:
            qtd_dias = (dt_fim - dt_inicio).days + 1
            ant_fim = dt_inicio - timedelta(days=1)
            ant_inicio = ant_fim - timedelta(days=qtd_dias - 1)

        start_dt, end_dt = get_operational_datetime_range(ant_inicio, ant_fim)

        return {
            'data_inicio': ant_inicio,
            'data_fim': ant_fim,
            'start_datetime': start_dt,
            'end_datetime': end_dt,
            'data_inicio_str': ant_inicio.strftime('%Y-%m-%d'),
            'data_fim_str': ant_fim.strftime('%Y-%m-%d'),
        }

    @staticmethod
    def _normalize_range(start, end):
        if isinstance(start, datetime):
            start_dt = start
            d_inicio = get_operational_date(start_dt)
        else:
            d_inicio = start
            start_dt = None

        if isinstance(end, datetime):
            end_dt = end
            d_fim = get_operational_date(end_dt)
        else:
            d_fim = end
            end_dt = None

        if start_dt is None or end_dt is None:
            calc_start, calc_end = get_operational_datetime_range(d_inicio, d_fim)
            start_dt = start_dt or calc_start
            end_dt = end_dt or calc_end

        return start_dt, end_dt, d_inicio, d_fim


    # =========================================================================
    # 1. RELATÓRIO GERAL DE VENDAS
    # =========================================================================
    @staticmethod
    def get_vendas_report(empresa, start_dt, end_dt, operador_id=None, caixa_id=None):
        start_datetime, end_datetime, d_inicio, d_fim = ReportService._normalize_range(start_dt, end_dt)

        vendas_qs = (
            Venda.objects.filter(
                empresa=empresa,
                status='CONCLUIDA',
                data_venda__gte=start_datetime,
                data_venda__lte=end_datetime
            )
            .select_related('cliente', 'operador', 'sessao_caixa__caixa')
            .prefetch_related('itens', 'pagamentos')
        )

        if operador_id:
            vendas_qs = vendas_qs.filter(operador_id=operador_id)
        if caixa_id:
            vendas_qs = vendas_qs.filter(sessao_caixa__caixa_id=caixa_id)

        agg = vendas_qs.aggregate(
            total_faturamento=Sum('total'),
            total_descontos=Sum('desconto'),
            total_subtotal=Sum('subtotal'),
            qtd_vendas=Count('id'),
            qtd_clientes=Count('cliente', distinct=True),
            venda_minima=Min('total'),
            venda_maxima=Max('total')
        )

        faturamento_liquido = agg['total_faturamento'] or Decimal('0.00')
        descontos_total = agg['total_descontos'] or Decimal('0.00')
        faturamento_bruto = agg['total_subtotal'] or Decimal('0.00')
        qtd_vendas = agg['qtd_vendas'] or 0
        qtd_clientes = agg['qtd_clientes'] or 0
        venda_minima = agg['venda_minima'] or Decimal('0.00')
        venda_maxima = agg['venda_maxima'] or Decimal('0.00')

        ticket_medio = (faturamento_liquido / Decimal(str(qtd_vendas))).quantize(Decimal('0.01')) if qtd_vendas > 0 else Decimal('0.00')

        itens_qs = ItemVenda.objects.filter(
            empresa=empresa,
            venda__in=vendas_qs
        )
        agg_itens = itens_qs.aggregate(
            total_itens=Sum('quantidade'),
            total_custo=Sum(F('quantidade') * F('preco_custo_unitario'))
        )
        total_itens_vendidos = agg_itens['total_itens'] or Decimal('0.00')
        total_custo = agg_itens['total_custo'] or Decimal('0.00')
        lucro_bruto = faturamento_liquido - total_custo
        
        margem_lucro_pct = float((lucro_bruto / faturamento_liquido) * 100) if faturamento_liquido > Decimal('0.00') else 0.0

        # Evolução Diária de Vendas no período (para gráficos)
        vendas_list = list(vendas_qs.order_by('data_venda'))
        dias_dict = {}
        curr = d_inicio
        while curr <= d_fim:
            dias_dict[curr] = {
                'data': curr.strftime('%d/%m/%Y'),
                'dia_curto': curr.strftime('%d/%m'),
                'total': Decimal('0.00'),
                'lucro': Decimal('0.00'),
                'qtd': 0
            }
            curr += timedelta(days=1)

        for v in vendas_list:
            v_dia = get_operational_date(v.data_venda)
            if v_dia in dias_dict:
                dias_dict[v_dia]['total'] += v.total
                dias_dict[v_dia]['lucro'] += v.lucro_total
                dias_dict[v_dia]['qtd'] += 1


        vendas_por_dia = list(dias_dict.values())

        return {
            'vendas': vendas_qs.order_by('-data_venda'),
            'faturamento_bruto': faturamento_bruto,
            'descontos_total': descontos_total,
            'faturamento_liquido': faturamento_liquido,
            'qtd_vendas': qtd_vendas,
            'ticket_medio': ticket_medio,
            'venda_minima': venda_minima,
            'venda_maxima': venda_maxima,
            'total_itens_vendidos': total_itens_vendidos,
            'qtd_clientes': qtd_clientes,
            'lucro_bruto': lucro_bruto,
            'margem_lucro_pct': margem_lucro_pct,
            'vendas_por_dia': vendas_por_dia,
        }

    # =========================================================================
    # 2. RELATÓRIO DE FORMAS DE PAGAMENTO
    # =========================================================================
    @staticmethod
    def get_formas_pagamento_report(empresa, start_dt, end_dt):
        start_datetime, end_datetime, _, _ = ReportService._normalize_range(start_dt, end_dt)

        pags_qs = (
            PagamentoVenda.objects.filter(
                empresa=empresa,
                venda__status='CONCLUIDA',
                venda__data_venda__gte=start_datetime,
                venda__data_venda__lte=end_datetime
            )
            .values('forma_pagamento')
            .annotate(
                total_recebido=Sum(
                    ExpressionWrapper(F('valor') - F('troco'), output_field=DecimalField(max_digits=12, decimal_places=2))
                ),
                total_bruto=Sum('valor'),
                total_troco=Sum('troco'),
                qtd_transacoes=Count('id')
            )
        )

        formas_map = dict(PagamentoVenda.FORMA_CHOICES)
        resultados = []
        total_geral = Decimal('0.00')

        for p in pags_qs:
            forma = p['forma_pagamento']
            valor_liq = p['total_recebido'] or Decimal('0.00')
            total_geral += valor_liq
            resultados.append({
                'forma_codigo': forma,
                'forma_nome': formas_map.get(forma, forma),
                'valor': valor_liq,
                'bruto': p['total_bruto'] or Decimal('0.00'),
                'troco': p['total_troco'] or Decimal('0.00'),
                'qtd': p['qtd_transacoes'],
                'percentual': 0.0
            })

        for r in resultados:
            if total_geral > Decimal('0.00'):
                r['percentual'] = float((r['valor'] / total_geral) * 100)

        resultados.sort(key=lambda x: x['valor'], reverse=True)

        return {
            'formas': resultados,
            'total_geral': total_geral,
            'chart_labels': [r['forma_nome'] for r in resultados],
            'chart_valores': [float(r['valor']) for r in resultados],
        }

    # =========================================================================
    # 3. RANKING DE PRODUTOS (MAIS VENDIDOS E LUCRO)
    # =========================================================================
    @staticmethod
    def get_produtos_ranking(empresa, start_dt, end_dt, limit=50, sort_by='qtd'):
        start_datetime, end_datetime, _, _ = ReportService._normalize_range(start_dt, end_dt)

        itens_qs = (
            ItemVenda.objects.filter(
                empresa=empresa,
                venda__status='CONCLUIDA',
                venda__data_venda__gte=start_datetime,
                venda__data_venda__lte=end_datetime
            )
            .values(
                'produto__id', 'produto__nome', 'produto__codigo_barras',
                'produto__categoria__nome', 'produto__estoque_atual'
            )
            .annotate(
                qtd_vendida=Sum('quantidade'),
                faturamento=Sum('subtotal'),
                custo_total=Sum(F('quantidade') * F('preco_custo_unitario'))
            )
        )

        produtos_calc = []
        total_faturamento_periodo = Decimal('0.00')

        for item in itens_qs:
            fat = item['faturamento'] or Decimal('0.00')
            qtd = item['qtd_vendida'] or Decimal('0.00')
            custo = item['custo_total'] or Decimal('0.00')
            lucro = fat - custo
            total_faturamento_periodo += fat

            preco_medio = (fat / qtd).quantize(Decimal('0.01')) if qtd > Decimal('0.00') else Decimal('0.00')
            custo_medio = (custo / qtd).quantize(Decimal('0.01')) if qtd > Decimal('0.00') else Decimal('0.00')
            margem = float((lucro / fat) * 100) if fat > Decimal('0.00') else 0.0

            produtos_calc.append({
                'id': item['produto__id'],
                'nome': item['produto__nome'],
                'codigo_barras': item['produto__codigo_barras'],
                'categoria': item['produto__categoria__nome'] or 'Sem Categoria',
                'estoque_atual': item['produto__estoque_atual'],
                'quantidade': qtd,
                'preco_medio': preco_medio,
                'custo_medio': custo_medio,
                'faturamento': fat,
                'custo_total': custo,
                'lucro_bruto': lucro,
                'margem_pct': margem,
                'participacao_pct': 0.0,
            })

        for p in produtos_calc:
            if total_faturamento_periodo > Decimal('0.00'):
                p['participacao_pct'] = float((p['faturamento'] / total_faturamento_periodo) * 100)

        if sort_by == 'faturamento':
            produtos_calc.sort(key=lambda x: x['faturamento'], reverse=True)
        elif sort_by == 'lucro':
            produtos_calc.sort(key=lambda x: x['lucro_bruto'], reverse=True)
        elif sort_by == 'margem':
            produtos_calc.sort(key=lambda x: x['margem_pct'], reverse=True)
        else:
            produtos_calc.sort(key=lambda x: x['quantidade'], reverse=True)

        for idx, p in enumerate(produtos_calc[:limit], 1):
            p['posicao'] = idx

        return {
            'produtos': produtos_calc[:limit],
            'total_faturamento': total_faturamento_periodo,
        }

    # =========================================================================
    # 4. VENDAS POR CATEGORIA
    # =========================================================================
    @staticmethod
    def get_vendas_por_categoria(empresa, start_dt, end_dt):
        start_datetime, end_datetime, _, _ = ReportService._normalize_range(start_dt, end_dt)

        itens_qs = (
            ItemVenda.objects.filter(
                empresa=empresa,
                venda__status='CONCLUIDA',
                venda__data_venda__gte=start_datetime,
                venda__data_venda__lte=end_datetime
            )
            .values('produto__categoria__nome')
            .annotate(
                qtd_itens=Sum('quantidade'),
                faturamento=Sum('subtotal'),
                custo_total=Sum(F('quantidade') * F('preco_custo_unitario'))
            )
            .order_by('-faturamento')
        )

        total_faturamento = sum((c['faturamento'] for c in itens_qs), Decimal('0.00'))
        categorias = []

        for item in itens_qs:
            fat = item['faturamento'] or Decimal('0.00')
            custo = item['custo_total'] or Decimal('0.00')
            part = float((fat / total_faturamento) * 100) if total_faturamento > Decimal('0.00') else 0.0
            categorias.append({
                'nome': item['produto__categoria__nome'] or 'Sem Categoria',
                'qtd_itens': item['qtd_itens'] or Decimal('0.00'),
                'faturamento': fat,
                'lucro': fat - custo,
                'participacao_pct': part,
            })

        return {
            'categorias': categorias,
            'total_faturamento': total_faturamento,
            'chart_labels': [c['nome'] for c in categorias],
            'chart_valores': [float(c['faturamento']) for c in categorias],
        }

    # =========================================================================
    # 5. VENDAS POR OPERADOR
    # =========================================================================
    @staticmethod
    def get_vendas_por_operador(empresa, start_dt, end_dt):
        start_datetime, end_datetime, _, _ = ReportService._normalize_range(start_dt, end_dt)

        vendas_qs = (
            Venda.objects.filter(
                empresa=empresa,
                status='CONCLUIDA',
                data_venda__gte=start_datetime,
                data_venda__lte=end_datetime
            )
            .values('operador__id', 'operador__first_name', 'operador__last_name', 'operador__username')
            .annotate(
                qtd_vendas=Count('id'),
                faturamento=Sum('total'),
                descontos=Sum('desconto'),
            )
            .order_by('-faturamento')
        )

        operadores = []
        for item in vendas_qs:
            nome = f"{item['operador__first_name']} {item['operador__last_name']}".strip() or item['operador__username']
            fat = item['faturamento'] or Decimal('0.00')
            qtd = item['qtd_vendas'] or 0
            t_medio = (fat / Decimal(str(qtd))).quantize(Decimal('0.01')) if qtd > 0 else Decimal('0.00')

            operadores.append({
                'id': item['operador__id'],
                'nome': nome,
                'qtd_vendas': qtd,
                'faturamento': fat,
                'descontos': item['descontos'] or Decimal('0.00'),
                'ticket_medio': t_medio,
            })

        return operadores

    # =========================================================================
    # 6. VENDAS POR CAIXA
    # =========================================================================
    @staticmethod
    def get_vendas_por_caixa(empresa, start_dt, end_dt):
        start_datetime, end_datetime, _, _ = ReportService._normalize_range(start_dt, end_dt)

        caixas = Caixa.objects.filter(empresa=empresa, ativo=True)
        resultados = []

        for cx in caixas:
            vendas_cx = Venda.objects.filter(
                empresa=empresa,
                sessao_caixa__caixa=cx,
                status='CONCLUIDA',
                data_venda__gte=start_datetime,
                data_venda__lte=end_datetime
            )
            qtd = vendas_cx.count()
            fat = vendas_cx.aggregate(Sum('total'))['total__sum'] or Decimal('0.00')

            pags_cx = PagamentoVenda.objects.filter(venda__in=vendas_cx)
            dinheiro = sum(((p.valor - p.troco) for p in pags_cx.filter(forma_pagamento='DINHEIRO')), Decimal('0.00'))
            pix = sum((p.valor for p in pags_cx.filter(forma_pagamento='PIX')), Decimal('0.00'))
            debito = sum((p.valor for p in pags_cx.filter(forma_pagamento='CARTAO_DEBITO')), Decimal('0.00'))
            credito = sum((p.valor for p in pags_cx.filter(forma_pagamento='CARTAO_CREDITO')), Decimal('0.00'))
            crediario = sum((p.valor for p in pags_cx.filter(forma_pagamento='CREDIARIO')), Decimal('0.00'))

            resultados.append({
                'caixa': cx,
                'qtd_vendas': qtd,
                'faturamento': fat,
                'dinheiro': dinheiro,
                'pix': pix,
                'debito': debito,
                'credito': credito,
                'crediario': crediario,
            })

        return resultados

    # =========================================================================
    # 7. RELATÓRIO DE ESTOQUE
    # =========================================================================
    @staticmethod
    def get_estoque_report(empresa, status_filtro='todos', categoria_id=None):
        prods_all = (
            Produto.objects.filter(empresa=empresa)
            .select_related('categoria', 'fornecedor_principal')
            .order_by('nome')
        )

        total_cadastrados = prods_all.count()
        prods_ativos = [p for p in prods_all if p.ativo]
        total_inativos = total_cadastrados - len(prods_ativos)

        if categoria_id:
            prods_ativos = [p for p in prods_ativos if str(p.categoria_id) == str(categoria_id)]

        produtos_zerados = [p for p in prods_ativos if p.estoque_atual <= Decimal('0.000')]
        produtos_baixo = [p for p in prods_ativos if p.estoque_atual > Decimal('0.000') and p.estoque_atual <= p.estoque_minimo]
        produtos_normais = [p for p in prods_ativos if p.estoque_atual > p.estoque_minimo]

        valor_total_custo = sum((p.estoque_atual * p.preco_custo for p in prods_ativos), Decimal('0.00'))
        valor_total_venda = sum((p.estoque_atual * p.preco_venda for p in prods_ativos), Decimal('0.00'))

        # Produtos com maior capital parado em estoque
        maior_capital = sorted(prods_ativos, key=lambda p: (p.estoque_atual * p.preco_custo), reverse=True)[:5]

        if status_filtro == 'zerado':
            filtrados = produtos_zerados
        elif status_filtro == 'baixo':
            filtrados = produtos_baixo
        elif status_filtro == 'normal':
            filtrados = produtos_normais
        else:
            filtrados = prods_ativos

        return {
            'produtos': filtrados,
            'total_cadastrados': total_cadastrados,
            'total_produtos_ativos': len(prods_ativos),
            'total_inativos': total_inativos,
            'qtd_zerados': len(produtos_zerados),
            'qtd_baixo': len(produtos_baixo),
            'qtd_normais': len(produtos_normais),
            'valor_total_custo': valor_total_custo,
            'valor_total_venda': valor_total_venda,
            'maior_capital': maior_capital,
            'produtos_criticos': sorted(produtos_zerados + produtos_baixo, key=lambda p: p.estoque_atual),
        }

    # =========================================================================
    # 8. RELATÓRIO DE MOVIMENTAÇÕES DE ESTOQUE
    # =========================================================================
    @staticmethod
    def get_movimentacoes_estoque_report(empresa, start_dt, end_dt, produto_id=None, tipo=None):
        start_datetime, end_datetime, _, _ = ReportService._normalize_range(start_dt, end_dt)

        movs_qs = (
            MovimentacaoEstoque.objects.filter(
                empresa=empresa,
                data_hora__gte=start_datetime,
                data_hora__lte=end_datetime
            )
            .select_related('produto', 'usuario')
            .order_by('-data_hora')
        )

        if produto_id:
            movs_qs = movs_qs.filter(produto_id=produto_id)
        if tipo:
            movs_qs = movs_qs.filter(tipo=tipo)

        return movs_qs

    # =========================================================================
    # 9. RELATÓRIO DE CREDIÁRIO
    # =========================================================================
    @staticmethod
    def get_crediario_report(empresa):
        contas_todas = ContaReceber.objects.filter(empresa=empresa)
        clientes_qs = Cliente.objects.filter(empresa=empresa, ativo=True)

        total_vendido_fiado = sum((c.valor_original for c in contas_todas), Decimal('0.00'))
        total_recebido = sum((c.valor_pago for c in contas_todas), Decimal('0.00'))
        total_aberto = sum((c.saldo for c in contas_todas if c.status not in ['QUITADA', 'PAGO', 'CANCELADA']), Decimal('0.00'))
        
        contas_vencidas = [c for c in contas_todas if c.is_vencida]
        total_vencido = sum((c.saldo for c in contas_vencidas), Decimal('0.00'))
        qtd_titulos_vencidos = len(contas_vencidas)

        clientes_devedores = []
        for cli in clientes_qs:
            if cli.saldo_devedor > Decimal('0.00'):
                contas_cli = [c for c in contas_todas if c.cliente_id == cli.id]
                vencido_cli = sum((c.saldo for c in contas_cli if c.is_vencida), Decimal('0.00'))
                clientes_devedores.append({
                    'cliente': cli,
                    'saldo_devedor': cli.saldo_devedor,
                    'limite_credito': cli.limite_credito,
                    'credito_disponivel': cli.credito_disponivel,
                    'saldo_vencido': vencido_cli,
                })

        clientes_devedores.sort(key=lambda x: x['saldo_devedor'], reverse=True)

        return {
            'total_vendido_fiado': total_vendido_fiado,
            'total_recebido': total_recebido,
            'total_aberto': total_aberto,
            'total_vencido': total_vencido,
            'qtd_titulos_vencidos': qtd_titulos_vencidos,
            'qtd_devedores': len(clientes_devedores),
            'clientes_devedores': clientes_devedores,
            'top_devedores': clientes_devedores[:5],
        }

    # =========================================================================
    # 10. RELATÓRIO DE DESPESAS
    # =========================================================================
    @staticmethod
    def get_despesas_report(empresa, start_dt, end_dt):
        _, _, d_inicio, d_fim = ReportService._normalize_range(start_dt, end_dt)

        despesas_qs = (
            ContaPagar.objects.filter(
                empresa=empresa,
                data_vencimento__gte=d_inicio,
                data_vencimento__lte=d_fim
            )
            .exclude(status='CANCELADA')
            .select_related('categoria', 'fornecedor')
            .order_by('data_vencimento')
        )

        total_despesas = sum((d.valor for d in despesas_qs), Decimal('0.00'))
        total_pagas = sum((d.valor_pago for d in despesas_qs), Decimal('0.00'))
        total_abertas = sum((d.saldo for d in despesas_qs), Decimal('0.00'))
        total_vencidas = sum((d.saldo for d in despesas_qs if d.is_vencida), Decimal('0.00'))

        cats_dict = {}
        for d in despesas_qs:
            cat_nome = d.categoria.nome if d.categoria else "Sem Categoria"
            if cat_nome not in cats_dict:
                cats_dict[cat_nome] = {'nome': cat_nome, 'valor': Decimal('0.00'), 'qtd': 0}
            cats_dict[cat_nome]['valor'] += d.valor
            cats_dict[cat_nome]['qtd'] += 1

        despesas_por_categoria = list(cats_dict.values())
        despesas_por_categoria.sort(key=lambda x: x['valor'], reverse=True)

        return {
            'despesas': despesas_qs,
            'total_despesas': total_despesas,
            'total_pagas': total_pagas,
            'total_abertas': total_abertas,
            'total_vencidas': total_vencidas,
            'despesas_por_categoria': despesas_por_categoria,
        }

    # =========================================================================
    # 11. DADOS EXECUTIVOS CONSOLIDADOS DO DASHBOARD GERENCIAL
    # =========================================================================
    @staticmethod
    def get_dashboard_gerencial(empresa, p_info):
        # 1. Período Atual vs Período Anterior
        p_ant = ReportService.get_periodo_anterior(
            p_info['periodo'], p_info['data_inicio'], p_info['data_fim']
        )

        vendas_atual = ReportService.get_vendas_report(empresa, p_info['start_datetime'], p_info['end_datetime'])
        vendas_ant = ReportService.get_vendas_report(empresa, p_ant['start_datetime'], p_ant['end_datetime'])

        # Variações percentuais
        fat_atual = vendas_atual['faturamento_liquido']
        fat_ant = vendas_ant['faturamento_liquido']
        if fat_ant > Decimal('0.00'):
            var_fat_pct = float(((fat_atual - fat_ant) / fat_ant) * 100)
        else:
            var_fat_pct = 100.0 if fat_atual > Decimal('0.00') else 0.0

        qtd_vendas_atual = vendas_atual['qtd_vendas']
        qtd_vendas_ant = vendas_ant['qtd_vendas']
        if qtd_vendas_ant > 0:
            var_qtd_pct = float(((qtd_vendas_atual - qtd_vendas_ant) / qtd_vendas_ant) * 100)
        else:
            var_qtd_pct = 100.0 if qtd_vendas_atual > 0 else 0.0

        # 2. Formas de Pagamento
        formas_data = ReportService.get_formas_pagamento_report(empresa, p_info['start_datetime'], p_info['end_datetime'])

        # 3. Top Produtos
        top_produtos_qtd = ReportService.get_produtos_ranking(empresa, p_info['start_datetime'], p_info['end_datetime'], limit=5, sort_by='qtd')
        top_produtos_fat = ReportService.get_produtos_ranking(empresa, p_info['start_datetime'], p_info['end_datetime'], limit=5, sort_by='faturamento')
        top_produtos_lucro = ReportService.get_produtos_ranking(empresa, p_info['start_datetime'], p_info['end_datetime'], limit=5, sort_by='lucro')
        top_produtos_margem = ReportService.get_produtos_ranking(empresa, p_info['start_datetime'], p_info['end_datetime'], limit=5, sort_by='margem')

        # 4. Estoque
        estoque_data = ReportService.get_estoque_report(empresa)

        # 5. Despesas
        despesas_data = ReportService.get_despesas_report(empresa, p_info['start_datetime'], p_info['end_datetime'])

        # 6. Caixas
        caixas_abertos = (
            SessaoCaixa.objects.filter(empresa=empresa, status='ABERTA')
            .select_related('caixa', 'operador')
            .order_by('-data_abertura')
        )

        ultimas_sessoes_fechadas = (
            SessaoCaixa.objects.filter(empresa=empresa, status='FECHADA')
            .select_related('caixa', 'operador')
            .order_by('-data_fechamento')[:5]
        )

        sessoes_fechadas_info = []
        for s in ultimas_sessoes_fechadas:
            saldo_esp = s.saldo_esperado
            saldo_cont = s.saldo_final_informado or Decimal('0.00')
            dif = s.diferenca if s.diferenca is not None else (saldo_cont - saldo_esp)

            if abs(dif) < Decimal('0.01'):
                status_dif = 'SEM DIFERENÇA'
                badge_class = 'bg-success'
            elif dif > Decimal('0.00'):
                status_dif = f'SOBRA (+R$ {dif:.2f})'
                badge_class = 'bg-primary'
            else:
                status_dif = f'FALTA (-R$ {abs(dif):.2f})'
                badge_class = 'bg-danger'

            sessoes_fechadas_info.append({
                'sessao': s,
                'saldo_esperado': saldo_esp,
                'saldo_fechamento': saldo_cont,
                'diferenca': dif,
                'status_diferenca': status_dif,
                'badge_class': badge_class,
            })

        # 7. Crediário
        crediario_data = ReportService.get_crediario_report(empresa)

        return {
            'p_info': p_info,
            'p_ant': p_ant,
            'vendas_atual': vendas_atual,
            'vendas_ant': vendas_ant,
            'var_fat_pct': var_fat_pct,
            'var_qtd_pct': var_qtd_pct,
            'formas_data': formas_data,
            'top_produtos_qtd': top_produtos_qtd['produtos'],
            'top_produtos_fat': top_produtos_fat['produtos'],
            'top_produtos_lucro': top_produtos_lucro['produtos'],
            'top_produtos_margem': top_produtos_margem['produtos'],
            'estoque_data': estoque_data,
            'despesas_data': despesas_data,
            'caixas_abertos': caixas_abertos,
            'ultimas_sessoes_fechadas': sessoes_fechadas_info,
            'crediario_data': crediario_data,
        }

    # =========================================================================
    # 12. RELATÓRIO DE REPOSIÇÃO SEMANAL DE ESTOQUE
    # =========================================================================
    @staticmethod
    def get_semanas_ultimos_18_meses(ref_date=None):
        """
        Gera a lista de semanas (Segunda a Domingo) dos últimos 18 meses,
        da mais recente (semana atual) para a mais antiga.
        Cada item contém informações amigáveis para exibição e filtragem.
        """
        if ref_date is None:
            ref_date = get_operational_today()
        elif isinstance(ref_date, datetime):
            ref_date = get_operational_date(ref_date)

        # Segunda-feira da semana corrente
        segunda_atual = ref_date - timedelta(days=ref_date.weekday())

        # 18 meses equivalem a aproximadamente 79 semanas (18 * 30.5 / 7 = 78.4 semanas)
        total_semanas = 79
        semanas = []

        for i in range(total_semanas):
            segunda = segunda_atual - timedelta(weeks=i)
            domingo = segunda + timedelta(days=6)
            ano_iso, semana_iso, _ = segunda.isocalendar()
            codigo = f"{ano_iso}-W{semana_iso:02d}"

            label = f"Semana {semana_iso:02d}/{ano_iso} — {segunda.strftime('%d/%m/%Y')} a {domingo.strftime('%d/%m/%Y')}"

            semanas.append({
                'codigo': codigo,
                'ano': ano_iso,
                'numero': semana_iso,
                'data_inicio': segunda,
                'data_fim': domingo,
                'data_inicio_str': segunda.strftime('%d/%m/%Y'),
                'data_fim_str': domingo.strftime('%d/%m/%Y'),
                'data_inicio_iso': segunda.strftime('%Y-%m-%d'),
                'data_fim_iso': domingo.strftime('%Y-%m-%d'),
                'label': label,
            })

        return semanas

    @staticmethod
    def get_reposicao_report(empresa, start_dt, end_dt):
        """
        Calcula os dados do Relatório de Reposição para o período especificado.
        Agrupa itens de vendas válidas (status='CONCLUIDA') por produto,
        ordenados primariamente por quantidade vendida descendente, e
        secundariamente por nome do produto em ordem alfabética.
        """
        start_datetime, end_datetime, d_inicio, d_fim = ReportService._normalize_range(start_dt, end_dt)

        itens_qs = (
            ItemVenda.objects.filter(
                empresa=empresa,
                venda__status='CONCLUIDA',
                venda__data_venda__gte=start_datetime,
                venda__data_venda__lte=end_datetime
            )
            .values(
                'produto__id',
                'produto__nome',
                'produto__codigo_barras',
                'produto__sku',
                'produto__categoria__nome',
                'produto__preco_custo',
                'produto__preco_venda',
                'produto__estoque_atual',
                'produto__estoque_minimo',
            )
            .annotate(
                qtd_vendida=Sum('quantidade'),
                faturamento=Sum('subtotal'),
                custo_total=Sum(
                    ExpressionWrapper(
                        F('quantidade') * F('preco_custo_unitario'),
                        output_field=DecimalField(max_digits=12, decimal_places=2)
                    )
                )
            )
            .order_by('-qtd_vendida', 'produto__nome')
        )

        produtos = []
        total_itens_vendidos = Decimal('0.00')
        total_faturamento = Decimal('0.00')
        total_lucro_obtido = Decimal('0.00')

        for idx, item in enumerate(itens_qs, start=1):
            fat = item['faturamento'] or Decimal('0.00')
            qtd = item['qtd_vendida'] or Decimal('0.00')
            custo = item['custo_total'] or Decimal('0.00')
            lucro = fat - custo

            total_itens_vendidos += qtd
            total_faturamento += fat
            total_lucro_obtido += lucro

            preco_medio = (fat / qtd).quantize(Decimal('0.01')) if qtd > Decimal('0.00') else Decimal('0.00')
            custo_medio = (custo / qtd).quantize(Decimal('0.01')) if qtd > Decimal('0.00') else Decimal('0.00')

            codigo = item['produto__sku'] or item['produto__codigo_barras'] or '-'

            estoque_atual = item['produto__estoque_atual'] if item['produto__estoque_atual'] is not None else Decimal('0.000')
            estoque_minimo = item['produto__estoque_minimo'] if item['produto__estoque_minimo'] is not None else Decimal('0.000')

            if estoque_atual <= Decimal('0.000'):
                status_reposicao = 'ESGOTADO'
                badge_reposicao = 'bg-danger'
            elif estoque_atual <= estoque_minimo:
                status_reposicao = 'REPOSIÇÃO NECESSÁRIA'
                badge_reposicao = 'bg-warning text-dark'
            else:
                status_reposicao = 'REGULAR'
                badge_reposicao = 'bg-success'

            produtos.append({
                'posicao': idx,
                'id': item['produto__id'],
                'nome': item['produto__nome'],
                'codigo': codigo,
                'codigo_barras': item['produto__codigo_barras'],
                'sku': item['produto__sku'],
                'categoria': item['produto__categoria__nome'] or 'Sem Categoria',
                'preco_custo_unitario': custo_medio if custo_medio > Decimal('0.00') else (item['produto__preco_custo'] or Decimal('0.00')),
                'preco_venda_unitario': preco_medio if preco_medio > Decimal('0.00') else (item['produto__preco_venda'] or Decimal('0.00')),
                'quantidade': qtd,
                'total_vendido': fat,
                'lucro_obtido': lucro,
                'estoque_atual': estoque_atual,
                'estoque_minimo': estoque_minimo,
                'status_reposicao': status_reposicao,
                'badge_reposicao': badge_reposicao,
            })

        produto_mais_vendido = None
        if produtos:
            top_qtd = produtos[0]
            produto_mais_vendido = {
                'nome': top_qtd['nome'],
                'quantidade': top_qtd['quantidade'],
            }

        produto_maior_faturamento = None
        if produtos:
            top_fat = max(produtos, key=lambda x: x['total_vendido'])
            produto_maior_faturamento = {
                'nome': top_fat['nome'],
                'faturamento': top_fat['total_vendido'],
            }

        return {
            'produtos': produtos,
            'total_itens_vendidos': total_itens_vendidos,
            'total_faturamento': total_faturamento,
            'total_lucro_obtido': total_lucro_obtido,
            'produto_mais_vendido': produto_mais_vendido,
            'produto_maior_faturamento': produto_maior_faturamento,
            'tem_vendas': len(produtos) > 0,
        }
