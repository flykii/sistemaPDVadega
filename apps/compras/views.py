import json
from datetime import timedelta
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from apps.clientes.models import Fornecedor
from apps.produtos.models import Produto
from apps.usuarios.permissions import cargo_required
from .models import Compra, ItemCompra, RecebimentoCompra
from .services import PurchaseService

@login_required
def compras_list(request):
    empresa = request.tenant or request.user.empresa
    compras = (
        Compra.objects.filter(empresa=empresa)
        .select_related('fornecedor')
        .prefetch_related('itens__produto', 'recebimentos')
        .order_by('-data_compra')
    )
    return render(request, 'compras/list.html', {'compras': compras})


@login_required
@cargo_required('ADMIN', 'GERENTE', 'ESTOQUISTA', 'FINANCEIRO')
def nova_compra_view(request):
    empresa = request.tenant or request.user.empresa
    fornecedores = Fornecedor.objects.filter(empresa=empresa, ativo=True).order_by('nome_fantasia', 'razao_social')
    produtos = Produto.objects.filter(empresa=empresa, ativo=True).order_by('nome')

    fornecedores_json = json.dumps([
        {
            'id': f.id,
            'nome': f.nome_fantasia or f.razao_social,
            'prazo_dias': f.dias_prazo_calculados,
            'condicao': f.condicao_pagamento_padrao or 'A_PRAZO',
        }
        for f in fornecedores
    ])

    if request.method == 'POST':
        fornecedor_id = request.POST.get('fornecedor_id')
        numero_nota = request.POST.get('numero_nota', '').strip()
        data_vencimento = request.POST.get('data_vencimento', '').strip()
        observacoes = request.POST.get('observacoes', '').strip()

        fornecedor = Fornecedor.objects.filter(id=fornecedor_id, empresa=empresa).first() if fornecedor_id else None

        # Coleta itens dinâmicos do formulário
        produto_ids = request.POST.getlist('produto_id[]')
        quantidades = request.POST.getlist('quantidade[]')
        custos = request.POST.getlist('preco_custo[]')

        itens_data = []
        for p_id, q, c in zip(produto_ids, quantidades, custos):
            if p_id and q and c:
                try:
                    p_id_int = int(p_id)
                    q_val = float(str(q).replace(',', '.'))
                    c_val = float(str(c).replace(',', '.'))
                    if q_val > 0 and c_val >= 0:
                        itens_data.append({
                            'produto_id': p_id_int,
                            'quantidade': q_val,
                            'preco_custo_unitario': c_val
                        })
                except (ValueError, TypeError):
                    continue

        if not itens_data:
            messages.error(request, "Adicione ao menos um item com quantidade e custo válidos.")
            return render(request, 'compras/form.html', {
                'fornecedores': fornecedores,
                'fornecedores_json': fornecedores_json,
                'produtos': produtos,
                'itens_iniciais_json': json.dumps([]),
                'fornecedor_selecionado_id': fornecedor_id,
                'data_vencimento_inicial': data_vencimento,
            })

        try:
            compra = PurchaseService.criar_pedido_compra(
                empresa=empresa,
                fornecedor=fornecedor,
                numero_nota=numero_nota,
                itens_data=itens_data,
                data_vencimento=data_vencimento,
                observacoes=observacoes,
                usuario=request.user
            )
            messages.success(request, f"Pedido de Compra #{compra.numero_nota or compra.id} registrado com sucesso! Total: R$ {compra.total:.2f}. Aguardando recebimento das mercadorias.")
            return redirect('compras_list')
        except Exception as e:
            messages.error(request, f"Erro ao processar pedido de compra: {str(e)}")

    # GET: Pre-preenchimento vindo do Relatório de Reposição ou query params
    fornecedor_id_param = request.GET.get('fornecedor_id')
    fornecedor_obj = None
    data_vencimento_inicial = ''

    if fornecedor_id_param:
        fornecedor_obj = fornecedores.filter(id=fornecedor_id_param).first()
        if fornecedor_obj:
            prazo = fornecedor_obj.dias_prazo_calculados
            data_vencimento_inicial = (timezone.now().date() + timedelta(days=prazo)).strftime('%Y-%m-%d')

    if not data_vencimento_inicial:
        data_vencimento_inicial = timezone.now().date().strftime('%Y-%m-%d')

    req_prod_ids = request.GET.getlist('produto_id[]') or request.GET.getlist('produto_id')
    req_qtds = request.GET.getlist('quantidade[]') or request.GET.getlist('quantidade')
    req_custos = request.GET.getlist('preco_custo[]') or request.GET.getlist('preco_custo')

    itens_iniciais = []
    if req_prod_ids:
        # Mapeia produtos do banco para caso custo ou dados precisem ser consultados
        prods_dict = {p.id: p for p in produtos.filter(id__in=[int(pid) for pid in req_prod_ids if str(pid).isdigit()])}
        for i, pid_raw in enumerate(req_prod_ids):
            if str(pid_raw).isdigit():
                pid = int(pid_raw)
                p_obj = prods_dict.get(pid)
                if p_obj:
                    qtd = float(req_qtds[i]) if i < len(req_qtds) and req_qtds[i] else 1.0
                    custo = float(req_custos[i]) if i < len(req_custos) and req_custos[i] else float(p_obj.preco_custo or 0)
                    itens_iniciais.append({
                        'produto_id': pid,
                        'quantidade': qtd,
                        'preco_custo': custo,
                    })

    return render(request, 'compras/form.html', {
        'fornecedores': fornecedores,
        'fornecedores_json': fornecedores_json,
        'produtos': produtos,
        'fornecedor_selecionado_id': int(fornecedor_id_param) if (fornecedor_id_param and fornecedor_id_param.isdigit()) else '',
        'data_vencimento_inicial': data_vencimento_inicial,
        'itens_iniciais_json': json.dumps(itens_iniciais),
    })


