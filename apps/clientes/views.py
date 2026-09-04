from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum
from .models import Cliente
from apps.financeiro.models import ContaReceber, PagamentoContaReceber
from apps.vendas.models import Venda
from apps.caixas.models import SessaoCaixa
from apps.financeiro.services import FinancialService
from apps.core.models import AuditService
from apps.usuarios.permissions import cargo_required

def safe_decimal(value, default='0.00'):
    if not value or str(value).strip() == '':
        return Decimal(default)
    try:
        cleaned = str(value).strip().replace(',', '.')
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return Decimal(default)


@login_required
def clientes_list(request):
    empresa = request.tenant or request.user.empresa
    query = request.GET.get('q', '').strip()
    filtro = request.GET.get('filtro', '')

    clientes = Cliente.objects.filter(empresa=empresa).order_by('nome')

    if query:
        clientes = clientes.filter(
            Q(nome__icontains=query) |
            Q(cpf_cnpj__icontains=query) |
            Q(telefone__icontains=query) |
            Q(celular__icontains=query) |
            Q(email__icontains=query)
        )

    if filtro == 'devedores':
        clientes = clientes.filter(saldo_devedor__gt=Decimal('0.00'))
    elif filtro == 'inativos':
        clientes = clientes.filter(ativo=False)
    elif filtro == 'ativos':
        clientes = clientes.filter(ativo=True)

    # Totais para os cards do topo
    todos = Cliente.objects.filter(empresa=empresa)
    total_clientes = todos.count()
    total_saldo_devedor = sum((c.saldo_devedor for c in todos), Decimal('0.00'))
    total_limite_concedido = sum((c.limite_credito for c in todos), Decimal('0.00'))
    total_devedores = todos.filter(saldo_devedor__gt=Decimal('0.00')).count()

    return render(request, 'clientes/clientes_list.html', {
        'clientes': clientes,
        'query': query,
        'filtro': filtro,
        'total_clientes': total_clientes,
        'total_saldo_devedor': total_saldo_devedor,
        'total_limite_concedido': total_limite_concedido,
        'total_devedores': total_devedores,
    })


@login_required
@cargo_required('ADMIN', 'GERENTE', 'OPERADOR', 'FINANCEIRO')
def cliente_form(request, pk=None):
    empresa = request.tenant or request.user.empresa
    cliente = get_object_or_404(Cliente, pk=pk, empresa=empresa) if pk else None

    if request.method == 'POST':
        nome = request.POST.get('nome', '').strip()
        cpf_cnpj = request.POST.get('cpf_cnpj', '').strip()
        telefone = request.POST.get('telefone', '').strip()
        celular = request.POST.get('celular', '').strip()
        email = request.POST.get('email', '').strip()
        endereco = request.POST.get('endereco', '').strip()
        numero = request.POST.get('numero', '').strip()
        complemento = request.POST.get('complemento', '').strip()
        bairro = request.POST.get('bairro', '').strip()
        cidade = request.POST.get('cidade', '').strip()
        estado = request.POST.get('estado', '').strip()
        cep = request.POST.get('cep', '').strip()
        limite_credito = safe_decimal(request.POST.get('limite_credito'), '0.00')
        observacoes = request.POST.get('observacoes', '').strip()
        ativo = request.POST.get('ativo') == 'on' or request.POST.get('ativo') == 'true' or ('ativo' not in request.POST and pk is None)

        if not nome:
            messages.error(request, "O nome do cliente é obrigatório.")
            return render(request, 'clientes/cliente_form.html', {'cliente': cliente})

        # Validação de documento duplicado dentro do mesmo tenant
        if cpf_cnpj:
            duplicado = Cliente.objects.filter(empresa=empresa, cpf_cnpj=cpf_cnpj)
            if cliente:
                duplicado = duplicado.exclude(id=cliente.id)
            if duplicado.exists():
                messages.error(request, f"Já existe um cliente cadastrado com o CPF/CNPJ '{cpf_cnpj}'.")
                return render(request, 'clientes/cliente_form.html', {'cliente': cliente})

        is_novo = cliente is None
        dados_ant = {}
        if not is_novo:
            dados_ant = {
                'nome': cliente.nome,
                'cpf_cnpj': cliente.cpf_cnpj,
                'limite_credito': str(cliente.limite_credito),
                'ativo': cliente.ativo
            }
        else:
            cliente = Cliente(empresa=empresa)

        limite_antigo = cliente.limite_credito if not is_novo else Decimal('0.00')

        cliente.nome = nome
        cliente.cpf_cnpj = cpf_cnpj
        cliente.telefone = telefone
        cliente.celular = celular
        cliente.email = email
        cliente.endereco = endereco
        cliente.numero = numero
        cliente.complemento = complemento
        cliente.bairro = bairro
        cliente.cidade = cidade
        cliente.estado = estado
        cliente.cep = cep
        cliente.limite_credito = limite_credito
        cliente.observacoes = observacoes
        cliente.ativo = ativo

        try:
            cliente.save()

            # Trilha de Auditoria
            if is_novo:
                AuditService.registrar(
                    empresa=empresa,
                    usuario=request.user,
                    acao='CLIENTE_CRIADO',
                    entidade='Cliente',
                    entidade_id=cliente.id,
                    descricao=f"Cliente '{cliente.nome}' cadastrado com limite de R$ {cliente.limite_credito:.2f}",
                    dados_posteriores={'nome': cliente.nome, 'cpf_cnpj': cliente.cpf_cnpj, 'limite': str(cliente.limite_credito)}
                )
            else:
                AuditService.registrar(
                    empresa=empresa,
                    usuario=request.user,
                    acao='CLIENTE_ALTERADO',
                    entidade='Cliente',
                    entidade_id=cliente.id,
                    descricao=f"Dados do cliente '{cliente.nome}' alterados",
                    dados_anteriores=dados_ant,
                    dados_posteriores={'nome': cliente.nome, 'cpf_cnpj': cliente.cpf_cnpj, 'limite': str(cliente.limite_credito), 'ativo': cliente.ativo}
                )
                if limite_antigo != cliente.limite_credito:
                    AuditService.registrar(
                        empresa=empresa,
                        usuario=request.user,
                        acao='LIMITE_CREDITO_ALTERADO',
                        entidade='Cliente',
                        entidade_id=cliente.id,
                        descricao=f"Limite de crédito de '{cliente.nome}' alterado de R$ {limite_antigo:.2f} para R$ {cliente.limite_credito:.2f}",
                        dados_anteriores={'limite_anterior': str(limite_antigo)},
                        dados_posteriores={'limite_novo': str(cliente.limite_credito)}
                    )

            messages.success(request, f"Cliente '{cliente.nome}' salvo com sucesso!")
            return redirect('cliente_ficha', pk=cliente.id)
        except Exception as e:
            messages.error(request, f"Erro ao salvar cliente: {str(e)}")

    return render(request, 'clientes/cliente_form.html', {'cliente': cliente})


