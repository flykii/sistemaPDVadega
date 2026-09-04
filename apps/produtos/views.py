from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from decimal import Decimal, InvalidOperation
from .models import Produto, Categoria, MovimentacaoEstoque
from apps.clientes.models import Fornecedor
from apps.usuarios.permissions import permissao_required
from .services import StockService

def safe_decimal(value, default='0.00'):
    """Converte input do usuário com segurança para Decimal, tratando vírgulas."""
    if not value or str(value).strip() == '':
        return Decimal(default)
    try:
        cleaned = str(value).strip().replace(',', '.')
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return Decimal(default)


@login_required
def produtos_list(request):
    empresa = request.tenant or request.user.empresa
    query = request.GET.get('q', '').strip()
    categoria_id = request.GET.get('categoria', '')
    filtro_estoque = request.GET.get('estoque', '')

    produtos = (
        Produto.objects.filter(empresa=empresa)
        .select_related('categoria', 'fornecedor_principal')
        .order_by('nome')
    )

    if query:
        produtos = produtos.filter(
            Q(nome__icontains=query) |
            Q(codigo_barras__icontains=query) |
            Q(sku__icontains=query)
        )

    if categoria_id:
        produtos = produtos.filter(categoria_id=categoria_id)

    if filtro_estoque == 'baixo':
        produtos = [p for p in produtos if p.estoque_baixo and not p.estoque_zerado]
    elif filtro_estoque == 'zerado':
        produtos = [p for p in produtos if p.estoque_zerado]

    categorias = Categoria.objects.filter(empresa=empresa, ativo=True)

    return render(request, 'produtos/list.html', {
        'produtos': produtos,
        'categorias': categorias,
        'query': query,
        'categoria_id': categoria_id,
        'filtro_estoque': filtro_estoque,
    })


