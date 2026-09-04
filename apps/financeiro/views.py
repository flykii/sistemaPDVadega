import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q, Sum

from .models import (
    ContaReceber, ContaPagar, FluxoCaixa, PagamentoContaReceber,
    CategoriaDespesa, DespesaRecorrente, PagamentoContaPagar
)
from apps.clientes.models import Cliente, Fornecedor
from apps.caixas.models import SessaoCaixa, MovimentacaoCaixa
from apps.vendas.models import Venda
from apps.usuarios.permissions import permissao_required
from .services import FinancialService

def safe_decimal(value, default='0.00'):
    if not value or str(value).strip() == '':
        return Decimal(default)
    try:
        cleaned = str(value).strip().replace(',', '.')
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return Decimal(default)


# =========================================================================
# CONTAS A RECEBER / CREDIÁRIO
# =========================================================================
@login_required
def contas_receber_list(request):
    empresa = request.tenant or request.user.empresa
    filtro_status = request.GET.get('status', 'abertas')
    cliente_id = request.GET.get('cliente', '')
    query = request.GET.get('q', '').strip()
    data_inicio = request.GET.get('data_inicio', '')
    data_fim = request.GET.get('data_fim', '')

    hoje = timezone.now().date()
    contas_qs = (
        ContaReceber.objects.filter(empresa=empresa)
        .select_related('cliente', 'venda')
        .prefetch_related('pagamentos_recebidos')
        .order_by('data_vencimento', '-id')
    )

    if cliente_id:
        contas_qs = contas_qs.filter(cliente_id=cliente_id)

    if query:
        contas_qs = contas_qs.filter(
            Q(cliente__nome__icontains=query) |
            Q(descricao__icontains=query) |
            Q(venda__codigo_venda__icontains=query)
        )

    if data_inicio:
        contas_qs = contas_qs.filter(data_vencimento__gte=data_inicio)
    if data_fim:
        contas_qs = contas_qs.filter(data_vencimento__lte=data_fim)

    if filtro_status == 'abertas':
        contas = [c for c in contas_qs if c.status in ['ABERTA', 'PARCIAL', 'PENDENTE'] and c.saldo > 0]
    elif filtro_status == 'vencidas':
        contas = [c for c in contas_qs if c.is_vencida]
    elif filtro_status == 'pagas':
        contas = [c for c in contas_qs if c.status in ['QUITADA', 'PAGO'] or c.saldo <= 0]
    elif filtro_status == 'hoje':
        contas = [c for c in contas_qs if c.data_vencimento == hoje and c.saldo > 0]
    elif filtro_status == '7dias':
        limite_7d = hoje + timedelta(days=7)
        contas = [c for c in contas_qs if hoje <= c.data_vencimento <= limite_7d and c.saldo > 0]
    else:
        contas = list(contas_qs)

    todas_contas = ContaReceber.objects.filter(empresa=empresa)
    total_a_receber = sum((c.saldo for c in todas_contas if c.status not in ['CANCELADA', 'QUITADA', 'PAGO']), Decimal('0.00'))
    total_vencido = sum((c.saldo for c in todas_contas if c.is_vencida), Decimal('0.00'))
    
    pagamentos_mes = PagamentoContaReceber.objects.filter(
        empresa=empresa,
        data_hora__year=hoje.year,
        data_hora__month=hoje.month
    )
    total_recebido_mes = sum((p.valor_efetivo for p in pagamentos_mes), Decimal('0.00'))
    qtd_contas_abertas = sum(1 for c in todas_contas if c.status in ['ABERTA', 'PARCIAL', 'PENDENTE'] and c.saldo > 0)
    
    clientes = Cliente.objects.filter(empresa=empresa, ativo=True).order_by('nome')
    sessao_aberta = SessaoCaixa.objects.filter(empresa=empresa, operador=request.user, status='ABERTA').first()

    return render(request, 'financeiro/contas_receber.html', {
        'contas': contas,
        'clientes': clientes,
        'filtro_status': filtro_status,
        'cliente_id': cliente_id,
        'query': query,
        'data_inicio': data_inicio,
        'data_fim': data_fim,
        'total_a_receber': total_a_receber,
        'total_vencido': total_vencido,
        'total_recebido_mes': total_recebido_mes,
        'qtd_contas_abertas': qtd_contas_abertas,
        'sessao_aberta': sessao_aberta,
    })