@login_required
def cliente_ficha(request, pk):
    empresa = request.tenant or request.user.empresa
    cliente = get_object_or_404(Cliente, pk=pk, empresa=empresa)

    contas = (
        ContaReceber.objects.filter(empresa=empresa, cliente=cliente)
        .select_related('venda')
        .order_by('data_vencimento', '-id')
    )

    vendas = (
        Venda.objects.filter(empresa=empresa, cliente=cliente)
        .prefetch_related('itens__produto', 'pagamentos')
        .order_by('-data_venda')
    )

    pagamentos_recebidos = (
        PagamentoContaReceber.objects.filter(empresa=empresa, conta_receber__cliente=cliente)
        .select_related('conta_receber', 'usuario', 'sessao_caixa')
        .order_by('-data_hora')
    )

    # Processamento de recebimento rápido de conta na ficha do cliente
    if request.method == 'POST':
        conta_id = request.POST.get('conta_id')
        valor_pago = safe_decimal(request.POST.get('valor_pago'), '0.00')
        forma_pagamento = request.POST.get('forma_pagamento', 'DINHEIRO')
        troco = safe_decimal(request.POST.get('troco'), '0.00')
        observacao = request.POST.get('observacao', '').strip()

        conta = get_object_or_404(ContaReceber, id=conta_id, empresa=empresa, cliente=cliente)
        sessao_caixa = SessaoCaixa.objects.filter(empresa=empresa, operador=request.user, status='ABERTA').first()

        try:
            FinancialService.receber_pagamento_conta(
                conta=conta,
                valor_pago=valor_pago,
                forma_pagamento=forma_pagamento,
                troco=troco,
                sessao_caixa=sessao_caixa,
                usuario=request.user,
                observacao=observacao
            )
            messages.success(request, f"Pagamento de R$ {valor_pago - troco:.2f} registrado com sucesso para a conta #{conta.id}!")
            return redirect('cliente_ficha', pk=cliente.id)
        except Exception as e:
            messages.error(request, str(e))

    return render(request, 'clientes/cliente_ficha.html', {
        'cliente': cliente,
        'contas': contas,
        'vendas': vendas,
        'pagamentos_recebidos': pagamentos_recebidos,
    })

