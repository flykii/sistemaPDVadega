from django.db import models
from decimal import Decimal
import uuid
from apps.core.models import TenantModelMixin
from apps.caixas.models import SessaoCaixa
from apps.clientes.models import Cliente
from apps.produtos.models import Produto
from django.conf import settings

class Venda(TenantModelMixin):
    STATUS_CHOICES = [
        ('CONCLUIDA', 'Concluída'),
        ('CANCELADA', 'Cancelada'),
        ('RASCUNHO', 'Rascunho'),
    ]

    sessao_caixa = models.ForeignKey(SessaoCaixa, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendas')
    cliente = models.ForeignKey(Cliente, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendas')
    operador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='vendas_realizadas')
    codigo_venda = models.CharField('Código da Venda', max_length=50)
    subtotal = models.DecimalField('Subtotal (R$)', max_digits=12, decimal_places=2, default=0.00)
    desconto = models.DecimalField('Desconto (R$)', max_digits=12, decimal_places=2, default=0.00)
    total = models.DecimalField('Total (R$)', max_digits=12, decimal_places=2, default=0.00)
    status = models.CharField('Status', max_length=15, choices=STATUS_CHOICES, default='CONCLUIDA')
    offline_uuid = models.CharField('UUID Offline PWA', max_length=64, blank=True, db_index=True)
    data_venda = models.DateTimeField('Data da Venda', auto_now_add=True)
    observacao = models.TextField('Observação', blank=True)
    motivo_cancelamento = models.TextField('Motivo do Cancelamento', blank=True)
    cancelado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vendas_canceladas', verbose_name='Cancelado por'
    )
    data_cancelamento = models.DateTimeField('Data/Hora do Cancelamento', null=True, blank=True)

    class Meta:
        verbose_name = 'Venda'
        verbose_name_plural = 'Vendas'
        unique_together = ['empresa', 'codigo_venda']
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'offline_uuid'],
                condition=~models.Q(offline_uuid=''),
                name='unique_empresa_offline_uuid'
            )
        ]

    def __str__(self):
        return f"Venda #{self.codigo_venda} - R$ {self.total} ({self.get_status_display()})"

    @property
    def lucro_total(self) -> Decimal:
        """Calcula o lucro bruto total da venda somando o lucro de cada item."""
        total_lucro = sum(item.lucro_real_item for item in self.itens.all())
        return Decimal(str(total_lucro))


class ItemVenda(TenantModelMixin):
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name='itens')
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name='itens_venda')
    quantidade = models.DecimalField('Quantidade', max_digits=12, decimal_places=3)
    preco_custo_unitario = models.DecimalField('Custo Unitário (R$)', max_digits=12, decimal_places=2)
    preco_venda_unitario = models.DecimalField('Preço Unitário (R$)', max_digits=12, decimal_places=2)
    subtotal = models.DecimalField('Subtotal (R$)', max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = 'Item de Venda'
        verbose_name_plural = 'Itens de Venda'

    def save(self, *args, **kwargs):
        self.subtotal = self.quantidade * self.preco_venda_unitario
        super().save(*args, **kwargs)

    @property
    def lucro_real_item(self) -> Decimal:
        """Lucro Real = (Preço Venda Unitário - Preço Custo Unitário) * Quantidade"""
        lucro_unitario = self.preco_venda_unitario - self.preco_custo_unitario
        return (lucro_unitario * Decimal(str(self.quantidade))).quantize(Decimal('0.01'))


class PagamentoVenda(TenantModelMixin):
    FORMA_CHOICES = [
        ('DINHEIRO', 'Dinheiro'),
        ('CARTAO_CREDITO', 'Cartão de Crédito'),
        ('CARTAO_DEBITO', 'Cartão de Débito'),
        ('PIX', 'PIX'),
        ('CREDIARIO', 'Crediário / Fiado'),
    ]

    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name='pagamentos')
    forma_pagamento = models.CharField('Forma de Pagamento', max_length=20, choices=FORMA_CHOICES)
    valor = models.DecimalField('Valor Pago (R$)', max_digits=12, decimal_places=2)
    troco = models.DecimalField('Troco (R$)', max_digits=12, decimal_places=2, default=0.00)
    dados_transacao = models.JSONField('Dados da Transação (TEF / PIX)', default=dict, blank=True)

    class Meta:
        verbose_name = 'Pagamento de Venda'
        verbose_name_plural = 'Pagamentos de Vendas'

    @property
    def valor_efetivo(self) -> Decimal:
        """Retorna o valor líquido destinado à quitação da venda (Valor Recebido - Troco)."""
        return Decimal(str(self.valor)) - Decimal(str(self.troco))

    def __str__(self):
        return f"{self.get_forma_pagamento_display()} - R$ {self.valor} (Efetivo: R$ {self.valor_efetivo})"