@login_required
def receber_conta_view(request, pk):
    empresa = request.tenant or request.user.empresa
    conta = get_object_or_404(ContaReceber, pk=pk, empresa=empresa)
    sessao_caixa = SessaoCaixa.objects.filter(empresa=empresa, operador=request.user, status='ABERTA').first()

    if request.method == 'POST':
        valor_pago = safe_decimal(request.POST.get('valor_pago'), '0.00')
        forma_pagamento = request.POST.get('forma_pagamento', 'DINHEIRO')
        troco = safe_decimal(request.POST.get('troco'), '0.00')
        observacao = request.POST.get('observacao', '').strip()

        try:
            pag = FinancialService.receber_pagamento_conta(
                conta=conta,
                valor_pago=valor_pago,
                forma_pagamento=forma_pagamento,
                troco=troco,
                sessao_caixa=sessao_caixa,
                usuario=request.user,
                observacao=observacao
            )
            messages.success(
                request,
                f"Recebimento de R$ {pag.valor_efetivo:.2f} registrado com sucesso para a conta #{conta.id}! "
                f"Saldo restante: R$ {conta.saldo:.2f}."
            )
            return redirect('contas_receber_list')
        except Exception as e:
            messages.error(request, str(e))

    return render(request, 'financeiro/receber_modal.html', {
        'conta': conta,
        'sessao_caixa': sessao_caixa,
    })


@login_required
def baixar_conta_receber_view(request, pk):
    empresa = request.tenant or request.user.empresa
    conta = get_object_or_404(ContaReceber, pk=pk, empresa=empresa)
    sessao_caixa = SessaoCaixa.objects.filter(empresa=empresa, operador=request.user, status='ABERTA').first()
    try:
        FinancialService.baixar_conta_receber(conta, usuario=request.user, sessao_caixa=sessao_caixa)
        messages.success(request, f"Conta a receber #{conta.id} de R$ {conta.valor} quitada com sucesso!")
    except Exception as e:
        messages.error(request, str(e))
    return redirect('contas_receber_list')


@login_required
@permissao_required('pode_operar_financeiro')
def cancelar_conta_receber_view(request, pk):
    empresa = request.tenant or request.user.empresa
    conta = get_object_or_404(ContaReceber, pk=pk, empresa=empresa)

    if request.method == 'POST':
        motivo = request.POST.get('motivo', '').strip()
        try:
            FinancialService.cancelar_conta_receber(conta, usuario=request.user, motivo=motivo)
            messages.success(request, f"Conta a receber #{conta.id} ('{conta.descricao}') cancelada com sucesso.")
        except Exception as e:
            messages.error(request, str(e))

    return redirect('contas_receber_list')