@login_required
def compra_detalhe_view(request, pk):
    empresa = request.tenant or request.user.empresa
    compra = get_object_or_404(
        Compra.objects.prefetch_related(
            'itens__produto',
            'recebimentos__itens__produto',
            'recebimentos__usuario',
            'contas_pagar'
        ),
        pk=pk,
        empresa=empresa
    )
    return render(request, 'compras/detalhe.html', {'compra': compra})


@login_required
@cargo_required('ADMIN', 'GERENTE', 'ESTOQUISTA')
def receber_compra_view(request, pk):
    empresa = request.tenant or request.user.empresa
    compra = get_object_or_404(
        Compra.objects.prefetch_related('itens__produto', 'recebimentos'),
        pk=pk,
        empresa=empresa
    )

    if compra.status == 'CANCELADA':
        messages.error(request, "Não é possível receber mercadorias de uma compra cancelada.")
        return redirect('compra_detalhe', pk=compra.id)

    if compra.status == 'CONCLUIDA':
        messages.warning(request, "Esta compra já se encontra concluída / totalmente recebida.")
        return redirect('compra_detalhe', pk=compra.id)

    if request.method == 'POST':
        item_ids = request.POST.getlist('item_compra_id[]')
        quantidades = request.POST.getlist('quantidade_recebida[]')
        custos = request.POST.getlist('preco_custo[]')
        encerrar_compra = request.POST.get('encerrar_compra') == 'on' or request.POST.get('encerrar_compra') == 'true'
        observacao = request.POST.get('observacao', '').strip()

        itens_recebidos = []
        for i_id, q, c in zip(item_ids, quantidades, custos):
            if i_id and q:
                try:
                    i_id_int = int(i_id)
                    q_val = float(str(q).replace(',', '.'))
                    c_val = float(str(c).replace(',', '.')) if c else None
                    if q_val > 0:
                        itens_recebidos.append({
                            'item_compra_id': i_id_int,
                            'quantidade_recebida': q_val,
                            'preco_custo': c_val
                        })
                except (ValueError, TypeError):
                    continue

        if not itens_recebidos:
            messages.error(request, "Informe ao menos um produto com quantidade recebida maior que zero.")
            return render(request, 'compras/receber.html', {'compra': compra})

        try:
            recebimento = PurchaseService.registrar_recebimento(
                compra=compra,
                itens_recebidos=itens_recebidos,
                encerrar_compra=encerrar_compra,
                observacao=observacao,
                usuario=request.user
            )
            messages.success(request, f"Recebimento da Compra #{compra.id} registrado com sucesso! Estoque e histórico atualizados.")
            return redirect('compra_detalhe', pk=compra.id)
        except Exception as e:
            messages.error(request, f"Erro ao registrar recebimento: {str(e)}")

    return render(request, 'compras/receber.html', {'compra': compra})


