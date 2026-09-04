from rest_framework import serializers
from apps.produtos.models import Produto, Categoria
from apps.clientes.models import Cliente
from apps.caixas.models import Caixa, SessaoCaixa
from apps.vendas.models import Venda, ItemVenda, PagamentoVenda

class CategoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Categoria
        fields = ['id', 'nome', 'descricao']


class ProdutoSerializer(serializers.ModelSerializer):
    categoria_nome = serializers.ReadOnlyField(source='categoria.nome')
    lucro_real = serializers.ReadOnlyField()

    class Meta:
        model = Produto
        fields = [
            'id', 'codigo_barras', 'sku', 'nome', 'categoria', 'categoria_nome',
            'preco_custo', 'margem_lucro', 'preco_venda', 'lucro_real',
            'estoque_atual', 'estoque_minimo', 'unidade_medida', 'imagem', 'ativo'
        ]


class ClienteSerializer(serializers.ModelSerializer):
    credito_disponivel = serializers.ReadOnlyField()
    percentual_utilizado = serializers.ReadOnlyField()

    class Meta:
        model = Cliente
        fields = [
            'id', 'nome', 'cpf_cnpj', 'telefone', 'celular', 'email',
            'endereco', 'numero', 'bairro', 'cidade', 'estado', 'cep',
            'limite_credito', 'saldo_devedor', 'credito_disponivel', 'percentual_utilizado', 'ativo'
        ]


class CaixaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Caixa
        fields = ['id', 'nome', 'codigo_identificador', 'status', 'ativo']


class SessaoCaixaSerializer(serializers.ModelSerializer):
    caixa_nome = serializers.ReadOnlyField(source='caixa.nome')
    operador_nome = serializers.ReadOnlyField(source='operador.username')

    class Meta:
        model = SessaoCaixa
        fields = [
            'id', 'caixa', 'caixa_nome', 'operador', 'operador_nome',
            'data_abertura', 'saldo_inicial', 'status'
        ]


class ItemVendaSerializer(serializers.ModelSerializer):
    produto_nome = serializers.ReadOnlyField(source='produto.nome')
    codigo_barras = serializers.ReadOnlyField(source='produto.codigo_barras')

    class Meta:
        model = ItemVenda
        fields = ['id', 'produto', 'produto_nome', 'codigo_barras', 'quantidade', 'preco_custo_unitario', 'preco_venda_unitario', 'subtotal']


class PagamentoVendaSerializer(serializers.ModelSerializer):
    forma_display = serializers.CharField(source='get_forma_pagamento_display', read_only=True)

    class Meta:
        model = PagamentoVenda
        fields = ['id', 'forma_pagamento', 'forma_display', 'valor', 'troco', 'dados_transacao']


class VendaSerializer(serializers.ModelSerializer):
    itens = ItemVendaSerializer(many=True, read_only=True)
    pagamentos = PagamentoVendaSerializer(many=True, read_only=True)
    cliente_nome = serializers.ReadOnlyField(source='cliente.nome')
    operador_nome = serializers.ReadOnlyField(source='operador.username')
    lucro_total = serializers.ReadOnlyField()

    class Meta:
        model = Venda
        fields = [
            'id', 'codigo_venda', 'sessao_caixa', 'cliente', 'cliente_nome',
            'operador', 'operador_nome', 'subtotal', 'desconto', 'total',
            'lucro_total', 'status', 'offline_uuid', 'data_venda', 'itens', 'pagamentos'
        ]


class VendaItemInputSerializer(serializers.Serializer):
    produto_id = serializers.IntegerField()
    quantidade = serializers.DecimalField(max_digits=12, decimal_places=3)
    preco_venda = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)


class PagamentoInputSerializer(serializers.Serializer):
    forma = serializers.ChoiceField(choices=['DINHEIRO', 'CARTAO_CREDITO', 'CARTAO_DEBITO', 'PIX', 'CREDIARIO'])
    valor = serializers.DecimalField(max_digits=12, decimal_places=2)
    troco = serializers.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    dados = serializers.JSONField(required=False, default=dict)


class ProcessarVendaInputSerializer(serializers.Serializer):
    sessao_caixa_id = serializers.IntegerField(required=False, allow_null=True)
    cliente_id = serializers.IntegerField(required=False, allow_null=True)
    desconto = serializers.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    offline_uuid = serializers.CharField(required=False, allow_blank=True, default='')
    observacao = serializers.CharField(required=False, allow_blank=True, default='')
    itens = VendaItemInputSerializer(many=True)
    pagamentos = PagamentoInputSerializer(many=True)