# =========================================================================
# DESPESAS AVULSAS E CONTAS A PAGAR
# =========================================================================
@login_required
@permissao_required('pode_operar_financeiro')
def contas_pagar_list(request):
    empresa = request.tenant or request.user.empresa
    filtro_status = request.GET.get('status', 'abertas')
    categoria_id = request.GET.get('categoria', '')
    fornecedor_id = request.GET.get('fornecedor', '')
    query = request.GET.get('q', '').strip()
    periodo = request.GET.get('periodo', 'mes_atual')
    data_inicio = request.GET.get('data_inicio', '')
    data_fim = request.GET.get('data_fim', '')

    hoje = timezone.now().date()
    
    # Tratamento de períodos rápidos
    if periodo == 'hoje':
        data_inicio = hoje.strftime('%Y-%m-%d')
        data_fim = hoje.strftime('%Y-%m-%d')
    elif periodo == 'ontem':
        ontem = hoje - timedelta(days=1)
        data_inicio = ontem.strftime('%Y-%m-%d')
        data_fim = ontem.strftime('%Y-%m-%d')
    elif periodo == '7dias':
        data_inicio = (hoje - timedelta(days=7)).strftime('%Y-%m-%d')
        data_fim = hoje.strftime('%Y-%m-%d')
    elif periodo == 'mes_atual':
        data_inicio = date(hoje.year, hoje.month, 1).strftime('%Y-%m-%d')
        _, u_dia = calendar.monthrange(hoje.year, hoje.month)
        data_fim = date(hoje.year, hoje.month, u_dia).strftime('%Y-%m-%d')
    elif periodo == 'mes_anterior':
        primeiro_mes_atual = date(hoje.year, hoje.month, 1)
        ultimo_mes_ant = primeiro_mes_atual - timedelta(days=1)
        data_inicio = date(ultimo_mes_ant.year, ultimo_mes_ant.month, 1).strftime('%Y-%m-%d')
        data_fim = ultimo_mes_ant.strftime('%Y-%m-%d')

    contas_qs = (
        ContaPagar.objects.filter(empresa=empresa)
        .select_related('fornecedor', 'categoria', 'despesa_recorrente', 'usuario')
        .prefetch_related('pagamentos_detalhes')
        .order_by('data_vencimento', '-id')
    )

    if categoria_id:
        contas_qs = contas_qs.filter(categoria_id=categoria_id)

    if fornecedor_id:
        contas_qs = contas_qs.filter(fornecedor_id=fornecedor_id)

    if query:
        contas_qs = contas_qs.filter(
            Q(descricao__icontains=query) |
            Q(fornecedor__nome_fantasia__icontains=query) |
            Q(fornecedor__razao_social__icontains=query) |
            Q(categoria__nome__icontains=query)
        )

    if data_inicio:
        contas_qs = contas_qs.filter(data_vencimento__gte=data_inicio)
    if data_fim:
        contas_qs = contas_qs.filter(data_vencimento__lte=data_fim)

    if filtro_status == 'abertas':
        contas = [c for c in contas_qs if c.status in ['ABERTA', 'PARCIAL', 'PENDENTE'] and c.saldo > 0]
    elif filtro_status == 'vencidas':
        contas = [c for c in contas_qs if c.is_vencida]
    elif filtro_status == 'pagas':
        contas = [c for c in contas_qs if c.status in ['PAGA', 'PAGO'] or c.saldo <= 0]
    elif filtro_status == 'hoje':
        contas = [c for c in contas_qs if c.data_vencimento == hoje and c.saldo > 0]
    elif filtro_status == '7dias':
        limite_7d = hoje + timedelta(days=7)
        contas = [c for c in contas_qs if hoje <= c.data_vencimento <= limite_7d and c.saldo > 0]
    else:
        contas = list(contas_qs)

    # Indicadores do Cabeçalho
    todas_despesas = ContaPagar.objects.filter(empresa=empresa)
    total_despesas_mes = sum(
        (c.valor for c in todas_despesas if c.data_vencimento.year == hoje.year and c.data_vencimento.month == hoje.month and c.status != 'CANCELADA'),
        Decimal('0.00')
    )
    total_aberto = sum((c.saldo for c in todas_despesas if c.status in ['ABERTA', 'PARCIAL', 'PENDENTE'] and c.saldo > 0), Decimal('0.00'))
    total_vencido = sum((c.saldo for c in todas_despesas if c.is_vencida), Decimal('0.00'))
    
    pagamentos_mes_despesas = PagamentoContaPagar.objects.filter(
        empresa=empresa,
        data_hora__year=hoje.year,
        data_hora__month=hoje.month
    )
    total_pago_mes = sum((p.valor for p in pagamentos_mes_despesas), Decimal('0.00'))
    total_recorrentes = DespesaRecorrente.objects.filter(empresa=empresa, ativo=True).count()

    categorias = CategoriaDespesa.objects.filter(empresa=empresa, ativo=True).order_by('nome')
    fornecedores = Fornecedor.objects.filter(empresa=empresa, ativo=True).order_by('nome_fantasia', 'razao_social')
    sessao_aberta = SessaoCaixa.objects.filter(empresa=empresa, operador=request.user, status='ABERTA').first()

    return render(request, 'financeiro/contas_pagar.html', {
        'contas': contas,
        'categorias': categorias,
        'fornecedores': fornecedores,
        'filtro_status': filtro_status,
        'categoria_id': categoria_id,
        'fornecedor_id': fornecedor_id,
        'query': query,
        'periodo': periodo,
        'data_inicio': data_inicio,
        'data_fim': data_fim,
        'total_despesas_mes': total_despesas_mes,
        'total_aberto': total_aberto,
        'total_vencido': total_vencido,
        'total_pago_mes': total_pago_mes,
        'total_recorrentes': total_recorrentes,
        'sessao_aberta': sessao_aberta,
    })