@login_required
@cargo_required('ADMIN', 'GERENTE')
def cancelar_compra_view(request, pk):
    empresa = request.tenant or request.user.empresa
    compra = get_object_or_404(Compra, pk=pk, empresa=empresa)

    if request.method == 'POST':
        motivo = request.POST.get('motivo', '').strip()
        try:
            PurchaseService.cancelar_compra(compra=compra, usuario=request.user, motivo=motivo)
            messages.success(request, f"Compra #{compra.id} cancelada com sucesso.")
        except Exception as e:
            messages.error(request, f"Erro ao cancelar compra: {str(e)}")

    return redirect('compra_detalhe', pk=compra.id)


@login_required
def fornecedores_list(request):
    empresa = request.tenant or request.user.empresa
    fornecedores = Fornecedor.objects.filter(empresa=empresa).order_by('nome_fantasia', 'razao_social')
    return render(request, 'compras/fornecedores_list.html', {'fornecedores': fornecedores})


@login_required
@cargo_required('ADMIN', 'GERENTE', 'ESTOQUISTA', 'FINANCEIRO')
def fornecedor_form(request, pk=None):
    empresa = request.tenant or request.user.empresa
    fornecedor = get_object_or_404(Fornecedor, pk=pk, empresa=empresa) if pk else None

    if request.method == 'POST':
        razao_social = request.POST.get('razao_social', '').strip()
        nome_fantasia = request.POST.get('nome_fantasia', '').strip()
        cnpj = request.POST.get('cnpj', '').strip()
        telefone = request.POST.get('telefone', '').strip()
        email = request.POST.get('email', '').strip()
        endereco = request.POST.get('endereco', '').strip()
        contato_nome = request.POST.get('contato_nome', '').strip()
        observacoes = request.POST.get('observacoes', '').strip()
        ativo = request.POST.get('ativo') == 'on' or request.POST.get('ativo') == 'true' or ('ativo' not in request.POST and pk is None)

        condicao_pagamento = request.POST.get('condicao_pagamento_padrao', '30_DIAS').strip()
        prazo_dias_str = request.POST.get('prazo_pagamento_dias', '').strip()

        dias_map = {
            'A_VISTA': 0, '1_DIA': 1, '2_DIAS': 2, '3_DIAS': 3, '4_DIAS': 4,
            '7_DIAS': 7, '14_DIAS': 14, '21_DIAS': 21, '28_DIAS': 28, '30_DIAS': 30
        }
        if condicao_pagamento in dias_map and not prazo_dias_str:
            prazo_dias = dias_map[condicao_pagamento]
        else:
            try:
                prazo_dias = int(prazo_dias_str) if prazo_dias_str else dias_map.get(condicao_pagamento, 30)
            except ValueError:
                prazo_dias = 30

        if not razao_social and not nome_fantasia:
            messages.error(request, "Informe a Razão Social ou o Nome Fantasia do fornecedor.")
            return render(request, 'compras/fornecedor_form.html', {'fornecedor': fornecedor})

        if not fornecedor:
            fornecedor = Fornecedor(empresa=empresa)

        fornecedor.razao_social = razao_social or nome_fantasia
        fornecedor.nome_fantasia = nome_fantasia or razao_social
        fornecedor.cnpj = cnpj
        fornecedor.telefone = telefone
        fornecedor.email = email
        fornecedor.endereco = endereco
        fornecedor.contato_nome = contato_nome
        fornecedor.condicao_pagamento_padrao = condicao_pagamento
        fornecedor.prazo_pagamento_dias = max(0, prazo_dias)
        fornecedor.observacoes = observacoes
        fornecedor.ativo = ativo

        try:
            fornecedor.save()
            messages.success(request, f"Fornecedor '{fornecedor.nome_fantasia}' salvo com sucesso!")
            return redirect('fornecedores_list')
        except Exception as e:
            messages.error(request, f"Erro ao salvar fornecedor: {str(e)}")

    return render(request, 'compras/fornecedor_form.html', {'fornecedor': fornecedor})
