from decimal import Decimal
from django.db import models
from apps.core.models import TenantModelMixin
from django.conf import settings

class Caixa(TenantModelMixin):
    STATUS_CHOICES = [
        ('ABERTO', 'Aberto'),
        ('FECHADO', 'Fechado'),
    ]

    nome = models.CharField('Nome do Caixa', max_length=100)
    codigo_identificador = models.CharField('Código Identificador', max_length=50)
    status = models.CharField('Status', max_length=10, choices=STATUS_CHOICES, default='FECHADO')
    ativo = models.BooleanField('Ativo', default=True)

    class Meta:
        verbose_name = 'Caixa'
        verbose_name_plural = 'Caixas'
        unique_together = ['empresa', 'codigo_identificador']

    def __str__(self):
        return f"{self.nome} [{self.codigo_identificador}] ({self.get_status_display()})"


class SessaoCaixa(TenantModelMixin):
    STATUS_CHOICES = [
        ('ABERTA', 'Aberta'),
        ('FECHADA', 'Fechada'),
    ]

    caixa = models.ForeignKey(Caixa, on_delete=models.PROTECT, related_name='sessoes')
    operador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='sessoes_caixa')
    nome_operador = models.CharField('Nome / Apelido do Operador', max_length=100, blank=True)
    data_abertura = models.DateTimeField('Data/Hora Abertura', auto_now_add=True)
    saldo_inicial = models.DecimalField('Saldo Inicial (R$)', max_digits=12, decimal_places=2, default=0.00)
    data_fechamento = models.DateTimeField('Data/Hora Fechamento', null=True, blank=True)
    saldo_final_calculado = models.DecimalField('Saldo Final Calculado (R$)', max_digits=12, decimal_places=2, null=True, blank=True)
    saldo_final_informado = models.DecimalField('Saldo Final Informado (R$)', max_digits=12, decimal_places=2, null=True, blank=True)
    diferenca = models.DecimalField('Diferença (R$)', max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField('Status', max_length=10, choices=STATUS_CHOICES, default='ABERTA')
    observacoes = models.TextField('Observações de Fechamento', blank=True)

    class Meta:
        verbose_name = 'Sessão de Caixa'
        verbose_name_plural = 'Sessões de Caixa'
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'caixa'],
                condition=models.Q(status='ABERTA'),
                name='unique_sessao_aberta_por_caixa'
            )
        ]

    def __str__(self):
        op = self.nome_operador or self.operador.get_full_name() or self.operador.username
        return f"Sessão #{self.id} - {self.caixa.nome} ({op})"

    @property
    def nome_operador_exibicao(self):
        return self.nome_operador or self.operador.get_full_name() or self.operador.username

    @property
    def total_vendas(self) -> Decimal:
        vendas = self.vendas.filter(status='CONCLUIDA')
        return sum((v.total for v in vendas), Decimal('0.00'))

    @property
    def qtd_vendas(self) -> int:
        return self.vendas.filter(status='CONCLUIDA').count()

    @property
    def total_vendas_dinheiro(self) -> Decimal:
        from apps.vendas.models import PagamentoVenda
        pags = PagamentoVenda.objects.filter(venda__sessao_caixa=self, venda__status='CONCLUIDA', forma_pagamento='DINHEIRO')
        return sum(((p.valor - p.troco) for p in pags), Decimal('0.00'))

    @property
    def total_vendas_pix(self) -> Decimal:
        from apps.vendas.models import PagamentoVenda
        pags = PagamentoVenda.objects.filter(venda__sessao_caixa=self, venda__status='CONCLUIDA', forma_pagamento='PIX')
        return sum((p.valor for p in pags), Decimal('0.00'))

    @property
    def total_vendas_debito(self) -> Decimal:
        from apps.vendas.models import PagamentoVenda
        pags = PagamentoVenda.objects.filter(venda__sessao_caixa=self, venda__status='CONCLUIDA', forma_pagamento='CARTAO_DEBITO')
        return sum((p.valor for p in pags), Decimal('0.00'))

    @property
    def total_vendas_credito(self) -> Decimal:
        from apps.vendas.models import PagamentoVenda
        pags = PagamentoVenda.objects.filter(venda__sessao_caixa=self, venda__status='CONCLUIDA', forma_pagamento='CARTAO_CREDITO')
        return sum((p.valor for p in pags), Decimal('0.00'))

    @property
    def total_vendas_crediario(self) -> Decimal:
        from apps.vendas.models import PagamentoVenda
        pags = PagamentoVenda.objects.filter(venda__sessao_caixa=self, venda__status='CONCLUIDA', forma_pagamento='CREDIARIO')
        return sum((p.valor for p in pags), Decimal('0.00'))

    @property
    def total_lucro(self) -> Decimal:
        vendas = self.vendas.filter(status='CONCLUIDA')
        return sum((v.lucro_total for v in vendas), Decimal('0.00'))

    @property
    def total_sangrias(self) -> Decimal:
        return sum((m.valor for m in self.movimentacoes.filter(tipo='SANGRIA')), Decimal('0.00'))

    @property
    def total_suprimentos(self) -> Decimal:
        return sum((m.valor for m in self.movimentacoes.filter(tipo='SUPRIMENTO')), Decimal('0.00'))

    @property
    def total_despesas(self) -> Decimal:
        return sum((m.valor for m in self.movimentacoes.filter(tipo='DESPESA')), Decimal('0.00'))

    @property
    def total_estornos(self) -> Decimal:
        return sum((m.valor for m in self.movimentacoes.filter(tipo='ESTORNO')), Decimal('0.00'))

    @property
    def saldo_esperado(self) -> Decimal:
        """Calcula o dinheiro físico esperado na gaveta do caixa."""
        return (
            self.saldo_inicial
            + self.total_suprimentos
            - self.total_sangrias
            - self.total_despesas
            + self.total_estornos
            + self.total_vendas_dinheiro
        )

    @property
    def saldo_atual(self) -> Decimal:
        return self.saldo_esperado

    @property
    def status_fechamento_display(self) -> str:
        if self.status == 'ABERTA':
            return 'Em Aberto'
        if self.diferenca is None or self.diferenca == Decimal('0.00'):
            return 'Fechado sem Diferença'
        elif self.diferenca > Decimal('0.00'):
            return f'Sobra de R$ {self.diferenca:.2f}'
        else:
            return f'Falta de R$ {abs(self.diferenca):.2f}'


class MovimentacaoCaixa(TenantModelMixin):
    TIPO_CHOICES = [
        ('SUPRIMENTO', 'Suprimento (Aporte)'),
        ('SANGRIA', 'Sangria (Retirada)'),
        ('DESPESA', 'Despesa Paga pelo Caixa'),
        ('ESTORNO', 'Estorno'),
    ]

    sessao_caixa = models.ForeignKey(SessaoCaixa, on_delete=models.CASCADE, related_name='movimentacoes')
    tipo = models.CharField('Tipo de Movimentação', max_length=15, choices=TIPO_CHOICES)
    valor = models.DecimalField('Valor (R$)', max_digits=12, decimal_places=2)
    motivo = models.CharField('Motivo / Descrição', max_length=255)
    operador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    data_hora = models.DateTimeField('Data/Hora', auto_now_add=True)

    class Meta:
        verbose_name = 'Movimentação de Caixa'
        verbose_name_plural = 'Movimentações de Caixa'

    def __str__(self):
        return f"{self.get_tipo_display()} R$ {self.valor} ({self.motivo})"