@login_required
@permissao_required('pode_operar_financeiro')
def despesa_form(request, pk=None):
    empresa = request.tenant or request.user.empresa
    conta = get_object_or_404(ContaPagar, pk=pk, empresa=empresa) if pk else None
    categorias = CategoriaDespesa.objects.filter(empresa=empresa, ativo=True).order_by('nome')
    fornecedores = Fornecedor.objects.filter(empresa=empresa, ativo=True).order_by('nome_fantasia', 'razao_social')
    sessao_aberta = SessaoCaixa.objects.filter(empresa=empresa, operador=request.user, status='ABERTA').first()

    if request.method == 'POST':
        descricao = request.POST.get('descricao', '').strip()
        categoria_id = request.POST.get('categoria_id')
        fornecedor_id = request.POST.get('fornecedor_id')
        valor = safe_decimal(request.POST.get('valor'), '0.00')
        data_competencia = request.POST.get('data_competencia') or timezone.now().date().strftime('%Y-%m-%d')
        data_vencimento = request.POST.get('data_vencimento') or data_competencia
        observacoes = request.POST.get('observacoes', '').strip()
        pago_imediatamente = request.POST.get('pago_imediatamente') == 'on' or request.POST.get('pago_imediatamente') == 'true'
        forma_pagamento = request.POST.get('forma_pagamento', 'DINHEIRO')

        if not descricao or valor <= Decimal('0.00'):
            messages.error(request, "Informe uma descrição válida e um valor maior que zero.")
            return render(request, 'financeiro/despesa_form.html', {
                'conta': conta, 'categorias': categorias, 'fornecedores': fornecedores, 'sessao_aberta': sessao_aberta
            })

        categoria = CategoriaDespesa.objects.filter(id=categoria_id, empresa=empresa).first() if categoria_id else None
        fornecedor = Fornecedor.objects.filter(id=fornecedor_id, empresa=empresa).first() if fornecedor_id else None

        try:
            if not conta:
                conta = FinancialService.cadastrar_despesa_avulsa(
                    empresa=empresa,
                    descricao=descricao,
                    valor=valor,
                    categoria=categoria,
                    fornecedor=fornecedor,
                    data_competencia=data_competencia,
                    data_vencimento=data_vencimento,
                    forma_pagamento=forma_pagamento if pago_imediatamente else '',
                    pago_imediatamente=pago_imediatamente,
                    sessao_caixa=sessao_aberta if (pago_imediatamente and forma_pagamento == 'DINHEIRO') else None,
                    usuario=request.user,
                    observacoes=observacoes
                )
                messages.success(request, f"Despesa '{conta.descricao}' registrada com sucesso!")
            else:
                if conta.status in ['PAGA', 'PAGO']:
                    messages.error(request, "Esta despesa já está quitada e não pode ser editada.")
                    return redirect('contas_pagar_list')

                conta.descricao = descricao
                conta.categoria = categoria
                conta.fornecedor = fornecedor
                conta.valor = valor
                conta.valor_original = valor
                conta.data_competencia = data_competencia
                conta.data_vencimento = data_vencimento
                conta.observacoes = observacoes
                conta.save()
                messages.success(request, f"Despesa '{conta.descricao}' atualizada com sucesso!")

            return redirect('contas_pagar_list')
        except Exception as e:
            messages.error(request, f"Erro ao salvar despesa: {str(e)}")

    return render(request, 'financeiro/despesa_form.html', {
        'conta': conta,
        'categorias': categorias,
        'fornecedores': fornecedores,
        'sessao_aberta': sessao_aberta,
    })


