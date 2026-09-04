from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.caixas.models import Caixa, SessaoCaixa, MovimentacaoCaixa
from apps.caixas.services import CashService
from apps.produtos.models import Produto
from apps.clientes.models import Cliente
from apps.vendas.services import SaleService
from apps.financeiro.models import FluxoCaixa, ContaReceber

class CashModuleTestCase(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            razao_social="Adega & Mercado Teste LTDA",
            nome_fantasia="Adega Teste",
            cnpj="12345678000199"
        )
        self.empresa2 = Empresa.objects.create(
            razao_social="Outra Empresa LTDA",
            nome_fantasia="Outro Mercado",
            cnpj="99887766000100"
        )

        self.operador = Usuario.objects.create_user(
            username="operador_caixa",
            email="caixa@teste.com",
            password="password123",
            empresa=self.empresa,
            cargo='OPERADOR'
        )

        self.caixa_1 = Caixa.objects.create(
            empresa=self.empresa,
            nome="Caixa 01 - Principal",
            codigo_identificador="CX-01"
        )

        self.caixa_2 = Caixa.objects.create(
            empresa=self.empresa,
            nome="Caixa 02 - Rápido",
            codigo_identificador="CX-02"
        )

        self.produto_cerveja = Produto.objects.create(
            empresa=self.empresa,
            codigo_barras="789000111",
            nome="Cerveja Heineken 350ml",
            preco_custo=Decimal('4.00'),
            preco_venda=Decimal('10.00'),
            estoque_atual=Decimal('100.000')
        )

        self.cliente = Cliente.objects.create(
            empresa=self.empresa,
            nome="Cliente Fiel",
            limite_credito=Decimal('1000.00'),
            saldo_devedor=Decimal('0.00')
        )

    # 1. Abertura de Caixa
    def test_1_abertura_de_caixa(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'), nome_operador="João do Caixa")
        self.assertEqual(sessao.status, 'ABERTA')
        self.assertEqual(sessao.saldo_inicial, Decimal('200.00'))
        self.assertEqual(sessao.saldo_atual, Decimal('200.00'))
        self.assertEqual(sessao.nome_operador_exibicao, "João do Caixa")
        self.caixa_1.refresh_from_db()
        self.assertEqual(self.caixa_1.status, 'ABERTO')

    # 2. Abertura Duplicada Bloqueada
    def test_2_abertura_duplicada_bloqueada(self):
        CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'))
        with self.assertRaises(ValueError) as ctx:
            CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('100.00'))
        self.assertIn("já possui uma sessão aberta", str(ctx.exception))

    # 3. Venda em Dinheiro Aumenta Saldo Físico
    def test_3_venda_dinheiro(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'))
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=sessao,
            itens_data=[{'produto_id': self.produto_cerveja.id, 'quantidade': 10, 'preco_venda': 10.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 100.00, 'troco': 0.00}]
        )
        sessao.refresh_from_db()
        self.assertEqual(sessao.total_vendas_dinheiro, Decimal('100.00'))
        self.assertEqual(sessao.saldo_atual, Decimal('300.00')) # 200 + 100

    # 4. Venda PIX NÃO Altera Dinheiro Físico na Gaveta
    def test_4_venda_pix_nao_altera_caixa_fisico(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'))
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=sessao,
            itens_data=[{'produto_id': self.produto_cerveja.id, 'quantidade': 5, 'preco_venda': 10.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 50.00, 'troco': 0.00}]
        )
        sessao.refresh_from_db()
        self.assertEqual(sessao.total_vendas_pix, Decimal('50.00'))
        self.assertEqual(sessao.total_vendas_dinheiro, Decimal('0.00'))
        self.assertEqual(sessao.saldo_atual, Decimal('200.00')) # Saldo físico permanece R$ 200

    # 5. Venda Débito NÃO Altera Dinheiro Físico na Gaveta
    def test_5_venda_debito_nao_altera_caixa_fisico(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'))
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=sessao,
            itens_data=[{'produto_id': self.produto_cerveja.id, 'quantidade': 3, 'preco_venda': 10.00}],
            pagamentos_data=[{'forma': 'CARTAO_DEBITO', 'valor': 30.00, 'troco': 0.00}]
        )
        sessao.refresh_from_db()
        self.assertEqual(sessao.total_vendas_debito, Decimal('30.00'))
        self.assertEqual(sessao.saldo_atual, Decimal('200.00'))

    # 6. Venda Crédito NÃO Altera Dinheiro Físico na Gaveta
    def test_6_venda_credito_nao_altera_caixa_fisico(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'))
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=sessao,
            itens_data=[{'produto_id': self.produto_cerveja.id, 'quantidade': 4, 'preco_venda': 10.00}],
            pagamentos_data=[{'forma': 'CARTAO_CREDITO', 'valor': 40.00, 'troco': 0.00}]
        )
        sessao.refresh_from_db()
        self.assertEqual(sessao.total_vendas_credito, Decimal('40.00'))
        self.assertEqual(sessao.saldo_atual, Decimal('200.00'))

    # 7. Venda Dividida: Apenas Parcela em Dinheiro Altera Gaveta
    def test_7_venda_dividida(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'))
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=sessao,
            itens_data=[{'produto_id': self.produto_cerveja.id, 'quantidade': 10, 'preco_venda': 10.00}],
            pagamentos_data=[
                {'forma': 'PIX', 'valor': 60.00, 'troco': 0.00},
                {'forma': 'DINHEIRO', 'valor': 50.00, 'troco': 10.00} # Efetivo: R$ 40
            ]
        )
        sessao.refresh_from_db()
        self.assertEqual(sessao.total_vendas, Decimal('100.00'))
        self.assertEqual(sessao.total_vendas_pix, Decimal('60.00'))
        self.assertEqual(sessao.total_vendas_dinheiro, Decimal('40.00'))
        self.assertEqual(sessao.saldo_atual, Decimal('240.00')) # 200 + 40

    # 8. Venda com Troco: Somente Valor Efetivo Incorporado
    def test_8_venda_com_troco(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'))
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=sessao,
            itens_data=[{'produto_id': self.produto_cerveja.id, 'quantidade': 1, 'preco_venda': 77.30}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 100.00, 'troco': 22.70}]
        )
        sessao.refresh_from_db()
        self.assertEqual(sessao.total_vendas_dinheiro, Decimal('77.30'))
        self.assertEqual(sessao.saldo_atual, Decimal('277.30')) # 200 + 77.30

    # 9. Suprimento Aumenta Dinheiro Físico
    def test_9_suprimento(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'))
        mov = CashService.registrar_movimentacao(sessao, 'SUPRIMENTO', Decimal('100.00'), 'Troco inicial extra', self.operador)
        sessao.refresh_from_db()
        self.assertEqual(sessao.total_suprimentos, Decimal('100.00'))
        self.assertEqual(sessao.saldo_atual, Decimal('300.00'))

        # Confirma lançamento em FluxoCaixa
        fluxo = FluxoCaixa.objects.filter(referencia_origem=f"CX-{sessao.id}-MOV-{mov.id}").first()
        self.assertIsNotNone(fluxo)
        self.assertEqual(fluxo.tipo, 'ENTRADA')
        self.assertEqual(fluxo.valor, Decimal('100.00'))

    # 10. Sangria Reduz Dinheiro Físico
    def test_10_sangria(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('500.00'))
        mov = CashService.registrar_movimentacao(sessao, 'SANGRIA', Decimal('200.00'), 'Recolhimento para o cofre', self.operador)
        sessao.refresh_from_db()
        self.assertEqual(sessao.total_sangrias, Decimal('200.00'))
        self.assertEqual(sessao.saldo_atual, Decimal('300.00')) # 500 - 200

        # Confirma lançamento em FluxoCaixa
        fluxo = FluxoCaixa.objects.filter(referencia_origem=f"CX-{sessao.id}-MOV-{mov.id}").first()
        self.assertIsNotNone(fluxo)
        self.assertEqual(fluxo.tipo, 'SAIDA')
        self.assertEqual(fluxo.valor, Decimal('200.00'))

    # 11. Sangria Superior ao Saldo Bloqueada
    def test_11_sangria_superior_ao_saldo_bloqueada(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'))
        with self.assertRaises(ValueError) as ctx:
            CashService.registrar_movimentacao(sessao, 'SANGRIA', Decimal('300.00'), 'Tentativa indevida', self.operador)
        self.assertIn("Saldo insuficiente", str(ctx.exception))

    # 12. Despesa Paga pelo Caixa Reduz Dinheiro Físico
    def test_12_despesa(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('500.00'))
        mov = CashService.registrar_movimentacao(sessao, 'DESPESA', Decimal('50.00'), 'Compra de sacolas e gelo', self.operador)
        sessao.refresh_from_db()
        self.assertEqual(sessao.total_despesas, Decimal('50.00'))
        self.assertEqual(sessao.saldo_atual, Decimal('450.00')) # 500 - 50

        fluxo = FluxoCaixa.objects.filter(referencia_origem=f"CX-{sessao.id}-MOV-{mov.id}").first()
        self.assertIsNotNone(fluxo)
        self.assertEqual(fluxo.tipo, 'SAIDA')
        self.assertEqual(fluxo.categoria, 'Despesa Caixa')

    # 13. Fechamento de Caixa sem Diferença
    def test_13_fechamento_sem_diferenca(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'))
        sessao_fechada = CashService.fechar_caixa(sessao, saldo_final_informado=Decimal('200.00'))
        self.assertEqual(sessao_fechada.status, 'FECHADA')
        self.assertEqual(sessao_fechada.saldo_final_calculado, Decimal('200.00'))
        self.assertEqual(sessao_fechada.saldo_final_informado, Decimal('200.00'))
        self.assertEqual(sessao_fechada.diferenca, Decimal('0.00'))
        self.assertEqual(sessao_fechada.status_fechamento_display, 'Fechado sem Diferença')
        self.caixa_1.refresh_from_db()
        self.assertEqual(self.caixa_1.status, 'FECHADO')

    # 14. Fechamento de Caixa com Falta
    def test_14_fechamento_com_falta(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('850.00'))
        sessao_fechada = CashService.fechar_caixa(sessao, saldo_final_informado=Decimal('840.00'))
        self.assertEqual(sessao_fechada.saldo_final_calculado, Decimal('850.00'))
        self.assertEqual(sessao_fechada.saldo_final_informado, Decimal('840.00'))
        self.assertEqual(sessao_fechada.diferenca, Decimal('-10.00'))
        self.assertIn("Falta de R$ 10.00", sessao_fechada.status_fechamento_display)

    # 15. Fechamento de Caixa com Sobra
    def test_15_fechamento_com_sobra(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('850.00'))
        sessao_fechada = CashService.fechar_caixa(sessao, saldo_final_informado=Decimal('860.00'))
        self.assertEqual(sessao_fechada.saldo_final_calculado, Decimal('850.00'))
        self.assertEqual(sessao_fechada.saldo_final_informado, Decimal('860.00'))
        self.assertEqual(sessao_fechada.diferenca, Decimal('10.00'))
        self.assertIn("Sobra de R$ 10.00", sessao_fechada.status_fechamento_display)

    # 16. Caixa Fechado Bloqueia Venda
    def test_16_caixa_fechado_bloqueando_venda(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'))
        CashService.fechar_caixa(sessao, saldo_final_informado=Decimal('200.00'))

        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa,
                operador=self.operador,
                sessao_caixa=sessao,
                itens_data=[{'produto_id': self.produto_cerveja.id, 'quantidade': 1, 'preco_venda': 10.00}],
                pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 10.00, 'troco': 0.00}]
            )
        self.assertIn("caixa fechado", str(ctx.exception))

    # 17. Caixa Fechado Bloqueia Movimentação Operacional
    def test_17_caixa_fechado_bloqueando_movimentacao(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'))
        CashService.fechar_caixa(sessao, saldo_final_informado=Decimal('200.00'))

        with self.assertRaises(ValueError) as ctx:
            CashService.registrar_movimentacao(sessao, 'SUPRIMENTO', Decimal('50.00'), 'Troco', self.operador)
        self.assertIn("caixa fechado", str(ctx.exception))

    # 18. Fechamento Duplicado Bloqueado
    def test_18_fechamento_duplicado(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'))
        CashService.fechar_caixa(sessao, saldo_final_informado=Decimal('200.00'))

        with self.assertRaises(ValueError) as ctx:
            CashService.fechar_caixa(sessao, saldo_final_informado=Decimal('200.00'))
        self.assertIn("já se encontra fechada", str(ctx.exception))

    # 19. Isolamento entre Múltiplos Caixas
    def test_19_isolamento_entre_caixas(self):
        sessao1 = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'))
        sessao2 = CashService.abrir_caixa(self.caixa_2, self.operador, Decimal('500.00'))

        # Venda de R$ 100 no Caixa 1
        SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=sessao1,
            itens_data=[{'produto_id': self.produto_cerveja.id, 'quantidade': 10, 'preco_venda': 10.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 100.00, 'troco': 0.00}]
        )

        sessao1.refresh_from_db()
        sessao2.refresh_from_db()

        self.assertEqual(sessao1.saldo_atual, Decimal('300.00'))
        self.assertEqual(sessao2.saldo_atual, Decimal('500.00')) # Intacto

    # 20. Isolamento entre Empresas
    def test_20_isolamento_entre_empresas(self):
        caixa_emp2 = Caixa.objects.create(empresa=self.empresa2, nome="Caixa Outra Empresa", codigo_identificador="CX-EMP2")
        self.assertNotIn(caixa_emp2, Caixa.objects.filter(empresa=self.empresa))

    # 21. Crediário Não Altera Caixa na Venda
    def test_21_crediario_nao_altera_caixa(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'))
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=sessao,
            cliente=self.cliente,
            itens_data=[{'produto_id': self.produto_cerveja.id, 'quantidade': 10, 'preco_venda': 10.00}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': 100.00, 'troco': 0.00}]
        )
        sessao.refresh_from_db()
        self.assertEqual(sessao.total_vendas_crediario, Decimal('100.00'))
        self.assertEqual(sessao.total_vendas_dinheiro, Decimal('0.00'))
        self.assertEqual(sessao.saldo_atual, Decimal('200.00')) # Não aumenta a gaveta

        # Confirma criação de Conta a Receber
        conta = ContaReceber.objects.filter(venda=venda).first()
        self.assertIsNotNone(conta)
        self.assertEqual(conta.valor, Decimal('100.00'))
        self.assertIn(conta.status, ['ABERTA', 'PENDENTE'])

    # 22. Cálculo Completo do Saldo Esperado com Múltiplas Operações
    def test_22_calculo_correto_do_saldo_esperado(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'))

        # Vendas em dinheiro: R$ 800
        SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=sessao,
            itens_data=[{'produto_id': self.produto_cerveja.id, 'quantidade': 80, 'preco_venda': 10.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 800.00, 'troco': 0.00}]
        )

        # Suprimento: R$ 100
        CashService.registrar_movimentacao(sessao, 'SUPRIMENTO', Decimal('100.00'), 'Aporte', self.operador)

        # Sangria: R$ 200
        CashService.registrar_movimentacao(sessao, 'SANGRIA', Decimal('200.00'), 'Retirada cofre', self.operador)

        # Despesa: R$ 50
        CashService.registrar_movimentacao(sessao, 'DESPESA', Decimal('50.00'), 'Gelo', self.operador)

        # Saldo esperado: 200 (inicial) + 800 (vendas) + 100 (suprimento) - 200 (sangria) - 50 (despesa) = R$ 850,00
        sessao.refresh_from_db()
        self.assertEqual(sessao.saldo_esperado, Decimal('850.00'))

    # 23. Saldo Esperado Nunca Alterado pelo Valor Contado
    def test_23_saldo_esperado_nunca_alterado_pelo_valor_contado(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('850.00'))
        # Operador informa R$ 840 (Falta de R$ 10)
        sessao_fechada = CashService.fechar_caixa(sessao, saldo_final_informado=Decimal('840.00'))
        self.assertEqual(sessao_fechada.saldo_final_calculado, Decimal('850.00'))
        self.assertEqual(sessao_fechada.saldo_final_informado, Decimal('840.00'))
        self.assertEqual(sessao_fechada.diferenca, Decimal('-10.00'))

    # 24. Gestão de Caixas Exibe Resumos Financeiros da Sessão Aberta
    def test_24_caixas_list_view_renders_open_session_financial_summary(self):
        sessao = CashService.abrir_caixa(self.caixa_1, self.operador, Decimal('200.00'))
        SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=sessao,
            itens_data=[{'produto_id': self.produto_cerveja.id, 'quantidade': 2, 'preco_venda': 10.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 20.00, 'troco': 0.00}]
        )
        CashService.registrar_movimentacao(sessao, 'SUPRIMENTO', Decimal('50.00'), 'Aporte', self.operador)

        self.client.force_login(self.operador)
        response = self.client.get('/caixas/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Conferência de Dinheiro Físico (Gaveta)')
        self.assertContains(response, 'Faturamento por Forma de Pagamento')
        self.assertContains(response, 'SALDO ESPERADO NA GAVETA')
        self.assertContains(response, 'TOTAL GERAL FATURADO')

