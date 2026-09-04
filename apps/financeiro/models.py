from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.conf import settings
from apps.core.models import TenantModelMixin
from apps.vendas.models import Venda
from apps.clientes.models import Cliente, Fornecedor
from apps.compras.models import Compra
from apps.caixas.models import SessaoCaixa

class CategoriaDespesa(TenantModelMixin):
    nome = models.CharField('Nome da Categoria', max_length=100)
    descricao = models.TextField('Descrição', blank=True)
    ativo = models.BooleanField('Ativo', default=True)

    class Meta:
        verbose_name = 'Categoria de Despesa'
        verbose_name_plural = 'Categorias de Despesas'
        unique_together = ['empresa', 'nome']
        ordering = ['nome']

    def __str__(self):
        return self.nome


class DespesaRecorrente(TenantModelMixin):
    PERIODICIDADE_CHOICES = [
        ('MENSAL', 'Mensal'),
        ('SEMANAL', 'Semanal'),
        ('ANUAL', 'Anual'),
    ]

    descricao = models.CharField('Descrição da Despesa Recorrente', max_length=200)
    categoria = models.ForeignKey(CategoriaDespesa, on_delete=models.SET_NULL, null=True, blank=True, related_name='despesas_recorrentes')
    fornecedor = models.ForeignKey(Fornecedor, on_delete=models.SET_NULL, null=True, blank=True, related_name='despesas_recorrentes')
    valor_estimado = models.DecimalField('Valor Fixo / Estimado (R$)', max_digits=12, decimal_places=2)
    periodicidade = models.CharField('Periodicidade', max_length=15, choices=PERIODICIDADE_CHOICES, default='MENSAL')
    dia_vencimento = models.PositiveSmallIntegerField('Dia do Vencimento (1-31)', default=10)
    data_inicio = models.DateField('Data de Início')
    data_fim = models.DateField('Data de Término (Opcional)', null=True, blank=True)
    ativo = models.BooleanField('Ativo', default=True)
    observacoes = models.TextField('Observações', blank=True)

    class Meta:
        verbose_name = 'Despesa Recorrente'
        verbose_name_plural = 'Despesas Recorrentes'
        ordering = ['dia_vencimento', 'descricao']

    def __str__(self):
        return f"{self.descricao} - R$ {self.valor_estimado} (Dia {self.dia_vencimento})"


class ContaReceber(TenantModelMixin):
    STATUS_CHOICES = [
        ('ABERTA', 'Aberta'),
        ('PARCIAL', 'Parcial'),
        ('QUITADA', 'Quitada'),
        ('CANCELADA', 'Cancelada'),
        ('PENDENTE', 'Pendente'), # Compatibilidade
        ('PAGO', 'Pago'),         # Compatibilidade
    ]

    venda = models.ForeignKey(Venda, on_delete=models.SET_NULL, null=True, blank=True, related_name='contas_receber')
    cliente = models.ForeignKey(Cliente, on_delete=models.SET_NULL, null=True, blank=True, related_name='contas_receber')
    descricao = models.CharField('Descrição / Histórico', max_length=255)
    valor = models.DecimalField('Valor Original (R$)', max_digits=12, decimal_places=2)
    valor_original = models.DecimalField('Valor Original Histórico (R$)', max_digits=12, decimal_places=2, default=0.00)
    valor_pago = models.DecimalField('Valor Pago (R$)', max_digits=12, decimal_places=2, default=0.00)
    data_vencimento = models.DateField('Data de Vencimento')
    data_pagamento = models.DateField('Data da Quitação', null=True, blank=True)
    status = models.CharField('Status', max_length=15, choices=STATUS_CHOICES, default='ABERTA')
    observacoes = models.TextField('Observações', blank=True)

    class Meta:
        verbose_name = 'Conta a Receber'
        verbose_name_plural = 'Contas a Receber'
        ordering = ['data_vencimento', '-id']

    def __str__(self):
        cli = self.cliente.nome if self.cliente else "Geral"
        return f"Receber #{self.id} - {cli} (Saldo R$ {self.saldo}) [{self.status_display_calculado}]"

    def save(self, *args, **kwargs):
        if not self.valor_original or self.valor_original == Decimal('0.00'):
            self.valor_original = self.valor
        super().save(*args, **kwargs)

    @property
    def saldo(self) -> Decimal:
        orig = Decimal(str(self.valor_original or self.valor))
        pago = Decimal(str(self.valor_pago or '0.00'))
        return max(Decimal('0.00'), orig - pago)

    @property
    def is_vencida(self) -> bool:
        if self.status in ['QUITADA', 'PAGO', 'CANCELADA']:
            return False
        return self.data_vencimento < timezone.now().date() and self.saldo > Decimal('0.00')

    @property
    def status_display_calculado(self) -> str:
        if self.status == 'CANCELADA':
            return 'Cancelada'
        if self.status in ['QUITADA', 'PAGO'] or self.saldo <= Decimal('0.00'):
            return 'Quitada'
        if self.is_vencida:
            return 'Vencida'
        if self.valor_pago > Decimal('0.00'):
            return 'Parcial'
        return 'Aberta'


