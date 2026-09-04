from decimal import Decimal
from django.db import models
from apps.core.models import TenantModelMixin

class Cliente(TenantModelMixin):
    nome = models.CharField('Nome / Razão Social', max_length=200)
    cpf_cnpj = models.CharField('CPF/CNPJ', max_length=20, blank=True, db_index=True)
    telefone = models.CharField('Telefone', max_length=20, blank=True)
    celular = models.CharField('Celular / WhatsApp', max_length=20, blank=True)
    email = models.EmailField('E-mail', blank=True)
    
    endereco = models.CharField('Endereço', max_length=255, blank=True)
    numero = models.CharField('Número', max_length=20, blank=True)
    complemento = models.CharField('Complemento', max_length=100, blank=True)
    bairro = models.CharField('Bairro', max_length=100, blank=True)
    cidade = models.CharField('Cidade', max_length=100, blank=True)
    estado = models.CharField('Estado (UF)', max_length=2, blank=True)
    cep = models.CharField('CEP', max_length=10, blank=True)

    limite_credito = models.DecimalField('Limite de Crédito (R$)', max_digits=12, decimal_places=2, default=0.00)
    saldo_devedor = models.DecimalField('Saldo Devedor (R$)', max_digits=12, decimal_places=2, default=0.00)
    observacoes = models.TextField('Observações', blank=True)
    ativo = models.BooleanField('Ativo', default=True)

    class Meta:
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'
        ordering = ['nome']

    def __str__(self):
        doc = f" ({self.cpf_cnpj})" if self.cpf_cnpj else ""
        return f"{self.nome}{doc}"

    @property
    def credito_disponivel(self) -> Decimal:
        """Calcula o saldo de crédito restante para novas compras a prazo."""
        if self.limite_credito <= Decimal('0.00'):
            return Decimal('0.00')
        return max(Decimal('0.00'), self.limite_credito - self.saldo_devedor)

    @property
    def percentual_utilizado(self) -> float:
        if self.limite_credito <= Decimal('0.00'):
            return 0.0
        return float(min(100.0, float((self.saldo_devedor / self.limite_credito) * 100)))

    @property
    def total_contas_pendentes(self) -> Decimal:
        contas = self.contas_receber.filter(status__in=['ABERTA', 'PENDENTE', 'PARCIAL'])
        return sum((c.saldo for c in contas), Decimal('0.00'))


class Fornecedor(TenantModelMixin):
    razao_social = models.CharField('Razão Social', max_length=200)
    nome_fantasia = models.CharField('Nome Fantasia', max_length=200, blank=True)
    cnpj = models.CharField('CNPJ', max_length=20, blank=True)
    telefone = models.CharField('Telefone', max_length=20, blank=True)
    email = models.EmailField('E-mail', blank=True)
    endereco = models.CharField('Endereço', max_length=255, blank=True)
    contato_nome = models.CharField('Nome do Contato', max_length=100, blank=True)
    observacoes = models.TextField('Observações', blank=True)
    ativo = models.BooleanField('Ativo', default=True)

    class Meta:
        verbose_name = 'Fornecedor'
        verbose_name_plural = 'Fornecedores'
        ordering = ['nome_fantasia', 'razao_social']

    def __str__(self):
        return f"{self.nome_fantasia or self.razao_social}"