@login_required
@permissao_required('pode_operar_financeiro')
def pagar_despesa_view(request, pk):
    empresa = request.tenant or request.user.empresa
    conta = get_object_or_404(ContaPagar, pk=pk, empresa=empresa)
    sessao_caixa = SessaoCaixa.objects.filter(empresa=empresa, operador=request.user, status='ABERTA').first()

    if request.method == 'POST':
        valor_pago = safe_decimal(request.POST.get('valor_pago'), '0.00')
        forma_pagamento = request.POST.get('forma_pagamento', 'DINHEIRO')
        observacao = request.POST.get('observacao', '').strip()

        try:
            FinancialService.pagar_conta_despesa(
                conta=conta,
                valor_pago=valor_pago,
                forma_pagamento=forma_pagamento,
                sessao_caixa=sessao_caixa if forma_pagamento == 'DINHEIRO' else None,
                usuario=request.user,
                observacao=observacao
            )
            messages.success(request, f"Pagamento de R$ {valor_pago:.2f} registrado com sucesso para a despesa #{conta.id}!")
            return redirect('contas_pagar_list')
        except Exception as e:
            messages.error(request, str(e))

    return render(request, 'financeiro/pagar_despesa_modal.html', {
        'conta': conta,
        'sessao_caixa': sessao_caixa,
    })


@login_required
@permissao_required('pode_operar_financeiro')
def cancelar_despesa_view(request, pk):
    empresa = request.tenant or request.user.empresa
    conta = get_object_or_404(ContaPagar, pk=pk, empresa=empresa)

    if request.method == 'POST':
        motivo = request.POST.get('motivo', '').strip()
        try:
            FinancialService.cancelar_conta_despesa(conta, usuario=request.user, motivo=motivo)
            messages.success(request, f"Despesa #{conta.id} ('{conta.descricao}') cancelada com sucesso.")
        except Exception as e:
            messages.error(request, str(e))

    return redirect('contas_pagar_list')


# =========================================================================
# DESPESAS RECORRENTES & PREVISÕES
# =========================================================================
@login_required
@permissao_required('pode_operar_financeiro')
def despesas_recorrentes_list(request):
    empresa = request.tenant or request.user.empresa
    recorrentes = DespesaRecorrente.objects.filter(empresa=empresa).select_related('categoria', 'fornecedor').order_by('dia_vencimento')
    total_mensal = sum((r.valor_estimado for r in recorrentes if r.ativo), Decimal('0.00'))

    return render(request, 'financeiro/recorrentes_list.html', {
        'recorrentes': recorrentes,
        'total_mensal': total_mensal,
    })


