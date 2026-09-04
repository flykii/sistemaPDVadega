from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from apps.clientes.models import Fornecedor
from apps.produtos.models import Produto
from apps.usuarios.permissions import cargo_required
from .models import Compra
from .services import PurchaseService

@login_required
def compras_list(request):
    empresa = request.tenant or request.user.empresa
    compras = (
        Compra.objects.filter(empresa=empresa)
        .select_related('fornecedor')
        .prefetch_related('itens__produto')
        .order_by('-data_compra')
    )
    return render(request, 'compras/list.html', {'compras': compras})


@login_required
@cargo_required('ADMIN', 'GERENTE', 'ESTOQUISTA', 'FINANCEIRO')
def nova_compra_view(request):
    empresa = request.tenant or request.user.empresa
    fornecedores = Fornecedor.objects.filter(empresa=empresa, ativo=True).order_by('nome_fantasia', 'razao_social')
    produtos = Produto.objects.filter(empresa=empresa, ativo=True).order_by('nome')

    if request.method == 'POST':
        fornecedor_id = request.POST.get('fornecedor_id')
        numero_nota = request.POST.get('numero_nota', '').strip()
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
                'fornecedores': fornecedores, 'produtos': produtos
            })

        try:
            compra = PurchaseService.processar_compra(
                empresa=empresa,
                fornecedor=fornecedor,
                numero_nota=numero_nota,
                itens_data=itens_data,
                observacoes=observacoes,
                usuario=request.user
            )
            messages.success(request, f"Compra NF #{compra.numero_nota or compra.id} registrada com sucesso! Total: R$ {compra.total:.2f}. Estoque e contas a pagar atualizados.")
            return redirect('compras_list')
        except Exception as e:
            messages.error(request, f"Erro ao processar compra: {str(e)}")

    return render(request, 'compras/form.html', {
        'fornecedores': fornecedores,
        'produtos': produtos
    })


@login_required
def compra_detalhe_view(request, pk):
    empresa = request.tenant or request.user.empresa
    compra = get_object_or_404(Compra, pk=pk, empresa=empresa)
    return render(request, 'compras/detalhe.html', {'compra': compra})


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
        fornecedor.observacoes = observacoes
        fornecedor.ativo = ativo

        try:
            fornecedor.save()
            messages.success(request, f"Fornecedor '{fornecedor.nome_fantasia}' salvo com sucesso!")
            return redirect('fornecedores_list')
        except Exception as e:
            messages.error(request, f"Erro ao salvar fornecedor: {str(e)}")

    return render(request, 'compras/fornecedor_form.html', {'fornecedor': fornecedor})
