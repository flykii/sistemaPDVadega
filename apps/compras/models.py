from django.db import models
from apps.core.models import TenantModelMixin
from apps.clientes.models import Fornecedor
from apps.produtos.models import Produto

class Compra(TenantModelMixin):
    STATUS_CHOICES = [
        ('RASCUNHO', 'Rascunho'),
        ('CONCLUIDA', 'Concluída'),
        ('CANCELADA', 'Cancelada'),
    ]

    fornecedor = models.ForeignKey(Fornecedor, on_delete=models.SET_NULL, null=True, blank=True, related_name='compras')
    numero_nota = models.CharField('Número da NF / Pedido', max_length=50, blank=True)
    total = models.DecimalField('Total (R$)', max_digits=12, decimal_places=2, default=0.00)
    data_compra = models.DateTimeField('Data da Compra', auto_now_add=True)
    status = models.CharField('Status', max_length=15, choices=STATUS_CHOICES, default='RASCUNHO')
    observacoes = models.TextField('Observações', blank=True)

    class Meta:
        verbose_name = 'Compra'
        verbose_name_plural = 'Compras'

    def __str__(self):
        fornec = self.fornecedor.nome_fantasia if self.fornecedor else "Sem Fornecedor"
        return f"Compra #{self.id} - {fornec} (R$ {self.total})"


class ItemCompra(TenantModelMixin):
    compra = models.ForeignKey(Compra, on_delete=models.CASCADE, related_name='itens')
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name='itens_compra')
    quantidade = models.DecimalField('Quantidade', max_digits=12, decimal_places=3)
    preco_custo_unitario = models.DecimalField('Custo Unitário (R$)', max_digits=12, decimal_places=2)
    subtotal = models.DecimalField('Subtotal (R$)', max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = 'Item de Compra'
        verbose_name_plural = 'Itens de Compra'

    def save(self, *args, **kwargs):
        self.subtotal = self.quantidade * self.preco_custo_unitario
        super().save(*args, **kwargs)
