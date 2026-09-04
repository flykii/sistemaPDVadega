from django.contrib.auth.models import AbstractUser
from django.db import models

class Usuario(AbstractUser):
    CARGO_CHOICES = [
        ('ADMIN', 'Administrador'),
        ('GERENTE', 'Gerente'),
        ('OPERADOR', 'Operador de Caixa'),
        ('ESTOQUISTA', 'Estoquista'),
        ('FINANCEIRO', 'Financeiro'),
    ]

    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        related_name='usuarios',
        verbose_name='Empresa',
        null=True,
        blank=True
    )
    cargo = models.CharField('Cargo', max_length=20, choices=CARGO_CHOICES, default='OPERADOR')
    pin_caixa = models.CharField('PIN de Caixa (4 a 6 dígitos)', max_length=10, blank=True)
    telefone = models.CharField('Telefone', max_length=20, blank=True)
    limite_desconto_pct = models.DecimalField(
        'Limite de Desconto (%)', max_digits=5, decimal_places=2, default=0.00,
        help_text='Percentual máximo de desconto que este usuário pode aplicar (0 = sem limite definido).'
    )

    class Meta:
        verbose_name = 'Usuário'
        verbose_name_plural = 'Usuários'

    def __str__(self):
        empresa_str = f" - {self.empresa.nome_fantasia}" if self.empresa else ""
        return f"{self.get_full_name() or self.username} ({self.get_cargo_display()}){empresa_str}"

    # =========================================================================
    # HELPERS DE AUTORIZAÇÃO POR CARGO
    # =========================================================================
    @property
    def is_admin(self):
        return self.cargo == 'ADMIN' or self.is_superuser

    @property
    def is_gerente(self):
        return self.cargo in ('ADMIN', 'GERENTE') or self.is_superuser

    @property
    def pode_cancelar_venda(self):
        return self.cargo in ('ADMIN', 'GERENTE') or self.is_superuser

    @property
    def pode_autorizar_desconto(self):
        return self.cargo in ('ADMIN', 'GERENTE') or self.is_superuser

    @property
    def pode_operar_caixa(self):
        return self.cargo in ('ADMIN', 'GERENTE', 'OPERADOR') or self.is_superuser

    @property
    def pode_ajustar_estoque(self):
        return self.cargo in ('ADMIN', 'GERENTE', 'ESTOQUISTA') or self.is_superuser

    @property
    def pode_operar_financeiro(self):
        return self.cargo in ('ADMIN', 'GERENTE', 'FINANCEIRO') or self.is_superuser

    @property
    def pode_gerenciar_usuarios(self):
        return self.cargo == 'ADMIN' or self.is_superuser

    @property
    def pode_visualizar_relatorios(self):
        return self.cargo in ('ADMIN', 'GERENTE', 'FINANCEIRO') or self.is_superuser

    @property
    def pode_visualizar_auditoria(self):
        return self.cargo in ('ADMIN', 'GERENTE') or self.is_superuser
