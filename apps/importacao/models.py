from django.db import models
from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario


class HistoricoImportacao(models.Model):
    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('PROCESSADO', 'Processado com Sucesso'),
        ('PROCESSADO_COM_ERROS', 'Processado com Erros'),
        ('FALHA', 'Falha Crítica'),
    ]

    TIPO_ENTIDADE_CHOICES = [
        ('PRODUTOS', 'Produtos'),
        ('CLIENTES', 'Clientes'),
        ('CATEGORIAS', 'Categorias'),
        ('FORNECEDORES', 'Fornecedores'),
        ('MISTO', 'Multi-Entidade / Estrutura Hierárquica'),
    ]

    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name='historico_importacoes',
        verbose_name='Empresa'
    )
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='importacoes_realizadas',
        verbose_name='Usuário'
    )
    nome_arquivo = models.CharField('Nome do Arquivo', max_length=255)
    tamanho_bytes = models.BigIntegerField('Tamanho em Bytes', default=0)
    hash_arquivo = models.CharField('Hash SHA256 do Arquivo', max_length=64, blank=True, db_index=True)
    tipo_entidade = models.CharField('Tipo de Entidade', max_length=50, choices=TIPO_ENTIDADE_CHOICES, default='PRODUTOS')
    
    total_registros = models.IntegerField('Total de Registros', default=0)
    quantidade_criada = models.IntegerField('Criados', default=0)
    quantidade_atualizada = models.IntegerField('Atualizados', default=0)
    quantidade_rejeitada = models.IntegerField('Rejeitados', default=0)
    quantidade_ignorada = models.IntegerField('Ignorados', default=0)
    
    mapeamento_utilizado = models.JSONField('Mapeamento de Campos Utilizado', default=dict, blank=True)
    detalhes_erros = models.JSONField('Relatório Detalhado de Erros', default=list, blank=True)
    status = models.CharField('Status da Importação', max_length=30, choices=STATUS_CHOICES, default='PENDENTE')
    mensagem_status = models.TextField('Mensagem de Status', blank=True)
    
    data_hora = models.DateTimeField('Data e Hora', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Histórico de Importação'
        verbose_name_plural = 'Histórico de Importações'
        ordering = ['-data_hora']

    def __str__(self):
        return f"Importação #{self.id} - {self.nome_arquivo} ({self.get_status_display()}) - {self.empresa.nome_fantasia}"
