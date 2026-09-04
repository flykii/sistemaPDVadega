from django.db import models
from django.core.exceptions import ValidationError
import re

HEX_COLOR_REGEX = re.compile(r'^#(?:[0-9a-fA-F]{3}){1,2}$')

def validar_hex_color(value):
    if not value or not HEX_COLOR_REGEX.match(value):
        raise ValidationError(f"'{value}' não é uma cor hexadecimal válida (ex: #2563EB ou #FFF).")


class Empresa(models.Model):
    razao_social = models.CharField('Razão Social', max_length=200)
    nome_fantasia = models.CharField('Nome Fantasia', max_length=200)
    cnpj = models.CharField('CNPJ', max_length=20, unique=True)
    inscricao_estadual = models.CharField('Inscrição Estadual', max_length=50, blank=True)
    telefone = models.CharField('Telefone', max_length=20, blank=True)
    whatsapp = models.CharField('WhatsApp', max_length=20, blank=True)
    email = models.EmailField('E-mail', blank=True)
    endereco = models.CharField('Endereço Completo', max_length=255, blank=True)
    cidade = models.CharField('Cidade', max_length=100, blank=True)
    estado = models.CharField('Estado (UF)', max_length=2, blank=True)
    logo = models.ImageField('Logo da Empresa', upload_to='logos/', null=True, blank=True)
    
    # Cores de Personalização do PDV (Legado compatível)
    cor_fundo_cabecalho = models.CharField('Cor Fundo Cabeçalho', max_length=20, default='#dc2626')
    cor_texto_cabecalho = models.CharField('Cor Texto Cabeçalho', max_length=20, default='#ffffff')
    cor_destaque = models.CharField('Cor de Destaque', max_length=20, default='#16a34a')
    cor_fundo_geral = models.CharField('Cor Fundo Geral', max_length=20, default='#f8fafc')
    cor_fundo_paineis = models.CharField('Cor Fundo Painéis', max_length=20, default='#ffffff')

    ativo = models.BooleanField('Ativo', default=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        verbose_name = 'Empresa'
        verbose_name_plural = 'Empresas'

    def __str__(self):
        return f"{self.nome_fantasia} ({self.cnpj})"

    def get_configuracao_visual(self):
        """Retorna ou cria a configuração visual associada com os padrões."""
        config, _ = ConfiguracaoVisual.objects.get_or_create(empresa=self)
        return config


class ConfiguracaoVisual(models.Model):
    """
    Configuração visual e temas personalizados por Empresa / Tenant.
    Utiliza CSS Variables centralizadas aplicadas dinamicamente nos templates.
    """
    empresa = models.OneToOneField(
        Empresa,
        on_delete=models.CASCADE,
        related_name='configuracao_visual',
        verbose_name='Empresa'
    )

    # 1. Identidade Visual
    nome_fantasia_exibicao = models.CharField('Nome Fantasia Exibido', max_length=200, blank=True)
    subtitulo_cabecalho = models.CharField('Subtítulo do Cabeçalho', max_length=200, blank=True, default='PDV Enterprise')
    logo = models.ImageField('Logo Customizado', upload_to='logos_custom/', null=True, blank=True)
    favicon = models.ImageField('Favicon', upload_to='favicons/', null=True, blank=True)

    # 2. Cores do Sistema
    cor_principal = models.CharField('Cor Principal', max_length=7, default='#2563eb', validators=[validar_hex_color])
    cor_secundaria = models.CharField('Cor Secundária', max_length=7, default='#475569', validators=[validar_hex_color])
    cor_destaque = models.CharField('Cor de Destaque', max_length=7, default='#f59e0b', validators=[validar_hex_color])
    cor_menu_sidebar = models.CharField('Cor Menu/Navbar', max_length=7, default='#0f172a', validators=[validar_hex_color])
    cor_fundo = models.CharField('Cor Plano de Fundo', max_length=7, default='#f8fafc', validators=[validar_hex_color])
    cor_cards = models.CharField('Cor dos Cards', max_length=7, default='#ffffff', validators=[validar_hex_color])
    cor_texto = models.CharField('Cor do Texto', max_length=7, default='#1e293b', validators=[validar_hex_color])
    cor_texto_secundario = models.CharField('Cor Texto Secundário', max_length=7, default='#64748b', validators=[validar_hex_color])
    cor_botoes = models.CharField('Cor dos Botões', max_length=7, default='#2563eb', validators=[validar_hex_color])
    cor_botoes_acao = models.CharField('Cor dos Botões de Ação', max_length=7, default='#10b981', validators=[validar_hex_color])
    cor_links = models.CharField('Cor dos Links', max_length=7, default='#2563eb', validators=[validar_hex_color])
    cor_sucesso = models.CharField('Cor Sucesso', max_length=7, default='#16a34a', validators=[validar_hex_color])
    cor_alerta = models.CharField('Cor Alerta', max_length=7, default='#d97706', validators=[validar_hex_color])
    cor_erro = models.CharField('Cor Erro', max_length=7, default='#dc2626', validators=[validar_hex_color])

    # 3. Cores e Tipografia do PDV
    cor_pdv_fundo = models.CharField('Cor Fundo PDV', max_length=7, default='#0f172a', validators=[validar_hex_color])
    cor_pdv_texto = models.CharField('Cor Texto PDV', max_length=7, default='#ffffff', validators=[validar_hex_color])
    cor_pdv_preco = models.CharField('Cor dos Preços', max_length=7, default='#22c55e', validators=[validar_hex_color])
    cor_pdv_total = models.CharField('Cor do Total Geral', max_length=7, default='#eab308', validators=[validar_hex_color])
    cor_pdv_botao_finalizar = models.CharField('Cor Botão Finalizar', max_length=7, default='#16a34a', validators=[validar_hex_color])
    cor_pdv_botao_cancelar = models.CharField('Cor Botão Cancelar', max_length=7, default='#dc2626', validators=[validar_hex_color])
    cor_pdv_botoes_pagamento = models.CharField('Cor Botões Pagamento', max_length=7, default='#3b82f6', validators=[validar_hex_color])
    cor_pdv_botao_pausar = models.CharField('Cor Botão Pausar Venda', max_length=7, default='#d97706', validators=[validar_hex_color])
    cor_pdv_botao_espera = models.CharField('Cor Botão Em Espera', max_length=7, default='#2563eb', validators=[validar_hex_color])
    cor_pdv_botao_divida = models.CharField('Cor Botão Receber Dívida', max_length=7, default='#7c3aed', validators=[validar_hex_color])

    tamanho_fonte_preco = models.CharField('Tamanho Fonte Preço', max_length=20, default='1.25rem')
    tamanho_fonte_total = models.CharField('Tamanho Fonte Total', max_length=20, default='2.0rem')
    tamanho_fonte_itens = models.CharField('Tamanho Fonte Itens', max_length=20, default='1.0rem')
    
    modo_layout = models.CharField(
        'Modo de Layout',
        max_length=20,
        choices=[('CONFORTAVEL', 'Confortável'), ('COMPACTO', 'Compacto')],
        default='CONFORTAVEL'
    )
    exibir_painel_produtos_rapidos = models.BooleanField('Exibir Produtos Rápidos no PDV', default=True)

    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        verbose_name = 'Configuração Visual'
        verbose_name_plural = 'Configurações Visuais'

    def __str__(self):
        return f"Configuração Visual - {self.empresa.nome_fantasia}"

    def clean(self):
        super().clean()
        campos_hex = [
            'cor_principal', 'cor_secundaria', 'cor_destaque', 'cor_menu_sidebar',
            'cor_fundo', 'cor_cards', 'cor_texto', 'cor_texto_secundario',
            'cor_botoes', 'cor_botoes_acao', 'cor_links', 'cor_sucesso',
            'cor_alerta', 'cor_erro', 'cor_pdv_fundo', 'cor_pdv_texto',
            'cor_pdv_preco', 'cor_pdv_total', 'cor_pdv_botao_finalizar',
            'cor_pdv_botao_cancelar', 'cor_pdv_botoes_pagamento',
            'cor_pdv_botao_pausar', 'cor_pdv_botao_espera', 'cor_pdv_botao_divida'
        ]
        for c in campos_hex:
            val = getattr(self, c)
            if val:
                val = val.strip()
                if not val.startswith('#'):
                    val = f"#{val}"
                setattr(self, c, val)
                validar_hex_color(val)

    def to_css_variables(self) -> str:
        """Gera bloco CSS de variáveis personalizadas injetadas no :root."""
        return f"""
        :root {{
            --cor-principal: {self.cor_principal};
            --cor-secundaria: {self.cor_secundaria};
            --cor-destaque: {self.cor_destaque};
            --cor-menu-sidebar: {self.cor_menu_sidebar};
            --cor-fundo: {self.cor_fundo};
            --cor-cards: {self.cor_cards};
            --cor-texto: {self.cor_texto};
            --cor-texto-secundario: {self.cor_texto_secundario};
            --cor-botoes: {self.cor_botoes};
            --cor-botoes-acao: {self.cor_botoes_acao};
            --cor-links: {self.cor_links};
            --cor-sucesso: {self.cor_sucesso};
            --cor-alerta: {self.cor_alerta};
            --cor-erro: {self.cor_erro};

            --cor-pdv-fundo: {self.cor_pdv_fundo};
            --cor-pdv-texto: {self.cor_pdv_texto};
            --cor-pdv-preco: {self.cor_pdv_preco};
            --cor-pdv-total: {self.cor_pdv_total};
            --cor-pdv-botao-finalizar: {self.cor_pdv_botao_finalizar};
            --cor-pdv-botao-cancelar: {self.cor_pdv_botao_cancelar};
            --cor-pdv-botoes-pagamento: {self.cor_pdv_botoes_pagamento};
            --cor-pdv-botao-pausar: {self.cor_pdv_botao_pausar};
            --cor-pdv-botao-espera: {self.cor_pdv_botao_espera};
            --cor-pdv-botao-divida: {self.cor_pdv_botao_divida};

            --pdv-fonte-preco: {self.tamanho_fonte_preco};
            --pdv-fonte-total: {self.tamanho_fonte_total};
            --pdv-fonte-itens: {self.tamanho_fonte_itens};
        }}
        """


class ConfiguracaoAtalhoPDV(models.Model):
    """
    Configuração de teclas de atalho do PDV por Empresa / Tenant.
    Permite customizar as teclas de acesso rápido às funções da frente de caixa.
    """
    FUNCOES_PADRAO = [
        ('FINALIZAR_COMPRA', 'Finalizar Compra / Pagamento', 'F5'),
        ('FOCAR_BUSCA', 'Buscar Produto / Focar Leitor', 'F2'),
        ('IDENTIFICAR_CLIENTE', 'Identificar / Selecionar Cliente', 'F4'),
        ('CANCELAR_FECHAR', 'Cancelar / Fechar Modais', 'Escape'),
    ]

    TECLAS_PERMITIDAS = [
        ('F1', 'F1'),
        ('F2', 'F2'),
        ('F3', 'F3'),
        ('F4', 'F4'),
        ('F5', 'F5'),
        ('F6', 'F6'),
        ('F7', 'F7'),
        ('F8', 'F8'),
        ('F9', 'F9'),
        ('F10', 'F10'),
        ('F11', 'F11'),
        ('F12', 'F12'),
        ('Escape', 'ESC'),
        ('Insert', 'INSERT'),
        ('Delete', 'DELETE'),
        ('Home', 'HOME'),
        ('End', 'END'),
        ('PageUp', 'PAGE UP'),
        ('PageDown', 'PAGE DOWN'),
    ]

    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name='atalhos_pdv',
        verbose_name='Empresa'
    )
    funcao_codigo = models.CharField('Código da Função', max_length=50)
    tecla = models.CharField('Tecla de Atalho', max_length=20)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        verbose_name = 'Atalho do PDV'
        verbose_name_plural = 'Atalhos do PDV'
        unique_together = [
            ('empresa', 'funcao_codigo'),
            ('empresa', 'tecla'),
        ]

    def __str__(self):
        return f"{self.empresa.nome_fantasia} - {self.funcao_codigo}: {self.tecla}"

    @classmethod
    def get_padroes_dict(cls) -> dict:
        return {f[0]: f[2] for f in cls.FUNCOES_PADRAO}

    @classmethod
    def get_atalhos_empresa(cls, empresa) -> dict:
        """
        Retorna dicionário {funcao_codigo: tecla} para a empresa,
        com fallback automático para os atalhos padrão do sistema.
        """
        atalhos = cls.get_padroes_dict()
        if empresa:
            customizados = cls.objects.filter(empresa=empresa)
            for c in customizados:
                if c.funcao_codigo in atalhos:
                    atalhos[c.funcao_codigo] = c.tecla
        return atalhos

    @classmethod
    def get_atalhos_detalhados(cls, empresa) -> list:
        """
        Retorna lista de dicionários para renderização na tabela de configuração:
        [{codigo, nome, tecla_atual, tecla_padrao, ...}]
        """
        mapa_atual = cls.get_atalhos_empresa(empresa)
        resultado = []
        for codigo, nome, padrao in cls.FUNCOES_PADRAO:
            resultado.append({
                'codigo': codigo,
                'nome': nome,
                'tecla_atual': mapa_atual.get(codigo, padrao),
                'tecla_padrao': padrao,
            })
        return resultado

    @classmethod
    def salvar_atalhos(cls, empresa, novos_atalhos: dict):
        """
        Valida e salva os atalhos da empresa de forma atômica.
        Verifica:
        - Teclas permitidas
        - Conflitos de teclas duplicadas
        """
        from django.db import transaction

        teclas_validas = {t[0].upper(): t[0] for t in cls.TECLAS_PERMITIDAS}
        teclas_validas['ESC'] = 'Escape'

        funcoes_validas = {f[0] for f in cls.FUNCOES_PADRAO}

        teclas_usadas = {}
        for func, tecla_raw in novos_atalhos.items():
            if func not in funcoes_validas:
                continue

            tecla_clean = tecla_raw.strip() if tecla_raw else ''
            tecla_norm = teclas_validas.get(tecla_clean.upper())
            if not tecla_norm:
                raise ValidationError(f"A tecla '{tecla_raw}' não é permitida para atalhos do PDV.")

            if tecla_norm in teclas_usadas:
                func_conflito = teclas_usadas[tecla_norm]
                nome_func_1 = next((f[1] for f in cls.FUNCOES_PADRAO if f[0] == func_conflito), func_conflito)
                nome_func_2 = next((f[1] for f in cls.FUNCOES_PADRAO if f[0] == func), func)
                raise ValidationError(
                    f"Este atalho já está sendo utilizado por outra função: '{nome_func_1}' e '{nome_func_2}'."
                )

            teclas_usadas[tecla_norm] = func

        with transaction.atomic():
            cls.objects.filter(empresa=empresa).delete()
            for func, tecla_norm in [(v, k) for k, v in teclas_usadas.items()]:
                cls.objects.create(
                    empresa=empresa,
                    funcao_codigo=func,
                    tecla=tecla_norm
                )

    @classmethod
    def restaurar_padroes(cls, empresa):
        """Remove customizações e devolve os atalhos originais."""
        cls.objects.filter(empresa=empresa).delete()


