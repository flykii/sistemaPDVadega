from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.contrib import messages
from decimal import Decimal
from .models import Caixa, SessaoCaixa, MovimentacaoCaixa
from apps.usuarios.models import Usuario
from apps.usuarios.permissions import permissao_required
from .services import CashService

@login_required
def caixas_list(request):
    empresa = request.tenant or request.user.empresa
    caixas = Caixa.objects.filter(empresa=empresa).order_by('nome')
    sessoes_abertas = (
        SessaoCaixa.objects.filter(empresa=empresa, status='ABERTA')
        .select_related('caixa', 'operador')
        .order_by('-data_abertura')
    )
    sessoes_fechadas = (
        SessaoCaixa.objects.filter(empresa=empresa, status='FECHADA')
        .select_related('caixa', 'operador')
        .order_by('-data_fechamento')[:50]
    )

    return render(request, 'caixas/list.html', {
        'caixas': caixas,
        'sessoes_abertas': sessoes_abertas,
        'sessoes_fechadas': sessoes_fechadas,
    })

@login_required
@permissao_required('pode_operar_caixa')
def abrir_caixa_view(request, caixa_id):
    empresa = request.tenant or request.user.empresa
    caixa = get_object_or_404(Caixa, id=caixa_id, empresa=empresa)
    operadores = Usuario.objects.filter(empresa=empresa, is_active=True)

    if request.method == 'POST':
        saldo_inicial = request.POST.get('saldo_inicial', '0.00').replace(',', '.')
        operador_id = request.POST.get('operador_id')
        nome_operador = request.POST.get('nome_operador', '').strip()
        operador = Usuario.objects.filter(id=operador_id, empresa=empresa).first() or request.user

        try:
            sessao = CashService.abrir_caixa(caixa, operador, saldo_inicial, nome_operador=nome_operador)
            op_nome = sessao.nome_operador_exibicao
            messages.success(request, f"Caixa '{caixa.nome}' aberto com sucesso para {op_nome} com Saldo Inicial de R$ {sessao.saldo_inicial:.2f}!")
            return redirect('caixas_list')
        except Exception as e:
            messages.error(request, str(e))

    return render(request, 'caixas/abrir.html', {
        'caixa': caixa,
        'operadores': operadores
    })

@login_required
@permissao_required('pode_operar_caixa')
def fechar_caixa_view(request, sessao_id):
    empresa = request.tenant or request.user.empresa
    sessao = get_object_or_404(SessaoCaixa, id=sessao_id, empresa=empresa)

    if not request.user.is_gerente and sessao.operador and sessao.operador != request.user:
        return HttpResponseForbidden(
            '<h3>Acesso negado</h3>'
            '<p>Apenas o próprio operador da sessão ou um Gerente/Administrador pode fechar este caixa.</p>'
            '<p><a href="/caixas/">Voltar para Caixas</a></p>'
        )

    if sessao.status == 'FECHADA':
        messages.info(request, "Esta sessão de caixa já se encontra fechada.")
        return redirect('relatorio_caixa', sessao_id=sessao.id)

    if request.method == 'POST':
        saldo_informado = request.POST.get('saldo_final_informado', '0.00').replace(',', '.')
        observacoes = request.POST.get('observacoes', '').strip()
        try:
            CashService.fechar_caixa(sessao, saldo_informado, observacoes)
            diferenca_txt = f"Diferença: R$ {sessao.diferenca:.2f}"
            if sessao.diferenca == Decimal('0.00'):
                messages.success(request, f"Caixa fechado com sucesso! Caixa 100% conferido sem diferenças.")
            elif sessao.diferenca > Decimal('0.00'):
                messages.warning(request, f"Caixa fechado com SOBRA de R$ {sessao.diferenca:.2f}.")
            else:
                messages.error(request, f"Caixa fechado com FALTA de R$ {abs(sessao.diferenca):.2f}.")
            return redirect('relatorio_caixa', sessao_id=sessao.id)
        except Exception as e:
            messages.error(request, str(e))

    return render(request, 'caixas/fechar.html', {'sessao': sessao})

@login_required
@permissao_required('pode_operar_caixa')
def movimentacao_caixa_view(request, sessao_id):
    empresa = request.tenant or request.user.empresa
    sessao = get_object_or_404(SessaoCaixa, id=sessao_id, empresa=empresa)

    if sessao.status != 'ABERTA':
        messages.error(request, "Não é possível lançar movimentações em uma sessão de caixa fechada.")
        return redirect('caixas_list')

    if request.method == 'POST':
        tipo = request.POST.get('tipo', '').upper().strip()
        valor = request.POST.get('valor', '0.00').replace(',', '.')
        motivo = request.POST.get('motivo', '').strip()
        try:
            mov = CashService.registrar_movimentacao(sessao, tipo, valor, motivo, request.user)
            messages.success(request, f"{mov.get_tipo_display()} de R$ {mov.valor:.2f} registrado com sucesso!")
            return redirect('caixas_list')
        except Exception as e:
            messages.error(request, str(e))

    return render(request, 'caixas/movimentacao.html', {'sessao': sessao})

@login_required
def relatorio_caixa_view(request, sessao_id):
    empresa = request.tenant or request.user.empresa
    sessao = get_object_or_404(SessaoCaixa, id=sessao_id, empresa=empresa)

    vendas = (
        sessao.vendas.filter(status='CONCLUIDA')
        .select_related('cliente', 'operador')
        .prefetch_related('pagamentos', 'itens__produto')
        .order_by('data_venda')
    )
    movimentacoes = sessao.movimentacoes.all().order_by('data_hora')

    return render(request, 'caixas/relatorio.html', {
        'sessao': sessao,
        'vendas': vendas,
        'movimentacoes': movimentacoes,
    })

@login_required
def relatorio_caixa_print_view(request, sessao_id):
    empresa = request.tenant or request.user.empresa
    sessao = get_object_or_404(SessaoCaixa, id=sessao_id, empresa=empresa)

    vendas = (
        sessao.vendas.filter(status='CONCLUIDA')
        .select_related('cliente')
        .prefetch_related('pagamentos', 'itens__produto')
        .order_by('data_venda')
    )
    movimentacoes = sessao.movimentacoes.all().order_by('data_hora')

    return render(request, 'caixas/relatorio_termico.html', {
        'sessao': sessao,
        'empresa': empresa,
        'vendas': vendas,
        'movimentacoes': movimentacoes,
    })
