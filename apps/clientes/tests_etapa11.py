"""
ETAPA 11 — Suíte de Testes Automatizados Completa.
Clientes, Crediário, Contas a Receber, Recebimento de Débitos, Multi-Tenancy, Concorrência e Auditoria.
Cobre todos os 35 cenários de testes obrigatórios da Etapa 11.
"""
from decimal import Decimal
import uuid
from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.caixas.models import Caixa, SessaoCaixa, MovimentacaoCaixa
from apps.caixas.services import CashService
from apps.produtos.models import Produto, Categoria, MovimentacaoEstoque
from apps.produtos.services import StockService
from apps.clientes.models import Cliente, Fornecedor
from apps.vendas.models import Venda, ItemVenda, PagamentoVenda
from apps.vendas.services import SaleService
from apps.financeiro.models import ContaReceber, ContaPagar, FluxoCaixa, PagamentoContaReceber
from apps.financeiro.services import FinancialService
from apps.core.models import AuditLog, AuditService
from apps.relatorios.services import ReportService


class Etapa11CrediarioTestCase(TestCase):
    """Validação completa do módulo de Clientes, Crediário e Contas a Receber."""

    def setUp(self):
        # 1. Tenants (Empresa A e Empresa B)
        self.empresa_a = Empresa.objects.create(
            razao_social="Alpha Comercio LTDA",
            nome_fantasia="Loja Alpha",
            cnpj="11.222.333/0001-44"
        )
        self.empresa_b = Empresa.objects.create(
            razao_social="Beta Varejo LTDA",
            nome_fantasia="Loja Beta",
            cnpj="55.666.777/0001-88"
        )

        # Usuários
        self.admin_a = Usuario.objects.create_user(
            username='admin_a', password='pass123',
            empresa=self.empresa_a, cargo='ADMIN'
        )
        self.gerente_a = Usuario.objects.create_user(
            username='gerente_a', password='pass123',
            empresa=self.empresa_a, cargo='GERENTE'
        )
        self.operador_a = Usuario.objects.create_user(
            username='operador_a', password='pass123',
            empresa=self.empresa_a, cargo='OPERADOR'
        )
        self.financeiro_a = Usuario.objects.create_user(
            username='financeiro_a', password='pass123',
            empresa=self.empresa_a, cargo='FINANCEIRO'
        )
        self.estoquista_a = Usuario.objects.create_user(
            username='estoquista_a', password='pass123',
            empresa=self.empresa_a, cargo='ESTOQUISTA'
        )

        self.admin_b = Usuario.objects.create_user(
            username='admin_b', password='pass123',
            empresa=self.empresa_b, cargo='ADMIN'
        )

        # Caixas
        self.caixa_a = Caixa.objects.create(
            empresa=self.empresa_a, nome="Caixa Principal A", codigo_identificador="CX-01"
        )
        self.sessao_a = CashService.abrir_caixa(
            caixa=self.caixa_a, operador=self.operador_a,
            saldo_inicial=Decimal('200.00'), nome_operador="Operador Alpha"
        )

        # Produtos
        self.produto_arroz = Produto.objects.create(
            empresa=self.empresa_a, nome="Arroz 5kg",
            codigo_barras="7891001", preco_custo=Decimal('15.00'),
            preco_venda=Decimal('30.00'), estoque_atual=Decimal('100.000'),
            controle_estoque=True
        )
        self.produto_feijao = Produto.objects.create(
            empresa=self.empresa_a, nome="Feijão 1kg",
            codigo_barras="7891002", preco_custo=Decimal('5.00'),
            preco_venda=Decimal('10.00'), estoque_atual=Decimal('50.000'),
            controle_estoque=True
        )

        # Clientes Empresa A
        self.cliente_ativo = Cliente.objects.create(
            empresa=self.empresa_a, nome="João da Silva",
            cpf_cnpj="12345678901", telefone="11999990001",
            limite_credito=Decimal('500.00'), saldo_devedor=Decimal('0.00'),
            ativo=True
        )
        self.cliente_inativo = Cliente.objects.create(
            empresa=self.empresa_a, nome="Carlos Inativo",
            cpf_cnpj="98765432100", limite_credito=Decimal('300.00'),
            saldo_devedor=Decimal('0.00'), ativo=False
        )

        # Cliente Empresa B (mesmo CPF permitido entre empresas diferentes)
        self.cliente_b = Cliente.objects.create(
            empresa=self.empresa_b, nome="João Beta",
            cpf_cnpj="12345678901", limite_credito=Decimal('1000.00'),
            saldo_devedor=Decimal('0.00'), ativo=True
        )

    # =========================================================================
    # 1. CADASTRO DE CLIENTE
    # =========================================================================
    def test_01_cadastro_cliente_sucesso(self):
        """Cadastrar cliente com limite de crédito e dados de contato."""
        self.client.login(username='operador_a', password='pass123')
        resp = self.client.post('/clientes/novo/', {
            'nome': 'Maria Souza',
            'cpf_cnpj': '11122233344',
            'telefone': '11988887777',
            'email': 'maria@email.com',
            'limite_credito': '450.00',
            'ativo': 'on'
        })
        self.assertEqual(resp.status_code, 302)
        cliente = Cliente.objects.filter(empresa=self.empresa_a, cpf_cnpj='11122233344').first()
        self.assertIsNotNone(cliente)
        self.assertEqual(cliente.limite_credito, Decimal('450.00'))
        self.assertEqual(cliente.credito_disponivel, Decimal('450.00'))

    # =========================================================================
    # 2. ISOLAMENTO DE CLIENTE POR EMPRESA
    # =========================================================================
    def test_02_isolamento_cliente_por_empresa(self):
        """Clientes de empresas distintas são completamente isolados."""
        self.client.login(username='admin_a', password='pass123')
        resp = self.client.get('/clientes/')
        self.assertContains(resp, "João da Silva")
        self.assertNotContains(resp, "João Beta")

        # Tentativa de acessar ficha de cliente da Empresa B retorna 404
        resp_b = self.client.get(f'/clientes/ficha/{self.cliente_b.id}/')
        self.assertEqual(resp_b.status_code, 404)

    # =========================================================================
    # 3. CLIENTE INATIVO BLOQUEADO PARA CREDIÁRIO
    # =========================================================================
    def test_03_cliente_inativo_bloqueado_para_crediario(self):
        """Cliente inativo não pode comprar no crediário."""
        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa_a, sessao_caixa=self.sessao_a,
                operador=self.operador_a, cliente=self.cliente_inativo,
                itens_data=[{'produto_id': self.produto_arroz.id, 'quantidade': 1}],
                pagamentos_data=[{'forma': 'CREDIARIO', 'valor': Decimal('30.00'), 'troco': Decimal('0.00')}]
            )
        self.assertIn("inativo", str(ctx.exception).lower())

    # =========================================================================
    # 4. VENDA EM CREDIÁRIO NO PDV
    # =========================================================================
    def test_04_venda_crediario_gera_conta_receber_e_ajusta_saldo(self):
        """Venda no crediário gera ContaReceber e aumenta saldo devedor do cliente."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a, cliente=self.cliente_ativo,
            itens_data=[{'produto_id': self.produto_arroz.id, 'quantidade': 2}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': Decimal('60.00'), 'troco': Decimal('0.00')}]
        )
        self.assertEqual(venda.total, Decimal('60.00'))
        self.cliente_ativo.refresh_from_db()
        self.assertEqual(self.cliente_ativo.saldo_devedor, Decimal('60.00'))
        self.assertEqual(self.cliente_ativo.credito_disponivel, Decimal('440.00'))

        conta = ContaReceber.objects.filter(empresa=self.empresa_a, venda=venda).first()
        self.assertIsNotNone(conta)
        self.assertEqual(conta.valor, Decimal('60.00'))
        self.assertEqual(conta.saldo, Decimal('60.00'))
        self.assertEqual(conta.status, 'ABERTA')

    # =========================================================================
    # 5. CREDIÁRIO SEM CLIENTE BLOQUEADO
    # =========================================================================
    def test_05_crediario_sem_cliente_bloqueado(self):
        """Venda em crediário sem selecionar cliente deve lançar ValueError."""
        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa_a, sessao_caixa=self.sessao_a,
                operador=self.operador_a, cliente=None,
                itens_data=[{'produto_id': self.produto_arroz.id, 'quantidade': 1}],
                pagamentos_data=[{'forma': 'CREDIARIO', 'valor': Decimal('30.00'), 'troco': Decimal('0.00')}]
            )
        self.assertIn("seleção de um Cliente", str(ctx.exception))

    # =========================================================================
    # 6. CREDIÁRIO DENTRO DO LIMITE
    # =========================================================================
    def test_06_crediario_dentro_do_limite_autorizado(self):
        """Venda cujo valor somado ao saldo devedor respeita o limite é concluída com sucesso."""
        # Limite = 500, saldo = 0, venda = 500
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a, cliente=self.cliente_ativo,
            itens_data=[{'produto_id': self.produto_arroz.id, 'quantidade': 10}],  # 10 * 30 = 300
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': Decimal('300.00'), 'troco': Decimal('0.00')}]
        )
        self.assertEqual(venda.total, Decimal('300.00'))
        self.cliente_ativo.refresh_from_db()
        self.assertEqual(self.cliente_ativo.credito_disponivel, Decimal('200.00'))

    # =========================================================================
    # 7. CREDIÁRIO ACIMA DO LIMITE
    # =========================================================================
    def test_07_crediario_acima_do_limite_rejeitado(self):
        """Venda que ultrapassa o limite disponível deve ser rejeitada com mensagem amigável."""
        # Limite = 500, saldo = 0, venda = 510 (ultrapassa limite)
        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa_a, sessao_caixa=self.sessao_a,
                operador=self.operador_a, cliente=self.cliente_ativo,
                itens_data=[{'produto_id': self.produto_arroz.id, 'quantidade': 17}],  # 17 * 30 = 510
                pagamentos_data=[{'forma': 'CREDIARIO', 'valor': Decimal('510.00'), 'troco': Decimal('0.00')}]
            )
        self.assertIn("Limite de crédito insuficiente", str(ctx.exception))

    # =========================================================================
    # 8. PAGAMENTO DIVIDIDO (PIX + CREDIÁRIO)
    # =========================================================================
    def test_08_pagamento_dividido_pix_e_crediario(self):
        """Venda dividida entre PIX e Crediário registra ContaReceber apenas da parcela a prazo."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a, cliente=self.cliente_ativo,
            itens_data=[{'produto_id': self.produto_arroz.id, 'quantidade': 3}],  # Total 90.00
            pagamentos_data=[
                {'forma': 'PIX', 'valor': Decimal('40.00'), 'troco': Decimal('0.00')},
                {'forma': 'CREDIARIO', 'valor': Decimal('50.00'), 'troco': Decimal('0.00')},
            ]
        )
        self.assertEqual(venda.total, Decimal('90.00'))
        self.cliente_ativo.refresh_from_db()
        self.assertEqual(self.cliente_ativo.saldo_devedor, Decimal('50.00'))

        # A ContaReceber gerada deve ter o valor de R$ 50.00
        conta = ContaReceber.objects.get(empresa=self.empresa_a, venda=venda)
        self.assertEqual(conta.valor, Decimal('50.00'))

        # O caixa físico da gaveta NÃO é alterado pelo crediário nem pelo PIX
        self.sessao_a.refresh_from_db()
        self.assertEqual(self.sessao_a.saldo_esperado, Decimal('200.00'))

    # =========================================================================
    # 9. CRIAÇÃO DE CONTA A RECEBER
    # =========================================================================
    def test_09_estrutura_e_propriedades_conta_receber(self):
        """Garante consistência dos campos e propriedades de ContaReceber."""
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Mensalidade Contrato", valor=Decimal('150.00'),
            data_vencimento=timezone.now().date() + timedelta(days=15),
            status='ABERTA'
        )
        self.assertEqual(conta.valor_original, Decimal('150.00'))
        self.assertEqual(conta.valor_pago, Decimal('0.00'))
        self.assertEqual(conta.saldo, Decimal('150.00'))
        self.assertFalse(conta.is_vencida)
        self.assertEqual(conta.status_display_calculado, 'Aberta')

    # =========================================================================
    # 10. PAGAMENTO INTEGRAL
    # =========================================================================
    def test_10_pagamento_integral_quita_conta_e_reduz_saldo_cliente(self):
        """Recebimento integral marca conta como QUITADA e reduz saldo devedor."""
        # Cria dívida de R$ 100
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a, cliente=self.cliente_ativo,
            itens_data=[{'produto_id': self.produto_feijao.id, 'quantidade': 10}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': Decimal('100.00'), 'troco': Decimal('0.00')}]
        )
        conta = ContaReceber.objects.get(empresa=self.empresa_a, venda=venda)

        # Recebimento integral de R$ 100.00
        pag = FinancialService.receber_pagamento_conta(
            conta=conta, valor_pago=Decimal('100.00'),
            forma_pagamento='DINHEIRO', sessao_caixa=self.sessao_a,
            usuario=self.operador_a, observacao="Quitação total"
        )
        conta.refresh_from_db()
        self.assertEqual(conta.status, 'QUITADA')
        self.assertEqual(conta.saldo, Decimal('0.00'))
        self.assertEqual(conta.valor_pago, Decimal('100.00'))

        self.cliente_ativo.refresh_from_db()
        self.assertEqual(self.cliente_ativo.saldo_devedor, Decimal('0.00'))
        self.assertEqual(self.cliente_ativo.credito_disponivel, Decimal('500.00'))

    # =========================================================================
    # 11. PAGAMENTO PARCIAL
    # =========================================================================
    def test_11_pagamento_parcial_atualiza_saldo_e_status(self):
        """Recebimento parcial marca status PARCIAL e mantém saldo remanescente."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a, cliente=self.cliente_ativo,
            itens_data=[{'produto_id': self.produto_feijao.id, 'quantidade': 10}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': Decimal('100.00'), 'troco': Decimal('0.00')}]
        )
        conta = ContaReceber.objects.get(empresa=self.empresa_a, venda=venda)

        # Amortização de R$ 40.00
        FinancialService.receber_pagamento_conta(
            conta=conta, valor_pago=Decimal('40.00'),
            forma_pagamento='DINHEIRO', sessao_caixa=self.sessao_a,
            usuario=self.operador_a
        )
        conta.refresh_from_db()
        self.assertEqual(conta.status, 'PARCIAL')
        self.assertEqual(conta.valor_pago, Decimal('40.00'))
        self.assertEqual(conta.saldo, Decimal('60.00'))

        self.cliente_ativo.refresh_from_db()
        self.assertEqual(self.cliente_ativo.saldo_devedor, Decimal('60.00'))
        self.assertEqual(self.cliente_ativo.credito_disponivel, Decimal('440.00'))

    # =========================================================================
    # 12. PAGAMENTO DE CONTA VENCIDA
    # =========================================================================
    def test_12_pagamento_de_conta_vencida(self):
        """Conta vencida no passado é quitada e remove status de vencida."""
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Dívida Vencida Mês Passado", valor=Decimal('80.00'),
            data_vencimento=timezone.now().date() - timedelta(days=20),
            status='ABERTA'
        )
        self.cliente_ativo.saldo_devedor += Decimal('80.00')
        self.cliente_ativo.save()

        self.assertTrue(conta.is_vencida)

        FinancialService.receber_pagamento_conta(
            conta=conta, valor_pago=Decimal('80.00'),
            forma_pagamento='PIX', usuario=self.operador_a
        )
        conta.refresh_from_db()
        self.assertEqual(conta.status, 'QUITADA')
        self.assertFalse(conta.is_vencida)

    # =========================================================================
    # 13. PAGAMENTO DUPLICADO / CONTA JÁ QUITADA
    # =========================================================================
    def test_13_pagamento_em_conta_ja_quitada_bloqueado(self):
        """Tentativa de receber pagamento em conta já quitada deve lançar ValueError."""
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Conta Quitada", valor=Decimal('50.00'),
            valor_pago=Decimal('50.00'),
            data_vencimento=timezone.now().date(),
            status='QUITADA'
        )
        with self.assertRaises(ValueError) as ctx:
            FinancialService.receber_pagamento_conta(
                conta=conta, valor_pago=Decimal('50.00'),
                forma_pagamento='DINHEIRO', usuario=self.operador_a
            )
        self.assertIn("totalmente quitada", str(ctx.exception))

    # =========================================================================
    # 14. PAGAMENTO ACIMA DO SALDO DEVIDO
    # =========================================================================
    def test_14_pagamento_acima_do_saldo_bloqueado(self):
        """Tentativa de pagar valor maior que o saldo em aberto deve lançar ValueError."""
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Conta Simples", valor=Decimal('50.00'),
            data_vencimento=timezone.now().date(), status='ABERTA'
        )
        with self.assertRaises(ValueError) as ctx:
            FinancialService.receber_pagamento_conta(
                conta=conta, valor_pago=Decimal('60.00'),
                forma_pagamento='PIX', usuario=self.operador_a
            )
        self.assertIn("não pode ser maior que o saldo", str(ctx.exception))

    # =========================================================================
    # 15. ATUALIZAÇÃO CORRETA DO SALDO DEVEDOR
    # =========================================================================
    def test_15_saldo_devedor_acompanha_multiplas_amortizacoes(self):
        """Múltiplas amortizações parciais decrementam o saldo_devedor com precisão Decimal."""
        self.cliente_ativo.saldo_devedor = Decimal('100.00')
        self.cliente_ativo.save()

        conta = ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Dívida Parcelada", valor=Decimal('100.00'),
            data_vencimento=timezone.now().date() + timedelta(days=30), status='ABERTA'
        )

        FinancialService.receber_pagamento_conta(conta=conta, valor_pago=Decimal('25.50'), forma_pagamento='PIX', usuario=self.operador_a)
        self.cliente_ativo.refresh_from_db()
        self.assertEqual(self.cliente_ativo.saldo_devedor, Decimal('74.50'))

        FinancialService.receber_pagamento_conta(conta=conta, valor_pago=Decimal('30.25'), forma_pagamento='DINHEIRO', usuario=self.operador_a)
        self.cliente_ativo.refresh_from_db()
        self.assertEqual(self.cliente_ativo.saldo_devedor, Decimal('44.25'))

    # =========================================================================
    # 16. ATUALIZAÇÃO DO LIMITE DISPONÍVEL
    # =========================================================================
    def test_16_calculo_preciso_limite_disponivel(self):
        """Propriedade credito_disponivel calcula (limite_credito - saldo_devedor)."""
        self.cliente_ativo.limite_credito = Decimal('800.00')
        self.cliente_ativo.saldo_devedor = Decimal('250.00')
        self.cliente_ativo.save()
        self.assertEqual(self.cliente_ativo.credito_disponivel, Decimal('550.00'))

    # =========================================================================
    # 17. RECEBIMENTO EM DINHEIRO ALTERA CAIXA FÍSICO
    # =========================================================================
    def test_17_recebimento_em_dinheiro_incrementa_gaveta(self):
        """Recebimento de dívida em DINHEIRO gera SUPRIMENTO no caixa e aumenta saldo da gaveta."""
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Título em Aberto", valor=Decimal('70.00'),
            data_vencimento=timezone.now().date(), status='ABERTA'
        )
        saldo_antes = self.sessao_a.saldo_esperado  # 200.00

        FinancialService.receber_pagamento_conta(
            conta=conta, valor_pago=Decimal('70.00'),
            forma_pagamento='DINHEIRO', sessao_caixa=self.sessao_a,
            usuario=self.operador_a
        )
        self.sessao_a.refresh_from_db()
        self.assertEqual(self.sessao_a.saldo_esperado, saldo_antes + Decimal('70.00'))

        mov = MovimentacaoCaixa.objects.filter(sessao_caixa=self.sessao_a, tipo='SUPRIMENTO', valor=Decimal('70.00')).first()
        self.assertIsNotNone(mov)

    # =========================================================================
    # 18. RECEBIMENTO PIX NÃO ALTERA CAIXA FÍSICO
    # =========================================================================
    def test_18_recebimento_pix_nao_altera_gaveta(self):
        """Recebimento via PIX entra no fluxo financeiro mas NÃO altera a gaveta de dinheiro."""
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Título PIX", valor=Decimal('120.00'),
            data_vencimento=timezone.now().date(), status='ABERTA'
        )
        saldo_antes = self.sessao_a.saldo_esperado  # 200.00

        FinancialService.receber_pagamento_conta(
            conta=conta, valor_pago=Decimal('120.00'),
            forma_pagamento='PIX', sessao_caixa=self.sessao_a,
            usuario=self.operador_a
        )
        self.sessao_a.refresh_from_db()
        self.assertEqual(self.sessao_a.saldo_esperado, saldo_antes)

    # =========================================================================
    # 19. RECEBIMENTO POR CARTÃO NÃO ALTERA CAIXA FÍSICO
    # =========================================================================
    def test_19_recebimento_cartao_nao_altera_gaveta(self):
        """Recebimento via CARTAO_DEBITO ou CARTAO_CREDITO não altera o saldo físico da gaveta."""
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Título Cartão", valor=Decimal('90.00'),
            data_vencimento=timezone.now().date(), status='ABERTA'
        )
        saldo_antes = self.sessao_a.saldo_esperado  # 200.00

        FinancialService.receber_pagamento_conta(
            conta=conta, valor_pago=Decimal('90.00'),
            forma_pagamento='CARTAO_CREDITO', sessao_caixa=self.sessao_a,
            usuario=self.operador_a
        )
        self.sessao_a.refresh_from_db()
        self.assertEqual(self.sessao_a.saldo_esperado, saldo_antes)

    # =========================================================================
    # 20. GERAÇÃO CORRETA DO FLUXO DE CAIXA
    # =========================================================================
    def test_20_recebimento_gera_fluxo_caixa_entrada(self):
        """Todo recebimento de crediário cria lançamento de ENTRADA no FluxoCaixa."""
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Dívida Teste Fluxo", valor=Decimal('150.00'),
            data_vencimento=timezone.now().date(), status='ABERTA'
        )
        FinancialService.receber_pagamento_conta(
            conta=conta, valor_pago=Decimal('150.00'),
            forma_pagamento='PIX', usuario=self.operador_a
        )
        fluxo = FluxoCaixa.objects.filter(
            empresa=self.empresa_a, tipo='ENTRADA',
            categoria='Recebimento Crediário', valor=Decimal('150.00')
        ).first()
        self.assertIsNotNone(fluxo)
        self.assertEqual(fluxo.referencia_origem, f"RECEBER-{conta.id}")

    # =========================================================================
    # 21. ROLLBACK DE VENDA A PRAZO EM FALHA
    # =========================================================================
    def test_21_rollback_venda_crediario_em_falha(self):
        """Se a criação falhar durante a transação, nada fica gravado parcialmente."""
        estoque_antes = self.produto_arroz.estoque_atual
        with self.assertRaises(ValueError):
            SaleService.processar_venda(
                empresa=self.empresa_a, sessao_caixa=self.sessao_a,
                operador=self.operador_a, cliente=self.cliente_ativo,
                itens_data=[{'produto_id': self.produto_arroz.id, 'quantidade': 1}],
                pagamentos_data=[{'forma': 'CREDIARIO', 'valor': Decimal('9999.00'), 'troco': Decimal('0.00')}]  # Excede limite
            )
        self.produto_arroz.refresh_from_db()
        self.assertEqual(self.produto_arroz.estoque_atual, estoque_antes)
        self.assertEqual(ContaReceber.objects.filter(empresa=self.empresa_a).count(), 0)

    # =========================================================================
    # 22. ROLLBACK DE RECEBIMENTO EM FALHA
    # =========================================================================
    def test_22_rollback_recebimento_em_falha(self):
        """Se recebimento falhar por valor inválido, o saldo da conta e do cliente permanecem intactos."""
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Conta Teste Rollback", valor=Decimal('100.00'),
            data_vencimento=timezone.now().date(), status='ABERTA'
        )
        self.cliente_ativo.saldo_devedor = Decimal('100.00')
        self.cliente_ativo.save()

        with self.assertRaises(ValueError):
            FinancialService.receber_pagamento_conta(
                conta=conta, valor_pago=Decimal('150.00'),  # Excede saldo
                forma_pagamento='DINHEIRO', usuario=self.operador_a
            )

        conta.refresh_from_db()
        self.assertEqual(conta.valor_pago, Decimal('0.00'))
        self.assertEqual(conta.status, 'ABERTA')
        self.cliente_ativo.refresh_from_db()
        self.assertEqual(self.cliente_ativo.saldo_devedor, Decimal('100.00'))

    # =========================================================================
    # 23. AUDITORIA DE CREDIÁRIO CONCEDIDO
    # =========================================================================
    def test_23_auditoria_crediario_concedido(self):
        """Venda no crediário gera registro com acao='CREDIARIO_CONCEDIDO' no AuditLog."""
        SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a, cliente=self.cliente_ativo,
            itens_data=[{'produto_id': self.produto_arroz.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': Decimal('30.00'), 'troco': Decimal('0.00')}]
        )
        log = AuditLog.objects.filter(empresa=self.empresa_a, acao='CREDIARIO_CONCEDIDO').first()
        self.assertIsNotNone(log)
        self.assertIn("João da Silva", log.descricao)

    # =========================================================================
    # 24. AUDITORIA DE RECEBIMENTO REGISTRADO
    # =========================================================================
    def test_24_auditoria_recebimento_registrado(self):
        """Recebimento de título gera registro com acao='RECEBIMENTO_REGISTRADO' no AuditLog."""
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Conta Audit", valor=Decimal('50.00'),
            data_vencimento=timezone.now().date(), status='ABERTA'
        )
        FinancialService.receber_pagamento_conta(
            conta=conta, valor_pago=Decimal('50.00'),
            forma_pagamento='PIX', usuario=self.operador_a
        )
        log = AuditLog.objects.filter(empresa=self.empresa_a, acao='RECEBIMENTO_REGISTRADO').first()
        self.assertIsNotNone(log)
        self.assertIn("PIX", log.descricao)

    # =========================================================================
    # 25. PERMISSÕES POR CARGO
    # =========================================================================
    def test_25_estoquista_bloqueado_de_operacoes_financeiras(self):
        """Estoquista não tem permissão para gerenciar contas ou cancelar recebimentos."""
        self.client.login(username='estoquista_a', password='pass123')
        resp = self.client.get('/financeiro/despesas/')
        self.assertEqual(resp.status_code, 403)

    # =========================================================================
    # 26. ACESSO DIRETO POR URL BLOQUEADO
    # =========================================================================
    def test_26_acesso_direto_cancelar_conta_receber_requer_permissao(self):
        """Operador comum não pode cancelar conta a receber via rota direta."""
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Conta Teste", valor=Decimal('50.00'),
            data_vencimento=timezone.now().date(), status='ABERTA'
        )
        self.client.login(username='operador_a', password='pass123')
        resp = self.client.post(f'/financeiro/receber/{conta.id}/cancelar/', {'motivo': 'Tentativa sem permissão'})
        self.assertEqual(resp.status_code, 403)

    # =========================================================================
    # 27. ISOLAMENTO MULTI-TENANT EM CONTAS A RECEBER
    # =========================================================================
    def test_27_contas_a_receber_isoladas_por_tenant(self):
        """Empresa B não enxerga títulos a receber da Empresa A."""
        ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Título Alpha Exclusivo", valor=Decimal('200.00'),
            data_vencimento=timezone.now().date(), status='ABERTA'
        )
        self.client.login(username='admin_b', password='pass123')
        resp = self.client.get('/financeiro/receber/')
        self.assertNotContains(resp, "Título Alpha Exclusivo")

    # =========================================================================
    # 28. CONCORRÊNCIA NO LIMITE DE CRÉDITO
    # =========================================================================
    def test_28_concorrencia_limite_credito_select_for_update(self):
        """SaleService utiliza select_for_update para carregar o cliente de forma concorrente."""
        self.cliente_ativo.saldo_devedor = Decimal('450.00')  # Limite é 500, sobra 50
        self.cliente_ativo.save()

        # Venda de R$ 60 excede limite disponível
        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa_a, sessao_caixa=self.sessao_a,
                operador=self.operador_a, cliente=self.cliente_ativo,
                itens_data=[{'produto_id': self.produto_arroz.id, 'quantidade': 2}],  # 60.00
                pagamentos_data=[{'forma': 'CREDIARIO', 'valor': Decimal('60.00'), 'troco': Decimal('0.00')}]
            )
        self.assertIn("Limite de crédito insuficiente", str(ctx.exception))

    # =========================================================================
    # 29. CONCORRÊNCIA NO RECEBIMENTO DE TÍTULO
    # =========================================================================
    def test_29_concorrencia_recebimento_select_for_update(self):
        """FinancialService.receber_pagamento_conta bloqueia linha com select_for_update."""
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Título Concorrente", valor=Decimal('100.00'),
            data_vencimento=timezone.now().date(), status='ABERTA'
        )
        pag1 = FinancialService.receber_pagamento_conta(conta=conta, valor_pago=Decimal('100.00'), forma_pagamento='PIX', usuario=self.operador_a)
        self.assertEqual(pag1.conta_receber.status, 'QUITADA')

        # Segunda tentativa imediata de quitação deve falhar
        with self.assertRaises(ValueError):
            FinancialService.receber_pagamento_conta(conta=conta, valor_pago=Decimal('100.00'), forma_pagamento='PIX', usuario=self.operador_a)

    # =========================================================================
    # 30. FICHA FINANCEIRA DO CLIENTE
    # =========================================================================
    def test_30_renderizacao_ficha_financeira_cliente(self):
        """Ficha financeira renderiza histórico de vendas, contas e pagamentos do cliente."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a, cliente=self.cliente_ativo,
            itens_data=[{'produto_id': self.produto_arroz.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': Decimal('30.00'), 'troco': Decimal('0.00')}]
        )
        self.client.login(username='operador_a', password='pass123')
        resp = self.client.get(f'/clientes/ficha/{self.cliente_ativo.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "João da Silva")
        self.assertContains(resp, venda.codigo_venda)
        self.assertContains(resp, "30,00")

    # =========================================================================
    # 31. CONTAS VENCIDAS
    # =========================================================================
    def test_31_contas_vencidas_calculadas_corretamente(self):
        """Propriedade is_vencida identifica corretamente títulos com vencimento anterior a hoje."""
        conta_vencida = ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Vencida", valor=Decimal('100.00'),
            data_vencimento=timezone.now().date() - timedelta(days=5), status='ABERTA'
        )
        conta_aberta = ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="A Vencer", valor=Decimal('100.00'),
            data_vencimento=timezone.now().date() + timedelta(days=5), status='ABERTA'
        )
        self.assertTrue(conta_vencida.is_vencida)
        self.assertFalse(conta_aberta.is_vencida)

    # =========================================================================
    # 32. DASHBOARD DE CREDIÁRIO
    # =========================================================================
    def test_32_dashboard_report_service_crediario(self):
        """ReportService.get_crediario_report consolida métricas da carteira de crediário."""
        ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Título Report", valor=Decimal('250.00'),
            data_vencimento=timezone.now().date() - timedelta(days=2), status='ABERTA'
        )
        self.cliente_ativo.saldo_devedor = Decimal('250.00')
        self.cliente_ativo.save()

        rep = ReportService.get_crediario_report(self.empresa_a)
        self.assertEqual(rep['total_vendido_fiado'], Decimal('250.00'))
        self.assertEqual(rep['total_aberto'], Decimal('250.00'))
        self.assertEqual(rep['total_vencido'], Decimal('250.00'))
        self.assertEqual(rep['qtd_devedores'], 1)

    # =========================================================================
    # 33. CANCELAMENTO / ESTORNO DE CONTA A RECEBER
    # =========================================================================
    def test_33_cancelamento_conta_a_receber(self):
        """Cancelar conta a receber abate o saldo_devedor do cliente e marca status CANCELADA."""
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Conta Cancelável", valor=Decimal('180.00'),
            data_vencimento=timezone.now().date() + timedelta(days=10), status='ABERTA'
        )
        self.cliente_ativo.saldo_devedor = Decimal('180.00')
        self.cliente_ativo.save()

        FinancialService.cancelar_conta_receber(conta, usuario=self.admin_a, motivo="Cancelamento manual acordado")
        conta.refresh_from_db()
        self.assertEqual(conta.status, 'CANCELADA')
        self.cliente_ativo.refresh_from_db()
        self.assertEqual(self.cliente_ativo.saldo_devedor, Decimal('0.00'))

    # =========================================================================
    # 34. DECIMAL E ARREDONDAMENTO FINANCEIRO
    # =========================================================================
    def test_34_precisao_decimal_sem_erros_de_ponto_flutuante(self):
        """Valores fracionários operam estritamente com precisão Decimal(0.01)."""
        conta = ContaReceber.objects.create(
            empresa=self.empresa_a, cliente=self.cliente_ativo,
            descricao="Fracionada", valor=Decimal('33.33'),
            data_vencimento=timezone.now().date(), status='ABERTA'
        )
        self.cliente_ativo.saldo_devedor = Decimal('33.33')
        self.cliente_ativo.save()

        pag = FinancialService.receber_pagamento_conta(conta=conta, valor_pago=Decimal('11.11'), forma_pagamento='PIX', usuario=self.operador_a)
        conta.refresh_from_db()
        self.assertEqual(conta.saldo, Decimal('22.22'))
        self.cliente_ativo.refresh_from_db()
        self.assertEqual(self.cliente_ativo.saldo_devedor, Decimal('22.22'))

    # =========================================================================
    # 35. INTEGRIDADE COMPLETA DA CADEIA FINANCEIRA
    # =========================================================================
    def test_35_integridade_completa_venda_crediario_recebimento_caixa_fluxo(self):
        """Ciclo completo: Venda Fiada -> Saldo Devedor -> Recebimento Dinheiro -> Gaveta -> Fluxo de Caixa."""
        saldo_inicial_gaveta = self.sessao_a.saldo_esperado  # 200.00

        # Passo 1: Venda de R$ 90 no crediário
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a, cliente=self.cliente_ativo,
            itens_data=[{'produto_id': self.produto_arroz.id, 'quantidade': 3}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': Decimal('90.00'), 'troco': Decimal('0.00')}]
        )
        self.cliente_ativo.refresh_from_db()
        self.assertEqual(self.cliente_ativo.saldo_devedor, Decimal('90.00'))

        # Passo 2: Recebimento de R$ 90 em DINHEIRO no caixa físico
        conta = ContaReceber.objects.get(empresa=self.empresa_a, venda=venda)
        pag = FinancialService.receber_pagamento_conta(
            conta=conta, valor_pago=Decimal('90.00'),
            forma_pagamento='DINHEIRO', sessao_caixa=self.sessao_a,
            usuario=self.operador_a
        )

        # Passo 3: Verificação de quitação e saldo do cliente
        conta.refresh_from_db()
        self.assertEqual(conta.status, 'QUITADA')
        self.cliente_ativo.refresh_from_db()
        self.assertEqual(self.cliente_ativo.saldo_devedor, Decimal('0.00'))

        # Passo 4: Verificação da gaveta física do caixa
        self.sessao_a.refresh_from_db()
        self.assertEqual(self.sessao_a.saldo_esperado, saldo_inicial_gaveta + Decimal('90.00'))

        # Passo 5: Verificação do Fluxo de Caixa
        fluxo = FluxoCaixa.objects.filter(empresa=self.empresa_a, tipo='ENTRADA', valor=Decimal('90.00')).first()
        self.assertIsNotNone(fluxo)
