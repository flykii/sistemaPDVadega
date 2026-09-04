"""
ETAPA 10 — Testes de Hardening, Segurança, Permissões, Multi-Tenancy e Concorrência.
Cobre todos os 25 cenários obrigatórios de testes da Etapa 10.
"""
from decimal import Decimal
import uuid
from django.test import TestCase, Client
from django.urls import reverse
from django.conf import settings

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.caixas.models import Caixa, SessaoCaixa, MovimentacaoCaixa
from apps.caixas.services import CashService
from apps.produtos.models import Produto, Categoria, MovimentacaoEstoque
from apps.produtos.services import StockService
from apps.clientes.models import Cliente, Fornecedor
from apps.vendas.models import Venda, ItemVenda, PagamentoVenda
from apps.vendas.services import SaleService
from apps.financeiro.models import ContaReceber, ContaPagar, FluxoCaixa, DespesaRecorrente
from apps.financeiro.services import FinancialService
from apps.core.models import AuditLog, AuditService


class Etapa10HardeningTestCase(TestCase):
    """Suíte abrangente de segurança, multi-tenancy, concorrência e autorização."""

    def setUp(self):
        # 1. Empresa A (Tenant Principal)
        self.empresa_a = Empresa.objects.create(
            razao_social="Empresa Alpha LTDA",
            nome_fantasia="Loja Alpha",
            cnpj="11.111.111/0001-11"
        )
        # 2. Empresa B (Tenant Secundário para testes cross-tenant)
        self.empresa_b = Empresa.objects.create(
            razao_social="Empresa Beta Comercio LTDA",
            nome_fantasia="Loja Beta",
            cnpj="22.222.222/0001-22"
        )

        # Usuários da Empresa A
        self.admin_a = Usuario.objects.create_user(
            username='admin_a', password='password123',
            empresa=self.empresa_a, cargo='ADMIN'
        )
        self.gerente_a = Usuario.objects.create_user(
            username='gerente_a', password='password123',
            empresa=self.empresa_a, cargo='GERENTE'
        )
        self.operador_a1 = Usuario.objects.create_user(
            username='operador_a1', password='password123',
            empresa=self.empresa_a, cargo='OPERADOR'
        )
        self.operador_a2 = Usuario.objects.create_user(
            username='operador_a2', password='password123',
            empresa=self.empresa_a, cargo='OPERADOR'
        )
        self.estoquista_a = Usuario.objects.create_user(
            username='estoquista_a', password='password123',
            empresa=self.empresa_a, cargo='ESTOQUISTA'
        )
        self.financeiro_a = Usuario.objects.create_user(
            username='financeiro_a', password='password123',
            empresa=self.empresa_a, cargo='FINANCEIRO'
        )

        # Usuários da Empresa B
        self.admin_b = Usuario.objects.create_user(
            username='admin_b', password='password123',
            empresa=self.empresa_b, cargo='ADMIN'
        )
        self.operador_b = Usuario.objects.create_user(
            username='operador_b', password='password123',
            empresa=self.empresa_b, cargo='OPERADOR'
        )

        # Caixas
        self.caixa_a = Caixa.objects.create(
            empresa=self.empresa_a, nome="Caixa Alpha 01", codigo_identificador="CX-A1"
        )
        self.caixa_b = Caixa.objects.create(
            empresa=self.empresa_b, nome="Caixa Beta 01", codigo_identificador="CX-B1"
        )

        # Sessão Caixa A1
        self.sessao_a = CashService.abrir_caixa(
            caixa=self.caixa_a, operador=self.operador_a1,
            saldo_inicial=Decimal('150.00'), nome_operador="Operador Alpha"
        )

        # Produtos
        self.produto_a = Produto.objects.create(
            empresa=self.empresa_a, nome="Produto Alpha",
            codigo_barras="7890001", preco_custo=Decimal('10.00'),
            preco_venda=Decimal('25.00'), estoque_atual=Decimal('40.000'),
            controle_estoque=True
        )
        self.produto_b = Produto.objects.create(
            empresa=self.empresa_b, nome="Produto Beta",
            codigo_barras="7890002", preco_custo=Decimal('12.00'),
            preco_venda=Decimal('30.00'), estoque_atual=Decimal('20.000'),
            controle_estoque=True
        )

        # Clientes
        self.cliente_a = Cliente.objects.create(
            empresa=self.empresa_a, nome="Cliente Alpha",
            cpf_cnpj="11122233344", limite_credito=Decimal('300.00')
        )
        self.cliente_b = Cliente.objects.create(
            empresa=self.empresa_b, nome="Cliente Beta",
            cpf_cnpj="55566677788", limite_credito=Decimal('500.00')
        )

    # =========================================================================
    # 1. ACESSO NÃO AUTENTICADO
    # =========================================================================
    def test_01_acesso_nao_autenticado_redireciona_login(self):
        """Requisição não autenticada para rotas protegidas deve redirecionar para /login/."""
        rotas = [
            '/',
            '/caixas/',
            '/produtos/',
            '/clientes/',
            '/compras/',
            '/financeiro/despesas/',
            '/relatorios/',
            '/relatorios/auditoria/',
            '/configuracoes/',
        ]
        for rota in rotas:
            resp = self.client.get(rota)
            self.assertEqual(resp.status_code, 302, f"Rota {rota} deveria redirecionar")
            self.assertIn('/login/', resp.url)

    # =========================================================================
    # 2. ACESSO DE USUÁRIO DE EMPRESA DIFERENTE (CROSS-TENANT)
    # =========================================================================
    def test_02_usuario_empresa_b_nao_acessa_produto_empresa_a(self):
        """Usuário da Empresa B não pode visualizar nem editar produto da Empresa A."""
        self.client.login(username='admin_b', password='password123')
        resp = self.client.get(f'/produtos/editar/{self.produto_a.id}/')
        self.assertEqual(resp.status_code, 404)

    # =========================================================================
    # 3. OPERADOR TENTANDO CANCELAR VENDA (403)
    # =========================================================================
    def test_03_operador_tentando_cancelar_venda_bloqueado(self):
        """Operador não tem permissão para cancelar venda (retorna 403)."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a1,
            itens_data=[{'produto_id': self.produto_a.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('25.00'), 'troco': Decimal('0.00')}]
        )
        self.client.login(username='operador_a1', password='password123')
        resp = self.client.post(f'/vendas/{venda.id}/cancelar/', {'motivo': 'Tentativa sem permissão'})
        self.assertEqual(resp.status_code, 403)

    # =========================================================================
    # 4. USUÁRIO AUTORIZADO CANCELANDO VENDA COM SUCESSO
    # =========================================================================
    def test_04_admin_ou_gerente_cancela_venda_sucesso(self):
        """Gerente ou Admin pode cancelar venda informando motivo válido."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a1,
            itens_data=[{'produto_id': self.produto_a.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('25.00'), 'troco': Decimal('0.00')}]
        )
        self.client.login(username='gerente_a', password='password123')
        resp = self.client.post(f'/vendas/{venda.id}/cancelar/', {'motivo': 'Cliente desistiu da compra'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        venda.refresh_from_db()
        self.assertEqual(venda.status, 'CANCELADA')

    # =========================================================================
    # 5. OPERADOR TENTANDO FECHAR CAIXA DE OUTRO OPERADOR (403)
    # =========================================================================
    def test_05_operador_tentando_fechar_caixa_de_outro_operador(self):
        """Operador A2 não pode fechar a sessão de caixa do Operador A1."""
        self.client.login(username='operador_a2', password='password123')
        resp = self.client.post(f'/caixas/fechar/{self.sessao_a.id}/', {
            'saldo_final_informado': '150.00'
        })
        self.assertEqual(resp.status_code, 403)

    # =========================================================================
    # 6. USUÁRIO SEM PERMISSÃO ACESSANDO URL DIRETAMENTE (AUDITORIA / CONFIG)
    # =========================================================================
    def test_06_operador_acessando_auditoria_direto_bloqueado(self):
        """Operador acessando /relatorios/auditoria/ diretamente recebe 403."""
        self.client.login(username='operador_a1', password='password123')
        resp = self.client.get('/relatorios/auditoria/')
        self.assertEqual(resp.status_code, 403)

    def test_06b_operador_acessando_configuracoes_direto_bloqueado(self):
        """Operador acessando /configuracoes/ diretamente recebe 403."""
        self.client.login(username='operador_a1', password='password123')
        resp = self.client.get('/configuracoes/')
        self.assertEqual(resp.status_code, 403)

    # =========================================================================
    # 7. ESTOQUISTA TENTANDO OPERAÇÃO FINANCEIRA (403)
    # =========================================================================
    def test_07_estoquista_tentando_operacao_financeira_bloqueado(self):
        """Estoquista não pode acessar gestão de contas a pagar nem registrar despesas."""
        self.client.login(username='estoquista_a', password='password123')
        resp = self.client.get('/financeiro/despesas/')
        self.assertEqual(resp.status_code, 403)

        resp_post = self.client.post('/financeiro/despesas/nova/', {
            'descricao': 'Despesa Indevida',
            'valor': '100.00'
        })
        self.assertEqual(resp_post.status_code, 403)

    # =========================================================================
    # 8. FINANCEIRO TENTANDO AJUSTAR ESTOQUE (403)
    # =========================================================================
    def test_08_financeiro_tentando_ajustar_estoque_bloqueado(self):
        """Usuário Financeiro não pode ajustar estoque de produtos."""
        self.client.login(username='financeiro_a', password='password123')
        resp = self.client.post(f'/produtos/ajuste/{self.produto_a.id}/', {
            'tipo': 'NOVO_SALDO',
            'novo_saldo': '100.000',
            'motivo': 'Tentativa indevida'
        })
        self.assertEqual(resp.status_code, 403)

    # =========================================================================
    # 9. DUPLO ENVIO DE VENDA (IDEMPOTÊNCIA COM OFFLINE_UUID)
    # =========================================================================
    def test_09_duplo_envio_venda_idempotente(self):
        """Dois envios da mesma venda com mesmo offline_uuid retornam a mesma venda sem duplicar."""
        unique_uuid = str(uuid.uuid4())
        venda1 = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a1,
            itens_data=[{'produto_id': self.produto_a.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('25.00'), 'troco': Decimal('0.00')}],
            offline_uuid=unique_uuid
        )
        venda2 = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a1,
            itens_data=[{'produto_id': self.produto_a.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('25.00'), 'troco': Decimal('0.00')}],
            offline_uuid=unique_uuid
        )
        self.assertEqual(venda1.id, venda2.id)
        self.assertEqual(Venda.objects.filter(empresa=self.empresa_a, offline_uuid=unique_uuid).count(), 1)

    # =========================================================================
    # 10. DUPLO CANCELAMENTO BLOQUEADO
    # =========================================================================
    def test_10_duplo_cancelamento_bloqueado(self):
        """Tentativa de segundo cancelamento deve lançar ValueError no backend."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a1,
            itens_data=[{'produto_id': self.produto_a.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('25.00'), 'troco': Decimal('0.00')}]
        )
        SaleService.cancelar_venda(venda.id, self.empresa_a, self.admin_a, "Primeiro cancelamento")
        with self.assertRaises(ValueError) as ctx:
            SaleService.cancelar_venda(venda.id, self.empresa_a, self.admin_a, "Segundo cancelamento")
        self.assertIn("já foi cancelada", str(ctx.exception))

    # =========================================================================
    # 11. DUPLA SANGRIA (VALIDAÇÃO DE SALDO DISPONÍVEL)
    # =========================================================================
    def test_11_sangria_excedente_saldo_rejeitada(self):
        """Sangria maior que o saldo disponível na gaveta deve ser rejeitada."""
        # Saldo inicial é R$ 150.00
        CashService.registrar_movimentacao(
            sessao=self.sessao_a, tipo='SANGRIA',
            valor=Decimal('100.00'), motivo='Sangria 1',
            operador=self.operador_a1
        )
        # Saldo restante é R$ 50.00. Tentativa de retirar R$ 80.00 deve falhar:
        with self.assertRaises(ValueError) as ctx:
            CashService.registrar_movimentacao(
                sessao=self.sessao_a, tipo='SANGRIA',
                valor=Decimal('80.00'), motivo='Sangria 2 excessiva',
                operador=self.operador_a1
            )
        self.assertIn("Saldo insuficiente", str(ctx.exception))

    # =========================================================================
    # 12. DUPLO FECHAMENTO DE CAIXA
    # =========================================================================
    def test_12_duplo_fechamento_caixa_bloqueado(self):
        """Tentar fechar sessão de caixa já fechada deve lançar ValueError."""
        CashService.fechar_caixa(self.sessao_a, Decimal('150.00'), "Fechamento regular")
        with self.assertRaises(ValueError) as ctx:
            CashService.fechar_caixa(self.sessao_a, Decimal('150.00'), "Fechamento duplicado")
        self.assertIn("já se encontra fechada", str(ctx.exception))

    # =========================================================================
    # 13. VENDA CANCELADA FORA DO TENANT
    # =========================================================================
    def test_13_cancelar_venda_outro_tenant_bloqueado(self):
        """Admin da Empresa B não pode cancelar venda pertencente à Empresa A."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a1,
            itens_data=[{'produto_id': self.produto_a.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('25.00'), 'troco': Decimal('0.00')}]
        )
        with self.assertRaises(ValueError) as ctx:
            SaleService.cancelar_venda(venda.id, self.empresa_b, self.admin_b, "Tentativa cross-tenant")
        self.assertIn("não encontrada", str(ctx.exception).lower())

    # =========================================================================
    # 14. PRODUTO FORA DO TENANT
    # =========================================================================
    def test_14_produto_outro_tenant_nao_listado(self):
        """Produtos da Empresa B não devem aparecer nas listagens da Empresa A."""
        self.client.login(username='admin_a', password='password123')
        resp = self.client.get('/produtos/')
        self.assertContains(resp, "Produto Alpha")
        self.assertNotContains(resp, "Produto Beta")

    # =========================================================================
    # 15. CAIXA FORA DO TENANT
    # =========================================================================
    def test_15_caixa_outro_tenant_nao_acessivel(self):
        """Caixas da Empresa B não são acessíveis pela Empresa A."""
        self.client.login(username='admin_a', password='password123')
        resp = self.client.get(f'/caixas/abrir/{self.caixa_b.id}/')
        self.assertEqual(resp.status_code, 404)

    # =========================================================================
    # 16. AUDITORIA FORA DO TENANT
    # =========================================================================
    def test_16_auditoria_isolada_por_tenant(self):
        """Logs de auditoria da Empresa A não aparecem para o Admin da Empresa B."""
        AuditService.registrar(
            empresa=self.empresa_a, usuario=self.admin_a,
            acao='CAIXA_ABERTO', entidade='Caixa',
            entidade_id=self.caixa_a.id, descricao='Abertura Alpha'
        )
        self.client.login(username='admin_b', password='password123')
        resp = self.client.get('/relatorios/auditoria/')
        self.assertNotContains(resp, "Abertura Alpha")

    # =========================================================================
    # 17. DASHBOARD ISOLADO POR EMPRESA
    # =========================================================================
    def test_17_dashboard_isolado_por_empresa(self):
        """Dashboard da Empresa B não inclui faturamento da Empresa A."""
        SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a1,
            itens_data=[{'produto_id': self.produto_a.id, 'quantidade': 2}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('50.00'), 'troco': Decimal('0.00')}]
        )
        self.client.login(username='admin_b', password='password123')
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        # Faturamento no dashboard de B deve ser R$ 0,00
        self.assertContains(resp, "0,00")

    # =========================================================================
    # 18. RELATÓRIOS ISOLADOS POR EMPRESA
    # =========================================================================
    def test_18_relatorio_vendas_isolado_por_empresa(self):
        """Relatório de vendas da Empresa B não lista vendas da Empresa A."""
        venda_a = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a1,
            itens_data=[{'produto_id': self.produto_a.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('25.00'), 'troco': Decimal('0.00')}]
        )
        self.client.login(username='admin_b', password='password123')
        resp = self.client.get('/relatorios/vendas/')
        self.assertNotContains(resp, venda_a.codigo_venda)

    # =========================================================================
    # 19. MENSAGENS AMIGÁVEIS PARA ERROS ESPERADOS
    # =========================================================================
    def test_19_erro_amigavel_estoque_insuficiente(self):
        """Tentativa de vender produto sem estoque retorna mensagem clara e compreensível."""
        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa_a, sessao_caixa=self.sessao_a,
                operador=self.operador_a1,
                itens_data=[{'produto_id': self.produto_a.id, 'quantidade': 999}],
                pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('24975.00'), 'troco': Decimal('0.00')}]
            )
        self.assertIn("Estoque insuficiente", str(ctx.exception))

    # =========================================================================
    # 20. CSRF E SEGURANÇA DE COOKIES
    # =========================================================================
    def test_20_configuracoes_seguranca_cookies(self):
        """Verifica se os cookies de sessão estão configurados com HttpOnly e cabeçalhos de segurança."""
        self.assertTrue(getattr(settings, 'SESSION_COOKIE_HTTPONLY', False))
        self.assertEqual(getattr(settings, 'X_FRAME_OPTIONS', ''), 'DENY')
        self.assertTrue(getattr(settings, 'SECURE_CONTENT_TYPE_NOSNIFF', False))

    # =========================================================================
    # 21. VENDA CANCELADA NÃO APARECE NO FATURAMENTO
    # =========================================================================
    def test_21_venda_cancelada_nao_aparece_no_faturamento(self):
        """Venda cancelada é excluída das somas de faturamento."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a1,
            itens_data=[{'produto_id': self.produto_a.id, 'quantidade': 2}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('50.00'), 'troco': Decimal('0.00')}]
        )
        SaleService.cancelar_venda(venda.id, self.empresa_a, self.admin_a, "Cancelada teste")
        from apps.relatorios.services import ReportService
        p = ReportService.parse_periodo('hoje')
        dados = ReportService.get_vendas_report(self.empresa_a, p['start_datetime'], p['end_datetime'])
        self.assertEqual(dados['faturamento_liquido'], Decimal('0.00'))
        self.assertEqual(dados['qtd_vendas'], 0)

    # =========================================================================
    # 22. VENDA CANCELADA NÃO APARECE NO LUCRO
    # =========================================================================
    def test_22_venda_cancelada_nao_aparece_no_lucro(self):
        """Lucro bruto de vendas canceladas não deve ser somado."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a1,
            itens_data=[{'produto_id': self.produto_a.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('25.00'), 'troco': Decimal('0.00')}]
        )
        SaleService.cancelar_venda(venda.id, self.empresa_a, self.admin_a, "Cancelada lucro")
        from apps.relatorios.services import ReportService
        p = ReportService.parse_periodo('hoje')
        dados = ReportService.get_vendas_report(self.empresa_a, p['start_datetime'], p['end_datetime'])
        self.assertEqual(dados['lucro_bruto'], Decimal('0.00'))

    # =========================================================================
    # 23. VENDA CANCELADA NÃO ALTERA INDEVIDAMENTE O CAIXA
    # =========================================================================
    def test_23_venda_cancelada_estorna_financeiro(self):
        """Cancelamento de venda gera registro de estorno de SAIDA no Fluxo de Caixa."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a1,
            itens_data=[{'produto_id': self.produto_a.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('25.00'), 'troco': Decimal('0.00')}]
        )
        SaleService.cancelar_venda(venda.id, self.empresa_a, self.admin_a, "Estorno financeiro")
        estorno = FluxoCaixa.objects.filter(
            empresa=self.empresa_a, tipo='SAIDA', categoria='Estorno Venda'
        ).first()
        self.assertIsNotNone(estorno)
        self.assertEqual(estorno.valor, Decimal('25.00'))

    # =========================================================================
    # 24. VENDA CANCELADA DEVOLVE ESTOQUE CORRETAMENTE
    # =========================================================================
    def test_24_venda_cancelada_devolve_estoque(self):
        """Cancelar venda devolve exatamente a quantidade vendida ao estoque."""
        estoque_inicial = self.produto_a.estoque_atual  # 40
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a1,
            itens_data=[{'produto_id': self.produto_a.id, 'quantidade': 3}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('75.00'), 'troco': Decimal('0.00')}]
        )
        self.produto_a.refresh_from_db()
        self.assertEqual(self.produto_a.estoque_atual, Decimal('37.000'))

        SaleService.cancelar_venda(venda.id, self.empresa_a, self.admin_a, "Estorno total estoque")
        self.produto_a.refresh_from_db()
        self.assertEqual(self.produto_a.estoque_atual, estoque_inicial)

        mov = MovimentacaoEstoque.objects.filter(
            empresa=self.empresa_a, tipo='ESTORNO', produto=self.produto_a
        ).first()
        self.assertIsNotNone(mov)
        self.assertEqual(mov.quantidade, Decimal('3.000'))

    # =========================================================================
    # 25. PERSISTÊNCIA DA SUÍTE ANTERIOR
    # =========================================================================
    def test_25_configuracao_loggers_ativos(self):
        """Verifica se a estrutura de logging foi devidamente inicializada no settings."""
        self.assertIn('apps', settings.LOGGING.get('loggers', {}))
        self.assertIn('console', settings.LOGGING.get('handlers', {}))