@login_required
@permissao_required('pode_operar_financeiro')
def despesa_recorrente_form(request, pk=None):
    empresa = request.tenant or request.user.empresa
    recorrente = get_object_or_404(DespesaRecorrente, pk=pk, empresa=empresa) if pk else None
    categorias = CategoriaDespesa.objects.filter(empresa=empresa, ativo=True).order_by('nome')
    fornecedores = Fornecedor.objects.filter(empresa=empresa, ativo=True).order_by('nome_fantasia', 'razao_social')

    if request.method == 'POST':
        descricao = request.POST.get('descricao', '').strip()
        categoria_id = request.POST.get('categoria_id')
        fornecedor_id = request.POST.get('fornecedor_id')
        valor_estimado = safe_decimal(request.POST.get('valor_estimado'), '0.00')
        periodicidade = request.POST.get('periodicidade', 'MENSAL')
        dia_vencimento = int(request.POST.get('dia_vencimento', 10))
        data_inicio = request.POST.get('data_inicio') or timezone.now().date().strftime('%Y-%m-%d')
        data_fim = request.POST.get('data_fim') or None
        observacoes = request.POST.get('observacoes', '').strip()
        ativo = request.POST.get('ativo') == 'on' or request.POST.get('ativo') == 'true' or ('ativo' not in request.POST and pk is None)

        categoria = CategoriaDespesa.objects.filter(id=categoria_id, empresa=empresa).first() if categoria_id else None
        fornecedor = Fornecedor.objects.filter(id=fornecedor_id, empresa=empresa).first() if fornecedor_id else None

        if not recorrente:
            recorrente = DespesaRecorrente(empresa=empresa)

        recorrente.descricao = descricao
        recorrente.categoria = categoria
        recorrente.fornecedor = fornecedor
        recorrente.valor_estimado = valor_estimado
        recorrente.periodicidade = periodicidade
        recorrente.dia_vencimento = max(1, min(31, dia_vencimento))
        recorrente.data_inicio = data_inicio
        recorrente.data_fim = data_fim
        recorrente.observacoes = observacoes
        recorrente.ativo = ativo

        try:
            recorrente.save()
            messages.success(request, f"Despesa recorrente '{recorrente.descricao}' salva com sucesso!")
            return redirect('despesas_recorrentes_list')
        except Exception as e:
            messages.error(request, f"Erro ao salvar despesa recorrente: {str(e)}")

    return render(request, 'financeiro/recorrente_form.html', {
        'recorrente': recorrente,
        'categorias': categorias,
        'fornecedores': fornecedores,
    })


@login_required
@permissao_required('pode_operar_financeiro')
def gerar_previsoes_view(request):
    empresa = request.tenant or request.user.empresa
    hoje = timezone.now().date()
    mes = int(request.POST.get('mes', hoje.month))
    ano = int(request.POST.get('ano', hoje.year))

    try:
        geradas = FinancialService.gerar_previsoes_despesas_recorrentes(
            empresa=empresa,
            mes=mes,
            ano=ano,
            usuario=request.user
        )
        if geradas:
            messages.success(request, f"{len(geradas)} despesas recorrentes previstas geradas com sucesso para {mes:02d}/{ano}!")
        else:
            messages.info(request, f"Todas as despesas recorrentes de {mes:02d}/{ano} já estavam geradas no sistema.")
    except Exception as e:
        messages.error(request, f"Erro ao gerar previsões: {str(e)}")

    return redirect('contas_pagar_list')


# =========================================================================
# CATEGORIAS DE DESPESAS
# =========================================================================
@login_required
@permissao_required('pode_operar_financeiro')
def categorias_despesa_list(request):
    empresa = request.tenant or request.user.empresa
    categorias = CategoriaDespesa.objects.filter(empresa=empresa).order_by('nome')
    return render(request, 'financeiro/categorias_despesa_list.html', {'categorias': categorias})


@login_required
@permissao_required('pode_operar_financeiro')
def categoria_despesa_form(request, pk=None):
    empresa = request.tenant or request.user.empresa
    categoria = get_object_or_404(CategoriaDespesa, pk=pk, empresa=empresa) if pk else None

    if request.method == 'POST':
        nome = request.POST.get('nome', '').strip()
        descricao = request.POST.get('descricao', '').strip()
        ativo = request.POST.get('ativo') == 'on' or request.POST.get('ativo') == 'true' or ('ativo' not in request.POST and pk is None)

        if not nome:
            messages.error(request, "O nome da categoria é obrigatório.")
            return render(request, 'financeiro/categoria_despesa_form.html', {'categoria': categoria})

        duplicada = CategoriaDespesa.objects.filter(empresa=empresa, nome__iexact=nome)
        if categoria:
            duplicada = duplicada.exclude(id=categoria.id)
        if duplicada.exists():
            messages.error(request, f"Já existe uma categoria cadastrada com o nome '{nome}'.")
            return render(request, 'financeiro/categoria_despesa_form.html', {'categoria': categoria})

        if not categoria:
            categoria = CategoriaDespesa(empresa=empresa)

        categoria.nome = nome
        categoria.descricao = descricao
        categoria.ativo = ativo

        try:
            categoria.save()
            messages.success(request, f"Categoria de despesa '{categoria.nome}' salva com sucesso!")
            return redirect('categorias_despesa_list')
        except Exception as e:
            messages.error(request, str(e))

    return render(request, 'financeiro/categoria_despesa_form.html', {'categoria': categoria})