@login_required
@permissao_required('pode_ajustar_estoque')
def produto_form(request, pk=None):
    empresa = request.tenant or request.user.empresa
    produto = get_object_or_404(Produto, pk=pk, empresa=empresa) if pk else None
    categorias = Categoria.objects.filter(empresa=empresa, ativo=True)
    fornecedores = Fornecedor.objects.filter(empresa=empresa, ativo=True)

    if request.method == 'POST':
        nome = request.POST.get('nome', '').strip()
        codigo_barras = request.POST.get('codigo_barras', '').strip()
        sku = request.POST.get('sku', '').strip()
        descricao = request.POST.get('descricao', '').strip()
        categoria_id = request.POST.get('categoria_id')
        fornecedor_id = request.POST.get('fornecedor_id')
        
        preco_custo = safe_decimal(request.POST.get('preco_custo'), '0.00')
        margem_lucro = safe_decimal(request.POST.get('margem_lucro'), '30.00')
        preco_venda = safe_decimal(request.POST.get('preco_venda'), '0.00')
        estoque_atual = safe_decimal(request.POST.get('estoque_atual'), '0.000')
        estoque_minimo = safe_decimal(request.POST.get('estoque_minimo'), '5.000')
        estoque_maximo = safe_decimal(request.POST.get('estoque_maximo'), '1000.000')
        unidade_medida = request.POST.get('unidade_medida', 'UN')
        controle_estoque = request.POST.get('controle_estoque') == 'on' or request.POST.get('controle_estoque') == 'true'
        ativo = request.POST.get('ativo') == 'on' or request.POST.get('ativo') == 'true' or ('ativo' not in request.POST and pk is None)

        if not nome or not codigo_barras:
            messages.error(request, "Nome e Código de Barras são obrigatórios.")
            return render(request, 'produtos/form.html', {
                'produto': produto, 'categorias': categorias, 'fornecedores': fornecedores
            })

        # Verifica duplicidade de código de barras na mesma empresa
        duplicado = Produto.objects.filter(empresa=empresa, codigo_barras=codigo_barras)
        if produto:
            duplicado = duplicado.exclude(id=produto.id)
        if duplicado.exists():
            messages.error(request, f"Já existe um produto cadastrado com o código de barras '{codigo_barras}'.")
            return render(request, 'produtos/form.html', {
                'produto': produto, 'categorias': categorias, 'fornecedores': fornecedores
            })

        categoria = Categoria.objects.filter(id=categoria_id, empresa=empresa).first() if categoria_id else None
        fornecedor = Fornecedor.objects.filter(id=fornecedor_id, empresa=empresa).first() if fornecedor_id else None

        is_novo = produto is None
        if not produto:
            produto = Produto(empresa=empresa)

        produto.nome = nome
        produto.codigo_barras = codigo_barras
        produto.sku = sku
        produto.descricao = descricao
        produto.categoria = categoria
        produto.fornecedor_principal = fornecedor
        produto.preco_custo = preco_custo
        produto.margem_lucro = margem_lucro
        if preco_venda > 0:
            produto.preco_venda = preco_venda
        
        # Se for edição e o estoque mudou manualmente via form, registra movimentação
        if not is_novo and produto.estoque_atual != estoque_atual:
            StockService.adjust_stock(produto, estoque_atual, motivo="Ajuste pelo formulário de edição", usuario=request.user)
        else:
            produto.estoque_atual = estoque_atual

        produto.estoque_minimo = estoque_minimo
        produto.estoque_maximo = estoque_maximo
        produto.unidade_medida = unidade_medida
        produto.controle_estoque = controle_estoque
        produto.ativo = ativo

        if 'imagem' in request.FILES:
            produto.imagem = request.FILES['imagem']

        try:
            produto.save()
            if is_novo and estoque_atual > 0:
                StockService.add_stock(produto, estoque_atual, motivo="Estoque Inicial", usuario=request.user)

            messages.success(request, f"Produto '{produto.nome}' salvo com sucesso! Preço Venda: R$ {produto.preco_venda:.2f}")
            return redirect('produtos_list')
        except Exception as e:
            messages.error(request, f"Erro ao salvar produto: {str(e)}")

    return render(request, 'produtos/form.html', {
        'produto': produto,
        'categorias': categorias,
        'fornecedores': fornecedores,
    })


@login_required
@permissao_required('pode_ajustar_estoque')
def produto_excluir(request, pk):
    empresa = request.tenant or request.user.empresa
    produto = get_object_or_404(Produto, pk=pk, empresa=empresa)

    # Verifica se o produto tem histórico (vendas, compras ou movimentações)
    tem_vendas = produto.itens_venda.exists() if hasattr(produto, 'itens_venda') else False
    tem_compras = produto.itens_compra.exists() if hasattr(produto, 'itens_compra') else False
    tem_movs = produto.movimentacoes_estoque.exists()

    if tem_vendas or tem_compras or tem_movs:
        # Soft delete: desativa para preservar histórico
        produto.ativo = False
        produto.save()
        messages.warning(request, f"O produto '{produto.nome}' possui histórico de vendas/movimentações e foi INATIVADO para preservar relatórios fiscais.")
    else:
        produto.delete()
        messages.success(request, f"Produto '{produto.nome}' excluído com sucesso!")

    return redirect('produtos_list')


@login_required
@permissao_required('pode_ajustar_estoque')
def estoque_ajuste(request, pk):
    empresa = request.tenant or request.user.empresa
    produto = get_object_or_404(Produto, pk=pk, empresa=empresa)

    if request.method == 'POST':
        tipo = request.POST.get('tipo', 'AJUSTE')
        quantidade = safe_decimal(request.POST.get('quantidade'), '0.000')
        novo_saldo = safe_decimal(request.POST.get('novo_saldo'), '0.000')
        motivo = request.POST.get('motivo', '').strip()

        try:
            if tipo == 'ENTRADA':
                StockService.add_stock(produto, quantidade, motivo=f"Ajuste Manual: {motivo}", usuario=request.user)
            elif tipo == 'SAIDA':
                StockService.remove_stock(produto, quantidade, motivo=f"Ajuste Manual: {motivo}", usuario=request.user)
            elif tipo == 'NOVO_SALDO':
                StockService.adjust_stock(produto, novo_saldo, motivo=motivo or "Contagem / Balanço de Estoque", usuario=request.user)
            messages.success(request, f"Estoque do produto '{produto.nome}' atualizado com sucesso! Novo saldo: {produto.estoque_atual} {produto.unidade_medida}")
            return redirect('produtos_list')
        except Exception as e:
            messages.error(request, str(e))

    return render(request, 'produtos/ajuste.html', {'produto': produto})