class PagamentoContaReceber(TenantModelMixin):
    FORMA_CHOICES = [
        ('DINHEIRO', 'Dinheiro'),
        ('PIX', 'PIX'),
        ('CARTAO_DEBITO', 'Cartão Débito'),
        ('CARTAO_CREDITO', 'Cartão Crédito'),
    ]

    conta_receber = models.ForeignKey(ContaReceber, on_delete=models.CASCADE, related_name='pagamentos_recebidos')
    valor = models.DecimalField('Valor Recebido (R$)', max_digits=12, decimal_places=2)
    troco = models.DecimalField('Troco (R$)', max_digits=12, decimal_places=2, default=0.00)
    forma_pagamento = models.CharField('Forma de Pagamento', max_length=20, choices=FORMA_CHOICES, default='DINHEIRO')
    sessao_caixa = models.ForeignKey(SessaoCaixa, on_delete=models.SET_NULL, null=True, blank=True, related_name='recebimentos_crediario')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='recebimentos_realizados')
    data_hora = models.DateTimeField('Data/Hora', auto_now_add=True)
    observacao = models.CharField('Observação', max_length=255, blank=True)

    class Meta:
        verbose_name = 'Pagamento de Conta a Receber'
        verbose_name_plural = 'Pagamentos de Contas a Receber'
        ordering = ['-data_hora']

    @property
    def valor_efetivo(self) -> Decimal:
        return self.valor - self.troco

    def __str__(self):
        return f"Pagamento #{self.id} - R$ {self.valor_efetivo} ({self.forma_pagamento})"


class ContaPagar(TenantModelMixin):
    STATUS_CHOICES = [
        ('ABERTA', 'Aberta'),
        ('PARCIAL', 'Parcial'),
        ('PAGA', 'Paga'),
        ('CANCELADA', 'Cancelada'),
        ('PENDENTE', 'Pendente'), # Compatibilidade
        ('PAGO', 'Pago'),         # Compatibilidade
    ]

    compra = models.ForeignKey(Compra, on_delete=models.SET_NULL, null=True, blank=True, related_name='contas_pagar')
    fornecedor = models.ForeignKey(Fornecedor, on_delete=models.SET_NULL, null=True, blank=True, related_name='contas_pagar')
    categoria = models.ForeignKey(CategoriaDespesa, on_delete=models.SET_NULL, null=True, blank=True, related_name='contas_pagar')
    despesa_recorrente = models.ForeignKey(DespesaRecorrente, on_delete=models.SET_NULL, null=True, blank=True, related_name='ocorrencias')
    recorrente_competencia = models.CharField('Competência (ex: 2026-09)', max_length=15, blank=True)

    descricao = models.CharField('Descrição / Histórico', max_length=255)
    valor = models.DecimalField('Valor Original (R$)', max_digits=12, decimal_places=2)
    valor_original = models.DecimalField('Valor Original Histórico (R$)', max_digits=12, decimal_places=2, default=0.00)
    valor_pago = models.DecimalField('Valor Pago (R$)', max_digits=12, decimal_places=2, default=0.00)
    
    data_competencia = models.DateField('Data da Despesa / Competência', default=timezone.now)
    data_vencimento = models.DateField('Data de Vencimento')
    data_pagamento = models.DateField('Data do Pagamento', null=True, blank=True)
    forma_pagamento = models.CharField('Forma de Pagamento Principal', max_length=20, blank=True)
    
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='despesas_registradas')
    sessao_caixa = models.ForeignKey(SessaoCaixa, on_delete=models.SET_NULL, null=True, blank=True, related_name='despesas_pagas')
    
    status = models.CharField('Status', max_length=15, choices=STATUS_CHOICES, default='ABERTA')
    observacoes = models.TextField('Observações', blank=True)

    class Meta:
        verbose_name = 'Conta a Pagar / Despesa'
        verbose_name_plural = 'Contas a Pagar / Despesas'
        ordering = ['data_vencimento', '-id']

    def __str__(self):
        fornec = self.fornecedor.nome_fantasia if self.fornecedor else (self.categoria.nome if self.categoria else "Geral")
        return f"Pagar #{self.id} - {self.descricao} (Saldo R$ {self.saldo}) [{self.status_display_calculado}]"

    def save(self, *args, **kwargs):
        if not self.valor_original or self.valor_original == Decimal('0.00'):
            self.valor_original = self.valor
        super().save(*args, **kwargs)

    @property
    def saldo(self) -> Decimal:
        orig = Decimal(str(self.valor_original or self.valor))
        pago = Decimal(str(self.valor_pago or '0.00'))
        return max(Decimal('0.00'), orig - pago)

    @property
    def is_vencida(self) -> bool:
        if self.status in ['PAGA', 'PAGO', 'CANCELADA']:
            return False
        return self.data_vencimento < timezone.now().date() and self.saldo > Decimal('0.00')

    @property
    def status_display_calculado(self) -> str:
        if self.status == 'CANCELADA':
            return 'Cancelada'
        if self.status in ['PAGA', 'PAGO'] or self.saldo <= Decimal('0.00'):
            return 'Paga'
        if self.is_vencida:
            return 'Vencida'
        if self.valor_pago > Decimal('0.00'):
            return 'Parcial'
        return 'Aberta'


