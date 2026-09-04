from django.db import models
import threading

# Thread-local storage para armazenar a empresa ativa da requisição
_thread_locals = threading.local()

def get_current_tenant():
    return getattr(_thread_locals, 'tenant', None)

def set_current_tenant(tenant):
    _thread_locals.tenant = tenant

def clear_current_tenant():
    if hasattr(_thread_locals, 'tenant'):
        del _thread_locals.tenant


class TenantQuerySet(models.QuerySet):
    def for_tenant(self, tenant=None):
        tenant = tenant or get_current_tenant()
        if tenant:
            return self.filter(empresa=tenant)
        return self


class TenantManager(models.Manager):
    def get_queryset(self):
        qs = TenantQuerySet(self.model, using=self._db)
        tenant = get_current_tenant()
        if tenant:
            return qs.filter(empresa=tenant)
        return qs

    def unfiltered(self):
        return TenantQuerySet(self.model, using=self._db)


class TenantModelMixin(models.Model):
    """
    Model abstrato para garantir isolamento Multi-Tenant por empresa.
    Todos os dados do sistema pertencem a uma Empresa.
    """
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        related_name='%(class)s_set',
        verbose_name='Empresa'
    )
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    objects = TenantManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not hasattr(self, 'empresa_id') or not self.empresa_id:
            tenant = get_current_tenant()
            if tenant:
                self.empresa = tenant
        super().save(*args, **kwargs)


class AuditLog(models.Model):
    """
    Trilha de auditoria para operações críticas do sistema.
    Não herda de TenantModelMixin para evitar filtragem automática pelo TenantManager.
    """
    ACAO_CHOICES = [
        ('VENDA_CRIADA', 'Venda Criada'),
        ('VENDA_CANCELADA', 'Venda Cancelada'),
        ('DESCONTO_APLICADO', 'Desconto Aplicado'),
        ('CAIXA_ABERTO', 'Caixa Aberto'),
        ('CAIXA_FECHADO', 'Caixa Fechado'),
        ('SUPRIMENTO', 'Suprimento'),
        ('SANGRIA', 'Sangria'),
        ('DESPESA_CAIXA', 'Despesa Caixa'),
        ('AJUSTE_ESTOQUE', 'Ajuste de Estoque'),
        ('COMPRA_REGISTRADA', 'Compra Registrada'),
        ('FINANCEIRO_OPERACAO', 'Operação Financeira'),
        ('USUARIO_ALTERADO', 'Usuário Alterado'),
        ('PRODUTO_ALTERADO', 'Produto Alterado'),
        ('CLIENTE_CRIADO', 'Cliente Criado'),
        ('CLIENTE_ALTERADO', 'Cliente Alterado'),
        ('CREDIARIO_CONCEDIDO', 'Crediário Concedido'),
        ('CONTA_RECEBER_CRIADA', 'Conta a Receber Criada'),
        ('RECEBIMENTO_REGISTRADO', 'Recebimento Registrado'),
        ('RECEBIMENTO_CANCELADO', 'Recebimento Cancelado'),
        ('LIMITE_CREDITO_ALTERADO', 'Limite de Crédito Alterado'),
        ('IMPORTACAO_DADOS', 'Importação de Dados'),
        ('CONFIGURACAO_VISUAL_ALTERADA', 'Configuração Visual Alterada'),
        ('ATALHOS_PDV_ALTERADOS', 'Atalhos do PDV Alterados'),
    ]


    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        related_name='audit_logs',
        verbose_name='Empresa'
    )
    usuario = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='audit_logs',
        verbose_name='Usuário'
    )
    acao = models.CharField('Ação', max_length=30, choices=ACAO_CHOICES)
    entidade = models.CharField('Entidade', max_length=80, help_text='Ex: Venda, Produto, SessaoCaixa')
    entidade_id = models.CharField('ID da Entidade', max_length=50, blank=True)
    descricao = models.TextField('Descrição da Operação')
    dados_anteriores = models.JSONField('Dados Anteriores', default=dict, blank=True)
    dados_posteriores = models.JSONField('Dados Posteriores', default=dict, blank=True)
    motivo = models.TextField('Motivo', blank=True)
    ip_address = models.GenericIPAddressField('Endereço IP', null=True, blank=True)
    data_hora = models.DateTimeField('Data/Hora', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Registro de Auditoria'
        verbose_name_plural = 'Registros de Auditoria'
        ordering = ['-data_hora']

    def __str__(self):
        return f"[{self.data_hora:%d/%m/%Y %H:%M}] {self.get_acao_display()} - {self.entidade} #{self.entidade_id} ({self.usuario})"


class AuditService:
    """Serviço centralizado para registrar operações na trilha de auditoria."""

    @staticmethod
    def registrar(
        empresa,
        usuario,
        acao: str,
        entidade: str,
        entidade_id='',
        descricao: str = '',
        dados_anteriores: dict = None,
        dados_posteriores: dict = None,
        motivo: str = '',
        ip_address: str = None
    ) -> 'AuditLog':
        return AuditLog.objects.create(
            empresa=empresa,
            usuario=usuario,
            acao=acao,
            entidade=entidade,
            entidade_id=str(entidade_id),
            descricao=descricao,
            dados_anteriores=dados_anteriores or {},
            dados_posteriores=dados_posteriores or {},
            motivo=motivo,
            ip_address=ip_address
        )