# =========================================================================
# FLUXO MENSAL & FLUXO DE CAIXA GERAL
# =========================================================================
@login_required
@permissao_required('pode_operar_financeiro')
def fluxo_mensal_view(request):
    empresa = getattr(request, 'tenant', None) or getattr(request.user, 'empresa', None)
    hoje = timezone.now().date()
    mes = int(request.GET.get('mes', hoje.month))
    ano = int(request.GET.get('ano', hoje.year))

    if empresa:
        despesas_mes = (
            ContaPagar.objects.filter(
                empresa=empresa,
                data_vencimento__year=ano,
                data_vencimento__month=mes
            )
            .exclude(status='CANCELADA')
            .select_related('categoria', 'fornecedor')
            .order_by('data_vencimento')
        )
    else:
        despesas_mes = ContaPagar.objects.none()

    total_previsto = sum((c.valor for c in despesas_mes), Decimal('0.00'))
    total_pago = sum((c.valor_pago for c in despesas_mes), Decimal('0.00'))
    total_aberto = sum((c.saldo for c in despesas_mes), Decimal('0.00'))

    pct_pago = float((total_pago / total_previsto) * 100) if total_previsto > Decimal('0.00') else 0.0
    pct_aberto = float((total_aberto / total_previsto) * 100) if total_previsto > Decimal('0.00') else 0.0

    return render(request, 'financeiro/fluxo_mensal.html', {
        'mes': mes,
        'ano': ano,
        'despesas': despesas_mes,
        'total_previsto': total_previsto,
        'total_pago': total_pago,
        'total_aberto': total_aberto,
        'pct_pago': pct_pago,
        'pct_aberto': pct_aberto,
    })


@login_required
def fluxo_caixa_list(request):
    empresa = request.tenant or request.user.empresa

    sessao_aberta = (
        SessaoCaixa.objects.filter(empresa=empresa, status='ABERTA')
        .select_related('caixa', 'operador')
        .first()
    )

    hoje = timezone.now().date()
    movimentos_fluxo = (
        FluxoCaixa.objects.filter(empresa=empresa)
        .order_by('-data_movimento')[:100]
    )

    total_entradas_geral = sum(
        (m.valor for m in FluxoCaixa.objects.filter(empresa=empresa, tipo='ENTRADA')),
        Decimal('0.00')
    )
    total_saidas_geral = sum(
        (m.valor for m in FluxoCaixa.objects.filter(empresa=empresa, tipo='SAIDA')),
        Decimal('0.00')
    )
    saldo_geral_empresa = total_entradas_geral - total_saidas_geral

    saldo_gaveta = sessao_aberta.saldo_esperado if sessao_aberta else Decimal('0.00')

    return render(request, 'financeiro/fluxo_caixa.html', {
        'sessao': sessao_aberta,
        'movimentos': movimentos_fluxo,
        'total_entradas_geral': total_entradas_geral,
        'total_saidas_geral': total_saidas_geral,
        'saldo_geral_empresa': saldo_geral_empresa,
        'saldo_gaveta': saldo_gaveta,
    })


@login_required
@permissao_required('pode_operar_financeiro')
def baixar_conta_pagar_view(request, pk):
    empresa = request.tenant or request.user.empresa
    conta = get_object_or_404(ContaPagar, pk=pk, empresa=empresa)
    sessao_caixa = SessaoCaixa.objects.filter(empresa=empresa, operador=request.user, status='ABERTA').first()
    try:
        FinancialService.baixar_conta_pagar(conta, usuario=request.user, sessao_caixa=sessao_caixa)
        messages.success(request, f"Despesa / Conta a pagar #{conta.id} de R$ {conta.valor} baixada com sucesso!")
    except Exception as e:
        messages.error(request, str(e))
    return redirect('contas_pagar_list')
