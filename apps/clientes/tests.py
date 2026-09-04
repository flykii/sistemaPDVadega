from datetime import timedelta
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.db import IntegrityError

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.produtos.models import Produto, Categoria
from apps.produtos.services import StockService
from apps.caixas.models import Caixa, SessaoCaixa, MovimentacaoCaixa
from apps.caixas.services import CashService
from apps.vendas.models import Venda, ItemVenda, PagamentoVenda
from apps.vendas.services import SaleService
from apps.clientes.models import Cliente
from apps.financeiro.models import ContaReceber, PagamentoContaReceber, FluxoCaixa
from apps.financeiro.services import FinancialService

class ClientesCrediarioTestCase(TestCase):
    def setUp(self):
        # Empresas
        self.empresa_a = Empresa.objects.create(
            razao_social="Adega Alpha LTDA",
            nome_fantasia="Adega Alpha",
            cnpj="11222333000100"
        )
        self.empresa_b = Empresa.objects.create(
            razao_social="Adega Beta LTDA",
            nome_fantasia="Adega Beta",
            cnpj="44555666000100"
        )

        # Operador
        self.operador_a = Usuario.objects.create_user(
            username="operador_a",
            email="op_a@teste.com",
            password="password123",
            empresa=self.empresa_a,
            cargo='OPERADOR'
        )

        # Caixa e Sessão Aberta
        self.caixa_a = Caixa.objects.create(
            empresa=self.empresa_a,
            nome="Caixa 01",
            codigo_identificador="CX-01"
        )
        self.sessao_caixa = CashService.abrir_caixa(self.caixa_a, self.operador_a, Decimal('100.00'))

        # Categoria e Produto
        self.categoria = Categoria.objects.create(empresa=self.empresa_a, nome="Bebidas")
        self.produto_vinho = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="7890001",
            nome="Vinho Tinto Seco",
            preco_custo=Decimal('20.00'),
            preco_venda=Decimal('50.00'),
            estoque_atual=Decimal('20.000'),
            controle_estoque=True
        )

        # Cliente com Limite de R$ 500,00
        self.cliente = Cliente.objects.create(
            empresa=self.empresa_a,
            nome="João da Silva",
            cpf_cnpj="12345678900",
            telefone="11999998888",
            endereco="Rua das Flores, 100",
            limite_credito=Decimal('500.00'),
            saldo_devedor=Decimal('0.00'),
            ativo=True
        )

    # 1. Cadastro de Cliente
    def test_1_cadastro_cliente(self):
        self.assertEqual(self.cliente.nome, "João da Silva")
        self.assertEqual(self.cliente.limite_credito, Decimal('500.00'))
        self.assertEqual(self.cliente.saldo_devedor, Decimal('0.00'))
        self.assertTrue(self.cliente.ativo)

    # 2. Isolamento de Clientes por Empresa (Multi-tenancy)
    def test_2_isolamento_clientes_empresa(self):
        cli_b = Cliente.objects.create(
            empresa=self.empresa_b,
            nome="Cliente Beta",
            limite_credito=Decimal('1000.00')
        )
        self.assertIn(self.cliente, Cliente.objects.filter(empresa=self.empresa_a))
        self.assertNotIn(cli_b, Cliente.objects.filter(empresa=self.empresa_a))

    # 3. Limite de Crédito e 4. Crédito Disponível
    def test_3_e_4_limite_e_credito_disponivel(self):
        self.cliente.saldo_devedor = Decimal('150.00')
        self.cliente.save()
        self.assertEqual(self.cliente.credito_disponivel, Decimal('350.00'))
        self.assertEqual(self.cliente.percentual_utilizado, 30.0)

    # 5. Venda em Crediário no PDV
    def test_5_venda_crediario_sucesso(self):
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_caixa,
            cliente=self.cliente,
            itens_data=[{'produto_id': self.produto_vinho.id, 'quantidade': 2, 'preco_venda': 50.00}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': 100.00, 'troco': 0.00}]
        )
        self.assertEqual(venda.total, Decimal('100.00'))
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.saldo_devedor, Decimal('100.00'))
        self.assertEqual(self.cliente.credito_disponivel, Decimal('400.00'))

    # 6. Venda sem cliente bloqueada no crediário
    def test_6_venda_sem_cliente_bloqueada(self):
        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa_a,
                operador=self.operador_a,
                sessao_caixa=self.sessao_caixa,
                cliente=None,
                itens_data=[{'produto_id': self.produto_vinho.id, 'quantidade': 1, 'preco_venda': 50.00}],
                pagamentos_data=[{'forma': 'CREDIARIO', 'valor': 50.00, 'troco': 0.00}]
            )
        self.assertIn("exigem a seleção de um Cliente", str(ctx.exception))

    # 7. Venda acima do limite bloqueada
    def test_7_venda_acima_do_limite_bloqueada(self):
        self.cliente.saldo_devedor = Decimal('450.00')
        self.cliente.save()
        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa_a,
                operador=self.operador_a,
                sessao_caixa=self.sessao_caixa,
                cliente=self.cliente,
                itens_data=[{'produto_id': self.produto_vinho.id, 'quantidade': 2, 'preco_venda': 50.00}], # Total 100
                pagamentos_data=[{'forma': 'CREDIARIO', 'valor': 100.00, 'troco': 0.00}]
            )
        self.assertIn("Limite de crédito insuficiente", str(ctx.exception))

    # 8. Criação automática de ContaReceber e 9. Atualização do saldo devedor
    def test_8_e_9_criacao_automatica_conta_receber(self):
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_caixa,
            cliente=self.cliente,
            itens_data=[{'produto_id': self.produto_vinho.id, 'quantidade': 1, 'preco_venda': 50.00}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': 50.00, 'troco': 0.00}]
        )
        conta = ContaReceber.objects.filter(venda=venda).first()
        self.assertIsNotNone(conta)
        self.assertEqual(conta.cliente, self.cliente)
        self.assertEqual(conta.valor_original, Decimal('50.00'))
        self.assertEqual(conta.valor_pago, Decimal('0.00'))
        self.assertEqual(conta.saldo, Decimal('50.00'))
        self.assertEqual(conta.status, 'ABERTA')

    # 10. Pagamento parcial de ContaReceber e 12. Marcada como PARCIAL
    def test_10_e_12_pagamento_parcial(self):
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a,
            cliente=self.cliente,
            descricao="Compra Fiada",
            valor=Decimal('300.00'),
            valor_original=Decimal('300.00'),
            valor_pago=Decimal('0.00'),
            data_vencimento=timezone.now().date() + timedelta(days=30),
            status='ABERTA'
        )
        self.cliente.saldo_devedor = Decimal('300.00')
        self.cliente.save()

        # Pagamento parcial de 100
        FinancialService.receber_pagamento_conta(
            conta=conta,
            valor_pago=Decimal('100.00'),
            forma_pagamento='PIX',
            usuario=self.operador_a
        )
        conta.refresh_from_db()
        self.cliente.refresh_from_db()

        self.assertEqual(conta.valor_pago, Decimal('100.00'))
        self.assertEqual(conta.saldo, Decimal('200.00'))
        self.assertEqual(conta.status, 'PARCIAL')
        self.assertEqual(self.cliente.saldo_devedor, Decimal('200.00'))

    # 11. Pagamento total e 13. Marcada como QUITADA
    def test_11_e_13_pagamento_total_quitada(self):
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a,
            cliente=self.cliente,
            descricao="Compra Fiada 2",
            valor=Decimal('200.00'),
            valor_original=Decimal('200.00'),
            valor_pago=Decimal('0.00'),
            data_vencimento=timezone.now().date() + timedelta(days=30),
            status='ABERTA'
        )
        self.cliente.saldo_devedor = Decimal('200.00')
        self.cliente.save()

        # Quitação total de 200
        FinancialService.receber_pagamento_conta(
            conta=conta,
            valor_pago=Decimal('200.00'),
            forma_pagamento='DINHEIRO',
            sessao_caixa=self.sessao_caixa,
            usuario=self.operador_a
        )
        conta.refresh_from_db()
        self.cliente.refresh_from_db()

        self.assertEqual(conta.valor_pago, Decimal('200.00'))
        self.assertEqual(conta.saldo, Decimal('0.00'))
        self.assertEqual(conta.status, 'QUITADA')
        self.assertEqual(self.cliente.saldo_devedor, Decimal('0.00'))

    # 14. Pagamento superior ao saldo bloqueado com erro
    def test_14_pagamento_superior_ao_saldo_bloqueado(self):
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a,
            cliente=self.cliente,
            descricao="Compra Fiada 3",
            valor=Decimal('100.00'),
            valor_original=Decimal('100.00'),
            valor_pago=Decimal('0.00'),
            data_vencimento=timezone.now().date() + timedelta(days=30),
            status='ABERTA'
        )
        with self.assertRaises(ValueError) as ctx:
            FinancialService.receber_pagamento_conta(
                conta=conta,
                valor_pago=Decimal('150.00'),
                forma_pagamento='PIX',
                usuario=self.operador_a
            )
        self.assertIn("não pode ser maior que o saldo da dívida", str(ctx.exception))

    # 15. Recebimento em DINHEIRO aumentando caixa físico
    def test_15_recebimento_dinheiro_aumenta_caixa_fisico(self):
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a,
            cliente=self.cliente,
            descricao="Divida Balcao",
            valor=Decimal('100.00'),
            valor_original=Decimal('100.00'),
            valor_pago=Decimal('0.00'),
            data_vencimento=timezone.now().date() + timedelta(days=10),
            status='ABERTA'
        )
        saldo_caixa_antes = self.sessao_caixa.saldo_esperado
        FinancialService.receber_pagamento_conta(
            conta=conta,
            valor_pago=Decimal('100.00'),
            forma_pagamento='DINHEIRO',
            sessao_caixa=self.sessao_caixa,
            usuario=self.operador_a
        )
        self.sessao_caixa.refresh_from_db()
        self.assertEqual(self.sessao_caixa.saldo_esperado, saldo_caixa_antes + Decimal('100.00'))

    # 16. Recebimento em PIX NÃO aumentando caixa físico
    def test_16_recebimento_pix_nao_aumenta_caixa_fisico(self):
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a,
            cliente=self.cliente,
            descricao="Divida PIX",
            valor=Decimal('80.00'),
            valor_original=Decimal('80.00'),
            valor_pago=Decimal('0.00'),
            data_vencimento=timezone.now().date() + timedelta(days=10),
            status='ABERTA'
        )
        saldo_caixa_antes = self.sessao_caixa.saldo_esperado
        FinancialService.receber_pagamento_conta(
            conta=conta,
            valor_pago=Decimal('80.00'),
            forma_pagamento='PIX',
            sessao_caixa=self.sessao_caixa,
            usuario=self.operador_a
        )
        self.sessao_caixa.refresh_from_db()
        self.assertEqual(self.sessao_caixa.saldo_esperado, saldo_caixa_antes)

    # 17. Recebimento em CARTAO_DEBITO NÃO aumentando caixa físico
    def test_17_recebimento_cartao_nao_aumenta_caixa_fisico(self):
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a,
            cliente=self.cliente,
            descricao="Divida Cartao",
            valor=Decimal('60.00'),
            valor_original=Decimal('60.00'),
            valor_pago=Decimal('0.00'),
            data_vencimento=timezone.now().date() + timedelta(days=10),
            status='ABERTA'
        )
        saldo_caixa_antes = self.sessao_caixa.saldo_esperado
        FinancialService.receber_pagamento_conta(
            conta=conta,
            valor_pago=Decimal('60.00'),
            forma_pagamento='CARTAO_DEBITO',
            sessao_caixa=self.sessao_caixa,
            usuario=self.operador_a
        )
        self.sessao_caixa.refresh_from_db()
        self.assertEqual(self.sessao_caixa.saldo_esperado, saldo_caixa_antes)

    # 18. Recebimento em DINHEIRO com troco
    def test_18_recebimento_dinheiro_com_troco(self):
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a,
            cliente=self.cliente,
            descricao="Divida Com Troco",
            valor=Decimal('77.30'),
            valor_original=Decimal('77.30'),
            valor_pago=Decimal('0.00'),
            data_vencimento=timezone.now().date() + timedelta(days=10),
            status='ABERTA'
        )
        saldo_caixa_antes = self.sessao_caixa.saldo_esperado
        # Cliente entrega 100 para pagar 77.30 -> troco 22.70 -> valor efetivo 77.30
        FinancialService.receber_pagamento_conta(
            conta=conta,
            valor_pago=Decimal('100.00'),
            forma_pagamento='DINHEIRO',
            troco=Decimal('22.70'),
            sessao_caixa=self.sessao_caixa,
            usuario=self.operador_a
        )
        conta.refresh_from_db()
        self.sessao_caixa.refresh_from_db()

        self.assertEqual(conta.valor_pago, Decimal('77.30'))
        self.assertEqual(conta.status, 'QUITADA')
        self.assertEqual(self.sessao_caixa.saldo_esperado, saldo_caixa_antes + Decimal('77.30'))

    # 19. Conta vencida identificada
    def test_19_conta_vencida(self):
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a,
            cliente=self.cliente,
            descricao="Conta Antiga",
            valor=Decimal('100.00'),
            valor_original=Decimal('100.00'),
            data_vencimento=timezone.now().date() - timedelta(days=5),
            status='ABERTA'
        )
        self.assertTrue(conta.is_vencida)
        self.assertEqual(conta.status_display_calculado, 'Vencida')

    # 20. Histórico financeiro do cliente e 21. Histórico de vendas do cliente
    def test_20_e_21_historico_cliente(self):
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_caixa,
            cliente=self.cliente,
            itens_data=[{'produto_id': self.produto_vinho.id, 'quantidade': 1, 'preco_venda': 50.00}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': 50.00, 'troco': 0.00}]
        )
        self.assertEqual(self.cliente.contas_receber.count(), 1)
        self.assertEqual(Venda.objects.filter(cliente=self.cliente).count(), 1)

    # 22. Conciliação faturamento x recebimento (não duplica faturamento)
    def test_22_conciliacao_faturamento_sem_duplicidade(self):
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_caixa,
            cliente=self.cliente,
            itens_data=[{'produto_id': self.produto_vinho.id, 'quantidade': 2, 'preco_venda': 50.00}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': 100.00, 'troco': 0.00}]
        )
        conta = ContaReceber.objects.filter(venda=venda).first()

        # Quitação posterior
        FinancialService.receber_pagamento_conta(
            conta=conta,
            valor_pago=Decimal('100.00'),
            forma_pagamento='DINHEIRO',
            sessao_caixa=self.sessao_caixa,
            usuario=self.operador_a
        )

        # Faturamento continua sendo 100 (total da venda)
        faturamento_vendas = sum((v.total for v in Venda.objects.filter(empresa=self.empresa_a)), Decimal('0.00'))
        self.assertEqual(faturamento_vendas, Decimal('100.00'))

    # 23. Rollback transacional em caso de erro na venda fiada
    def test_23_rollback_venda_fiada(self):
        vendas_antes = Venda.objects.count()
        contas_antes = ContaReceber.objects.count()
        saldo_antes = self.cliente.saldo_devedor
        estoque_antes = self.produto_vinho.estoque_atual

        with self.assertRaises(ValueError):
            SaleService.processar_venda(
                empresa=self.empresa_a,
                operador=self.operador_a,
                sessao_caixa=self.sessao_caixa,
                cliente=self.cliente,
                itens_data=[
                    {'produto_id': self.produto_vinho.id, 'quantidade': 1, 'preco_venda': 50.00},
                    {'produto_id': 999999, 'quantidade': 1, 'preco_venda': 50.00} # Erro
                ],
                pagamentos_data=[{'forma': 'CREDIARIO', 'valor': 100.00, 'troco': 0.00}]
            )

        self.assertEqual(Venda.objects.count(), vendas_antes)
        self.assertEqual(ContaReceber.objects.count(), contas_antes)
        self.cliente.refresh_from_db()
        self.produto_vinho.refresh_from_db()
        self.assertEqual(self.cliente.saldo_devedor, saldo_antes)
        self.assertEqual(self.produto_vinho.estoque_atual, estoque_antes)

    # 24. Idempotência de venda fiada via offline_uuid
    def test_24_idempotencia_venda_fiada(self):
        uuid_teste = "OFF-CREDIARIO-12345"
        venda1 = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_caixa,
            cliente=self.cliente,
            itens_data=[{'produto_id': self.produto_vinho.id, 'quantidade': 1, 'preco_venda': 50.00}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': 50.00, 'troco': 0.00}],
            offline_uuid=uuid_teste
        )
        # Reenvio com mesmo uuid
        venda2 = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_caixa,
            cliente=self.cliente,
            itens_data=[{'produto_id': self.produto_vinho.id, 'quantidade': 1, 'preco_venda': 50.00}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': 50.00, 'troco': 0.00}],
            offline_uuid=uuid_teste
        )
        self.assertEqual(venda1.id, venda2.id)
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.saldo_devedor, Decimal('50.00')) # Não dobrou

    # 25. Concorrência de duas vendas no limite do cliente
    def test_25_concorrencia_limite_cliente(self):
        self.cliente.limite_credito = Decimal('80.00')
        self.cliente.saldo_devedor = Decimal('0.00')
        self.cliente.save()

        # Venda 1 consome 50.00 (Restam 30.00 de limite)
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_caixa,
            cliente=self.cliente,
            itens_data=[{'produto_id': self.produto_vinho.id, 'quantidade': 1, 'preco_venda': 50.00}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': 50.00, 'troco': 0.00}]
        )
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.saldo_devedor, Decimal('50.00'))

        # Venda 2 tenta consumir 50.00 adicionais (ultrapassando os 30.00 disponíveis) -> deve ser bloqueada
        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa_a,
                operador=self.operador_a,
                sessao_caixa=self.sessao_caixa,
                cliente=self.cliente,
                itens_data=[{'produto_id': self.produto_vinho.id, 'quantidade': 1, 'preco_venda': 50.00}],
                pagamentos_data=[{'forma': 'CREDIARIO', 'valor': 50.00, 'troco': 0.00}]
            )
        self.assertIn("Limite de crédito insuficiente", str(ctx.exception))

    # 26. Concorrência de dois pagamentos da mesma conta
    def test_26_concorrencia_pagamento_mesma_conta(self):
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a,
            cliente=self.cliente,
            descricao="Divida Unica",
            valor=Decimal('100.00'),
            valor_original=Decimal('100.00'),
            valor_pago=Decimal('0.00'),
            data_vencimento=timezone.now().date() + timedelta(days=10),
            status='ABERTA'
        )
        # Pagamento 1 quita 100
        FinancialService.receber_pagamento_conta(
            conta=conta,
            valor_pago=Decimal('100.00'),
            forma_pagamento='PIX',
            usuario=self.operador_a
        )
        conta.refresh_from_db()
        self.assertEqual(conta.status, 'QUITADA')

        # Pagamento 2 tenta pagar novamente a conta quitada
        with self.assertRaises(ValueError) as ctx:
            FinancialService.receber_pagamento_conta(
                conta=conta,
                valor_pago=Decimal('50.00'),
                forma_pagamento='PIX',
                usuario=self.operador_a
            )
        self.assertIn("já está totalmente quitada", str(ctx.exception))

    # 27. Isolamento de contas entre empresas
    def test_27_isolamento_contas_entre_empresas(self):
        conta_a = ContaReceber.objects.create(
            empresa=self.empresa_a,
            descricao="Conta Alpha",
            valor=Decimal('50.00'),
            data_vencimento=timezone.now().date()
        )
        conta_b = ContaReceber.objects.create(
            empresa=self.empresa_b,
            descricao="Conta Beta",
            valor=Decimal('50.00'),
            data_vencimento=timezone.now().date()
        )
        self.assertIn(conta_a, ContaReceber.objects.filter(empresa=self.empresa_a))
        self.assertNotIn(conta_b, ContaReceber.objects.filter(empresa=self.empresa_a))

    # 28. Venda fiada reduzindo estoque e 29. Venda fiada não aumentando gaveta física
    def test_28_e_29_venda_fiada_estoque_e_caixa_fisico(self):
        estoque_antes = self.produto_vinho.estoque_atual
        caixa_antes = self.sessao_caixa.saldo_esperado

        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_caixa,
            cliente=self.cliente,
            itens_data=[{'produto_id': self.produto_vinho.id, 'quantidade': 3, 'preco_venda': 50.00}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': 150.00, 'troco': 0.00}]
        )

        self.produto_vinho.refresh_from_db()
        self.sessao_caixa.refresh_from_db()

        # Estoque baixou 3 unidades
        self.assertEqual(self.produto_vinho.estoque_atual, estoque_antes - Decimal('3.000'))
        # Caixa físico permanece inalterado (pois fiado não coloca dinheiro na gaveta)
        self.assertEqual(self.sessao_caixa.saldo_esperado, caixa_antes)

    # 30. Integração Completa de Ponta a Ponta
    def test_30_integracao_completa_ponta_a_ponta(self):
        # 1. Saldo inicial do cliente
        self.assertEqual(self.cliente.saldo_devedor, Decimal('0.00'))
        self.assertEqual(self.cliente.credito_disponivel, Decimal('500.00'))

        # 2. Realiza venda fiada de R$ 150,00 no PDV
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_caixa,
            cliente=self.cliente,
            itens_data=[{'produto_id': self.produto_vinho.id, 'quantidade': 3, 'preco_venda': 50.00}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': 150.00, 'troco': 0.00}]
        )
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.saldo_devedor, Decimal('150.00'))
        self.assertEqual(self.cliente.credito_disponivel, Decimal('350.00'))

        conta = ContaReceber.objects.filter(venda=venda).first()
        self.assertIsNotNone(conta)
        self.assertEqual(conta.saldo, Decimal('150.00'))

        # 3. Cliente faz pagamento parcial de R$ 50,00 via PIX
        FinancialService.receber_pagamento_conta(
            conta=conta,
            valor_pago=Decimal('50.00'),
            forma_pagamento='PIX',
            sessao_caixa=self.sessao_caixa,
            usuario=self.operador_a
        )
        conta.refresh_from_db()
        self.cliente.refresh_from_db()
        self.assertEqual(conta.saldo, Decimal('100.00'))
        self.assertEqual(conta.status, 'PARCIAL')
        self.assertEqual(self.cliente.saldo_devedor, Decimal('100.00'))

        # 4. Cliente quita os R$ 100,00 restantes em DINHEIRO entregando uma nota de R$ 100
        saldo_gaveta_antes = self.sessao_caixa.saldo_esperado
        FinancialService.receber_pagamento_conta(
            conta=conta,
            valor_pago=Decimal('100.00'),
            forma_pagamento='DINHEIRO',
            troco=Decimal('0.00'),
            sessao_caixa=self.sessao_caixa,
            usuario=self.operador_a
        )
        conta.refresh_from_db()
        self.cliente.refresh_from_db()
        self.sessao_caixa.refresh_from_db()

        # Quitação total e gaveta aumentada em 100
        self.assertEqual(conta.saldo, Decimal('0.00'))
        self.assertEqual(conta.status, 'QUITADA')
        self.assertEqual(self.cliente.saldo_devedor, Decimal('0.00'))
        self.assertEqual(self.cliente.credito_disponivel, Decimal('500.00'))
        self.assertEqual(self.sessao_caixa.saldo_esperado, saldo_gaveta_antes + Decimal('100.00'))