@login_required
def estoque_baixo_list(request):
    empresa = request.tenant or request.user.empresa
    produtos = Produto.objects.filter(empresa=empresa, ativo=True).select_related('categoria', 'fornecedor_principal')
    
    produtos_baixos = [p for p in produtos if p.estoque_baixo]
    produtos_zerados = [p for p in produtos if p.estoque_zerado]

    return render(request, 'produtos/estoque_baixo.html', {
        'produtos_baixos': produtos_baixos,
        'produtos_zerados': produtos_zerados,
        'total_baixos': len(produtos_baixos),
        'total_zerados': len(produtos_zerados),
    })


@login_required
def movimentacoes_list(request):
    empresa = request.tenant or request.user.empresa
    tipo = request.GET.get('tipo', '')
    produto_id = request.GET.get('produto', '')

    movs = (
        MovimentacaoEstoque.objects.filter(empresa=empresa)
        .select_related('produto', 'usuario')
        .order_by('-data_hora')
    )

    if tipo:
        movs = movs.filter(tipo=tipo)
    if produto_id:
        movs = movs.filter(produto_id=produto_id)

    produtos = Produto.objects.filter(empresa=empresa, ativo=True).order_by('nome')

    return render(request, 'produtos/movimentacoes.html', {
        'movimentacoes': movs[:200],
        'produtos': produtos,
        'tipo_selecionado': tipo,
        'produto_selecionado': produto_id,
    })


@login_required
def categorias_list(request):
    empresa = request.tenant or request.user.empresa
    categorias = Categoria.objects.filter(empresa=empresa).order_by('nome')
    return render(request, 'produtos/categorias_list.html', {'categorias': categorias})


@login_required
@permissao_required('pode_ajustar_estoque')
def categoria_form(request, pk=None):
    empresa = request.tenant or request.user.empresa
    categoria = get_object_or_404(Categoria, pk=pk, empresa=empresa) if pk else None

    if request.method == 'POST':
        nome = request.POST.get('nome', '').strip()
        descricao = request.POST.get('descricao', '').strip()
        ativo = request.POST.get('ativo') == 'on' or request.POST.get('ativo') == 'true' or ('ativo' not in request.POST and pk is None)

        if not nome:
            messages.error(request, "O nome da categoria é obrigatório.")
            return render(request, 'produtos/categoria_form.html', {'categoria': categoria})

        # Impede categorias duplicadas com mesmo nome na mesma empresa
        duplicada = Categoria.objects.filter(empresa=empresa, nome__iexact=nome)
        if categoria:
            duplicada = duplicada.exclude(id=categoria.id)
        if duplicada.exists():
            messages.error(request, f"Já existe uma categoria cadastrada com o nome '{nome}'.")
            return render(request, 'produtos/categoria_form.html', {'categoria': categoria})

        if not categoria:
            categoria = Categoria(empresa=empresa)

        categoria.nome = nome
        categoria.descricao = descricao
        categoria.ativo = ativo

        try:
            categoria.save()
            messages.success(request, f"Categoria '{categoria.nome}' salva com sucesso!")
            return redirect('categorias_list')
        except Exception as e:
            messages.error(request, str(e))

    return render(request, 'produtos/categoria_form.html', {'categoria': categoria})
