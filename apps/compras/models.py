from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.conf import settings
from apps.core.models import TenantModelMixin
from apps.clientes.models import Fornecedor
from apps.produtos.models import Produto

class Compra(TenantModelMixin):
    STATUS_CHOICES = [
        ('PENDENTE', 'Aguardando Recebimento'),
        ('PARCIAL', 'Recebimento Parcial'),
        ('CONCLUIDA', 'Concluída / Recebida'),
        ('CANCELADA', 'Cancelada'),
        ('RASCUNHO', 'Rascunho'), # Compatibilidade
    ]

    fornecedor = models.ForeignKey(Fornecedor, on_delete=models.SET_NULL, null=True, blank=True, related_name='compras')
    numero_nota = models.CharField('Número da NF / Pedido', max_length=50, blank=True)
    total = models.DecimalField('Total (R$)', max_digits=12, decimal_places=2, default=0.00)
    data_compra = models.DateTimeField('Data da Compra', auto_now_add=True)
    status = models.CharField('Status', max_length=20, choices=STATUS_CHOICES, default='PENDENTE')
    observacoes = models.TextField('Observações', blank=True)

    class Meta:
        verbose_name = 'Compra'
        verbose_name_plural = 'Compras'
        ordering = ['-data_compra']

    def __str__(self):
        fornec = self.fornecedor.nome_fantasia if self.fornecedor else "Sem Fornecedor"
        return f"Compra #{self.id} - {fornec} (R$ {self.total}) [{self.get_status_display()}]"

    @property
    def total_itens_pedidos(self) -> Decimal:
        return sum((item.quantidade for item in self.itens.all()), Decimal('0.000'))

    @property
    def total_itens_recebidos(self) -> Decimal:
        return sum((item.quantidade_recebida for item in self.itens.all()), Decimal('0.000'))

    @property
    def total_itens_pendentes(self) -> Decimal:
        return sum((item.quantidade_pendente for item in self.itens.all()), Decimal('0.000'))

    @property
    def is_totalmente_recebida(self) -> bool:
        itens = list(self.itens.all())
        if not itens:
            return False
        return all(item.quantidade_recebida >= item.quantidade for item in itens)

    @property
    def status_badge_class(self) -> str:
        if self.status == 'CONCLUIDA':
            return 'bg-success'
        if self.status == 'PARCIAL':
            return 'bg-warning text-dark'
        if self.status == 'PENDENTE':
            return 'bg-info text-dark'
        if self.status == 'CANCELADA':
            return 'bg-danger'
        return 'bg-secondary'


class ItemCompra(TenantModelMixin):
    compra = models.ForeignKey(Compra, on_delete=models.CASCADE, related_name='itens')
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name='itens_compra')
    quantidade = models.DecimalField('Quantidade Pedida', max_digits=12, decimal_places=3)
    quantidade_recebida = models.DecimalField('Quantidade Recebida', max_digits=12, decimal_places=3, default=Decimal('0.000'))
    preco_custo_unitario = models.DecimalField('Custo Unitário (R$)', max_digits=12, decimal_places=2)
    subtotal = models.DecimalField('Subtotal (R$)', max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = 'Item de Compra'
        verbose_name_plural = 'Itens de Compra'

    def save(self, *args, **kwargs):
        self.subtotal = self.quantidade * self.preco_custo_unitario
        super().save(*args, **kwargs)

    @property
    def quantidade_pendente(self) -> Decimal:
        return max(Decimal('0.000'), self.quantidade - self.quantidade_recebida)

    @property
    def is_totalmente_recebido(self) -> bool:
        return self.quantidade_recebida >= self.quantidade

    @property
    def excedente(self) -> Decimal:
        return max(Decimal('0.000'), self.quantidade_recebida - self.quantidade)


class RecebimentoCompra(TenantModelMixin):
    compra = models.ForeignKey(Compra, on_delete=models.CASCADE, related_name='recebimentos')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='recebimentos_compras')
    data_recebimento = models.DateTimeField('Data/Hora do Recebimento', default=timezone.now)
    observacao = models.CharField('Observação / NF Entrega', max_length=255, blank=True)

    class Meta:
        verbose_name = 'Recebimento de Compra'
        verbose_name_plural = 'Recebimentos de Compras'
        ordering = ['-data_recebimento']

    def __str__(self):
        return f"Recebimento #{self.id} - Compra #{self.compra_id} ({self.data_recebimento.strftime('%d/%m/%Y %H:%M')})"


class ItemRecebimentoCompra(TenantModelMixin):
    recebimento = models.ForeignKey(RecebimentoCompra, on_delete=models.CASCADE, related_name='itens')
    item_compra = models.ForeignKey(ItemCompra, on_delete=models.CASCADE, related_name='entregas')
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name='itens_recebidos_compras')
    quantidade_recebida = models.DecimalField('Quantidade Deste Recebimento', max_digits=12, decimal_places=3)
    preco_custo = models.DecimalField('Custo Unitário Praticado (R$)', max_digits=12, decimal_places=2, default=0.00)

    class Meta:
        verbose_name = 'Item de Recebimento de Compra'
        verbose_name_plural = 'Itens de Recebimento de Compra'

    def __str__(self):
        return f"{self.produto.nome} - {self.quantidade_recebida} un (Recebimento #{self.recebimento_id})"