class PagamentoContaPagar(TenantModelMixin):
    FORMA_CHOICES = [
        ('DINHEIRO', 'Dinheiro (Caixa Físico)'),
        ('PIX', 'PIX'),
        ('CARTAO_DEBITO', 'Cartão Débito'),
        ('CARTAO_CREDITO', 'Cartão Crédito'),
        ('BOLETO', 'Boleto Bancário'),
        ('TRANSFERENCIA', 'Transferência Bancária'),
    ]

    conta_pagar = models.ForeignKey(ContaPagar, on_delete=models.CASCADE, related_name='pagamentos_detalhes')
    valor = models.DecimalField('Valor Pago (R$)', max_digits=12, decimal_places=2)
    forma_pagamento = models.CharField('Forma de Pagamento', max_length=20, choices=FORMA_CHOICES, default='DINHEIRO')
    sessao_caixa = models.ForeignKey(SessaoCaixa, on_delete=models.SET_NULL, null=True, blank=True, related_name='pagamentos_despesas')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='pagamentos_despesas_realizados')
    data_hora = models.DateTimeField('Data/Hora', auto_now_add=True)
    observacao = models.CharField('Observação', max_length=255, blank=True)

    class Meta:
        verbose_name = 'Pagamento de Despesa / Conta a Pagar'
        verbose_name_plural = 'Pagamentos de Despesas / Contas a Pagar'
        ordering = ['-data_hora']

    def __str__(self):
        return f"Pagamento Despesa #{self.id} - R$ {self.valor} ({self.forma_pagamento})"


class FluxoCaixa(TenantModelMixin):
    TIPO_CHOICES = [
        ('ENTRADA', 'Entrada'),
        ('SAIDA', 'Saída'),
    ]

    tipo = models.CharField('Tipo de Lançamento', max_length=10, choices=TIPO_CHOICES)
    categoria = models.CharField('Categoria Financeira', max_length=100)
    descricao = models.CharField('Descrição / Histórico', max_length=255)
    valor = models.DecimalField('Valor (R$)', max_digits=12, decimal_places=2)
    data_movimento = models.DateTimeField('Data do Movimento', auto_now_add=True)
    referencia_origem = models.CharField('Origem (Venda, Compra, Sangria, etc.)', max_length=100, blank=True)

    class Meta:
        verbose_name = 'Fluxo de Caixa'
        verbose_name_plural = 'Fluxos de Caixa'
        ordering = ['-data_movimento']

    def __str__(self):
        return f"{self.get_tipo_display()} R$ {self.valor} ({self.categoria} - {self.descricao})"
