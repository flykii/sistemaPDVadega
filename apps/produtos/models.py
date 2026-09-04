from django.db import models
from decimal import Decimal
from django.conf import settings
from apps.core.models import TenantModelMixin
from apps.core.pricing import calculate_sale_price, calculate_margin_percent, calculate_profit_amount

class Categoria(TenantModelMixin):
    nome = models.CharField('Nome da Categoria', max_length=100)
    descricao = models.TextField('Descrição', blank=True)
    ativo = models.BooleanField('Ativo', default=True)

    class Meta:
        verbose_name = 'Categoria'
        verbose_name_plural = 'Categorias'
        unique_together = ['empresa', 'nome']

    def __str__(self):
        return self.nome


class Produto(TenantModelMixin):
    UNIDADE_CHOICES = [
        ('UN', 'Unidade (UN)'),
        ('KG', 'Quilograma (KG)'),
        ('G', 'Grama (G)'),
        ('L', 'Litro (L)'),
        ('ML', 'Mililitro (ML)'),
        ('LT', 'Lata (LT)'),
        ('CX', 'Caixa (CX)'),
        ('PCT', 'Pacote (PCT)'),
        ('FD', 'Fardo (FD)'),
        ('M2', 'Metro Quadrado (M²)'),
    ]

    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True, related_name='produtos')
    fornecedor_principal = models.ForeignKey('clientes.Fornecedor', on_delete=models.SET_NULL, null=True, blank=True, related_name='produtos')
    codigo_barras = models.CharField('Código de Barras (EAN)', max_length=50, db_index=True)
    sku = models.CharField('SKU / Código Interno', max_length=50, blank=True, db_index=True)
    nome = models.CharField('Nome do Produto', max_length=200)
    descricao = models.TextField('Descrição / Detalhes', blank=True)
    
    preco_custo = models.DecimalField('Preço de Custo (R$)', max_digits=12, decimal_places=2, default=0.00)
    margem_lucro = models.DecimalField('Margem de Lucro Bruto (%)', max_digits=6, decimal_places=2, default=30.00, help_text="Cálculo base: Venda = Custo / (1 - (Margem/100))")
    preco_venda = models.DecimalField('Preço de Venda (R$)', max_digits=12, decimal_places=2, default=0.00)
    
    estoque_atual = models.DecimalField('Estoque Atual', max_digits=12, decimal_places=3, default=0.000)
    estoque_minimo = models.DecimalField('Estoque Mínimo', max_digits=12, decimal_places=3, default=5.000)
    estoque_maximo = models.DecimalField('Estoque Máximo', max_digits=12, decimal_places=3, default=1000.000, null=True, blank=True)
    unidade_medida = models.CharField('Unidade de Medida', max_length=10, choices=UNIDADE_CHOICES, default='UN')
    controle_estoque = models.BooleanField('Controla Estoque', default=True)
    
    imagem = models.ImageField('Imagem do Produto', upload_to='produtos/', null=True, blank=True)
    ativo = models.BooleanField('Ativo', default=True)

    class Meta:
        verbose_name = 'Produto'
        verbose_name_plural = 'Produtos'
        unique_together = ['empresa', 'codigo_barras']

    def __str__(self):
        return f"{self.nome} - R$ {self.preco_venda} [{self.codigo_barras}]"

    @property
    def lucro_real(self) -> Decimal:
        """Retorna o lucro líquido em moeda (R$) conforme regra do cliente."""
        return calculate_profit_amount(self.preco_custo, self.preco_venda)

    @property
    def estoque_baixo(self) -> bool:
        return self.estoque_atual <= self.estoque_minimo

    @property
    def estoque_zerado(self) -> bool:
        return self.estoque_atual <= Decimal('0.000')

    @property
    def status_estoque(self) -> str:
        if self.estoque_zerado:
            return 'ZERADO'
        elif self.estoque_baixo:
            return 'BAIXO'
        return 'NORMAL'

    @property
    def valor_estoque_custo(self) -> Decimal:
        return self.estoque_atual * self.preco_custo

    def save(self, *args, **kwargs):
        # Aplica a fórmula exata do usuário se preco_venda não for explicitamente modificado
        if self.preco_custo > 0:
            if self.margem_lucro > 0 and (not self.preco_venda or self.preco_venda <= self.preco_custo):
                self.preco_venda = calculate_sale_price(self.preco_custo, self.margem_lucro)
            elif self.preco_venda > 0:
                self.margem_lucro = calculate_margin_percent(self.preco_custo, self.preco_venda)
        super().save(*args, **kwargs)


class MovimentacaoEstoque(TenantModelMixin):
    TIPO_CHOICES = [
        ('ENTRADA', 'Entrada'),
        ('SAIDA', 'Saída'),
        ('AJUSTE', 'Ajuste Manual'),
        ('ESTORNO', 'Estorno'),
    ]

    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name='movimentacoes_estoque')
    tipo = models.CharField('Tipo de Movimentação', max_length=10, choices=TIPO_CHOICES)
    quantidade = models.DecimalField('Quantidade', max_digits=12, decimal_places=3)
    estoque_anterior = models.DecimalField('Estoque Anterior', max_digits=12, decimal_places=3, default=0.000)
    estoque_posterior = models.DecimalField('Estoque Posterior', max_digits=12, decimal_places=3, default=0.000)
    preco_custo_unitario = models.DecimalField('Custo Unitário (R$)', max_digits=12, decimal_places=2, null=True, blank=True)
    motivo = models.CharField('Motivo', max_length=255)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='movimentacoes_estoque')
    origem_ref = models.CharField('Referência de Origem', max_length=100, blank=True)
    data_hora = models.DateTimeField('Data/Hora', auto_now_add=True)

    class Meta:
        verbose_name = 'Movimentação de Estoque'
        verbose_name_plural = 'Movimentações de Estoque'
        ordering = ['-data_hora']

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.produto.nome} ({self.quantidade} {self.produto.unidade_medida})"
