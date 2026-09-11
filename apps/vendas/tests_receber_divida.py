from decimal import Decimal
from datetime import date, timedelta
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.produtos.models import Produto, Categoria
from apps.clientes.models import Cliente
from apps.caixas.models import Caixa, SessaoCaixa
from apps.caixas.services import CashService
from apps.financeiro.models import ContaReceber, PagamentoContaReceber, FluxoCaixa
from apps.vendas.models import Venda, ItemVenda, PagamentoVenda
from apps.vendas.services import SaleService


class ReceberDividaTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            razao_social="Empresa Teste Ltda",
            nome_fantasia="Empresa Teste",
            cnpj="12345678000199"
        )

        self.operador = Usuario.objects.create_user(
            username="operador_teste",
            password="password123",
            empresa=self.empresa,
            cargo="OPERADOR"
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.operador)

        self.caixa = Caixa.objects.create(
            empresa=self.empresa,
            nome="Caixa 1",
            codigo_identificador="CX01"
        )
        self.sessao_caixa = CashService.abrir_caixa(
            caixa=self.caixa,
            operador=self.operador,
            saldo_inicial=Decimal('100.00')
        )

        self.categoria = Categoria.objects.create(
            empresa=self.empresa,
            nome="Geral"
        )
        self.produto = Produto.objects.create(
            empresa=self.empresa,
            nome="Produto Teste",
            codigo_barras="7891234567890",
            sku="PROD-001",
            categoria=self.categoria,
            preco_venda=Decimal('20.00'),
            preco_custo=Decimal('10.00'),
            estoque_atual=Decimal('50.000'),
            ativo=True
        )

        self.cliente_carlin = Cliente.objects.create(
            empresa=self.empresa,
            nome="Carlin",
            cpf_cnpj="12345678901",
            limite_credito=Decimal('1000.00')
        )

        self.cliente_jonatas = Cliente.objects.create(
            empresa=self.empresa,
            nome="Jonatas",
            cpf_cnpj="98765432100",
            limite_credito=Decimal('1000.00')
        )

    def _criar_contas_carlin(self, valores):
        contas = []
        hoje = date.today()
        for i, val in enumerate(valores):
            c = ContaReceber.objects.create(
                empresa=self.empresa,
                cliente=self.cliente_carlin,
                descricao=f"Conta {i+1} Carlin",
                valor=Decimal(str(val)),
                valor_original=Decimal(str(val)),
                valor_pago=Decimal('0.00'),
                data_vencimento=hoje + timedelta(days=i),
                status='ABERTA'
            )
            contas.append(c)
        return contas

    # 1. Dívida Simples Sem Abatimento (pagamento total da dívida)
    def test_01_divida_simples_sem_abatimento(self):
        self._criar_contas_carlin(['55.50'])
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('55.50'),
            'valor_abatimento': Decimal('0.00'),
            'motivo_abatimento': ''
        }
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('55.50'), 'troco': Decimal('0.00')}
        ]

        res = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao_caixa,
            itens_data=[],
            pagamentos_data=pagamentos_data,
            cliente=self.cliente_carlin,
            recebimento_divida=recebimento_divida
        )

        self.assertEqual(res['status'], 'CONCLUIDA')
        self.assertEqual(Decimal(str(res['total_liquidado'])), Decimal('55.50'))
        conta = ContaReceber.objects.get(cliente=self.cliente_carlin)
        self.assertEqual(conta.status, 'QUITADA')
        self.assertEqual(conta.saldo, Decimal('0.00'))

    # 2. Dívida Parcial Sem Abatimento (saldo restante correto)
    def test_02_divida_parcial_sem_abatimento(self):
        self._criar_contas_carlin(['100.00'])
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('40.00'),
            'valor_abatimento': Decimal('0.00'),
            'motivo_abatimento': ''
        }
        pagamentos_data = [
            {'forma': 'PIX', 'valor': Decimal('40.00'), 'troco': Decimal('0.00')}
        ]

        res = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao_caixa,
            itens_data=[],
            pagamentos_data=pagamentos_data,
            cliente=self.cliente_carlin,
            recebimento_divida=recebimento_divida
        )

        self.assertEqual(res['status'], 'CONCLUIDA')
        conta = ContaReceber.objects.get(cliente=self.cliente_carlin)
        self.assertEqual(conta.status, 'PARCIAL')
        self.assertEqual(conta.saldo, Decimal('60.00'))

    # 3. Dívida Com Abatimento em Valor R$ (Ex: 55,50 - 10,00 = 45,50 a pagar, liquidando 55,50)
    def test_03_divida_com_abatimento_valor_reais(self):
        self._criar_contas_carlin(['55.50'])
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('45.50'),
            'valor_abatimento': Decimal('10.00'),
            'motivo_abatimento': 'Desconto promocional'
        }
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('45.50'), 'troco': Decimal('0.00')}
        ]

        res = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao_caixa,
            itens_data=[],
            pagamentos_data=pagamentos_data,
            cliente=self.cliente_carlin,
            recebimento_divida=recebimento_divida
        )

        self.assertEqual(res['status'], 'CONCLUIDA')
        self.assertEqual(Decimal(str(res['valor_pago'])), Decimal('45.50'))
        self.assertEqual(Decimal(str(res['valor_abatimento'])), Decimal('10.00'))
        self.assertEqual(Decimal(str(res['total_liquidado'])), Decimal('55.50'))
        conta = ContaReceber.objects.get(cliente=self.cliente_carlin)
        self.assertEqual(conta.status, 'QUITADA')
        self.assertEqual(conta.saldo, Decimal('0.00'))

    # 4. Dívida Com Abatimento Percentual % (100.00 - 10% = 90.00 a pagar, liquidando 100.00)
    def test_04_divida_com_abatimento_percentual(self):
        self._criar_contas_carlin(['100.00'])
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('90.00'),
            'valor_abatimento': Decimal('10.00'),
            'motivo_abatimento': '10% de abatimento'
        }
        pagamentos_data = [
            {'forma': 'CARTAO_CREDITO', 'valor': Decimal('90.00'), 'troco': Decimal('0.00')}
        ]

        res = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao_caixa,
            itens_data=[],
            pagamentos_data=pagamentos_data,
            cliente=self.cliente_carlin,
            recebimento_divida=recebimento_divida
        )

        conta = ContaReceber.objects.get(cliente=self.cliente_carlin)
        self.assertEqual(conta.status, 'QUITADA')
        self.assertEqual(conta.saldo, Decimal('0.00'))

    # 5. Quitar Dívida Com Abatimento (Ex: 80 - 20 = 60 a pagar, liquidando 80)
    def test_05_quitar_divida_com_abatimento(self):
        self._criar_contas_carlin(['80.00'])
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('60.00'),
            'valor_abatimento': Decimal('20.00'),
            'motivo_abatimento': 'Quitação de dívida'
        }
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('60.00'), 'troco': Decimal('0.00')}
        ]

        res = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao_caixa,
            itens_data=[],
            pagamentos_data=pagamentos_data,
            cliente=self.cliente_carlin,
            recebimento_divida=recebimento_divida
        )

        conta = ContaReceber.objects.get(cliente=self.cliente_carlin)
        self.assertEqual(conta.status, 'QUITADA')
        self.assertEqual(conta.saldo, Decimal('0.00'))

    # 6. Baixa FIFO com Múltiplas Contas (3 contas de 50; paga 75 -> quita conta 1, paga 25 da conta 2, conta 3 intacta)
    def test_06_baixa_fifo_multiplas_contas(self):
        contas = self._criar_contas_carlin(['50.00', '50.00', '50.00'])
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('75.00'),
            'valor_abatimento': Decimal('0.00'),
            'motivo_abatimento': ''
        }
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('75.00'), 'troco': Decimal('0.00')}
        ]

        SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao_caixa,
            itens_data=[],
            pagamentos_data=pagamentos_data,
            cliente=self.cliente_carlin,
            recebimento_divida=recebimento_divida
        )

        c1 = ContaReceber.objects.get(id=contas[0].id)
        c2 = ContaReceber.objects.get(id=contas[1].id)
        c3 = ContaReceber.objects.get(id=contas[2].id)

        self.assertEqual(c1.status, 'QUITADA')
        self.assertEqual(c1.saldo, Decimal('0.00'))

        self.assertEqual(c2.status, 'PARCIAL')
        self.assertEqual(c2.saldo, Decimal('25.00'))

        self.assertEqual(c3.status, 'ABERTA')
        self.assertEqual(c3.saldo, Decimal('50.00'))

    # 7. Baixa FIFO com Abatimento
    def test_07_baixa_fifo_com_abatimento(self):
        contas = self._criar_contas_carlin(['50.00', '50.00'])
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('80.00'),
            'valor_abatimento': Decimal('20.00'),
            'motivo_abatimento': 'Acordo'
        }
        pagamentos_data = [
            {'forma': 'PIX', 'valor': Decimal('80.00'), 'troco': Decimal('0.00')}
        ]

        SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao_caixa,
            itens_data=[],
            pagamentos_data=pagamentos_data,
            cliente=self.cliente_carlin,
            recebimento_divida=recebimento_divida
        )

        c1 = ContaReceber.objects.get(id=contas[0].id)
        c2 = ContaReceber.objects.get(id=contas[1].id)
        self.assertEqual(c1.status, 'QUITADA')
        self.assertEqual(c2.status, 'QUITADA')
        self.assertEqual(c1.saldo, Decimal('0.00'))
        self.assertEqual(c2.saldo, Decimal('0.00'))

    # 8. Rejeição: Abatimento Maior que a Dívida
    def test_08_rejeicao_abatimento_maior_que_divida(self):
        self._criar_contas_carlin(['50.00'])
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('0.00'),
            'valor_abatimento': Decimal('60.00'),
            'motivo_abatimento': 'Invalido'
        }
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('0.00'), 'troco': Decimal('0.00')}
        ]

        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa,
                operador=self.operador,
                sessao_caixa=self.sessao_caixa,
                itens_data=[],
                pagamentos_data=pagamentos_data,
                cliente=self.cliente_carlin,
                recebimento_divida=recebimento_divida
            )
        self.assertIn("não pode ser superior à dívida", str(ctx.exception))

    # 9. Rejeição: Valor Pago Maior que Dívida Consolidada
    def test_09_rejeicao_valor_pago_maior_que_divida(self):
        self._criar_contas_carlin(['50.00'])
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('60.00'),
            'valor_abatimento': Decimal('0.00'),
            'motivo_abatimento': ''
        }
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('60.00'), 'troco': Decimal('0.00')}
        ]

        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa,
                operador=self.operador,
                sessao_caixa=self.sessao_caixa,
                itens_data=[],
                pagamentos_data=pagamentos_data,
                cliente=self.cliente_carlin,
                recebimento_divida=recebimento_divida
            )
        self.assertIn("não pode ser superior à dívida", str(ctx.exception))

    # 10. Rejeição: Total Liquidado Maior que Dívida Consolidada
    def test_10_rejeicao_total_liquidado_maior_que_divida(self):
        self._criar_contas_carlin(['50.00'])
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('45.00'),
            'valor_abatimento': Decimal('10.00'),
            'motivo_abatimento': 'Invalido'
        }
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('45.00'), 'troco': Decimal('0.00')}
        ]

        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa,
                operador=self.operador,
                sessao_caixa=self.sessao_caixa,
                itens_data=[],
                pagamentos_data=pagamentos_data,
                cliente=self.cliente_carlin,
                recebimento_divida=recebimento_divida
            )
        self.assertIn("não pode ser superior à dívida", str(ctx.exception))

    # 11. Rejeição: Cliente Incompatível no Payload
    def test_11_rejeicao_cliente_incompativel(self):
        self._criar_contas_carlin(['50.00'])
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('50.00'),
            'valor_abatimento': Decimal('0.00'),
            'motivo_abatimento': ''
        }
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('50.00'), 'troco': Decimal('0.00')}
        ]

        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa,
                operador=self.operador,
                sessao_caixa=self.sessao_caixa,
                itens_data=[],
                pagamentos_data=pagamentos_data,
                cliente=self.cliente_jonatas,
                recebimento_divida=recebimento_divida
            )
        self.assertIn("deve ser o mesmo cliente da dívida", str(ctx.exception))

    # 12. Rejeição: Cliente Sem Dívida
    def test_12_rejeicao_cliente_sem_divida(self):
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('50.00'),
            'valor_abatimento': Decimal('0.00'),
            'motivo_abatimento': ''
        }
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('50.00'), 'troco': Decimal('0.00')}
        ]

        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa,
                operador=self.operador,
                sessao_caixa=self.sessao_caixa,
                itens_data=[],
                pagamentos_data=pagamentos_data,
                cliente=self.cliente_carlin,
                recebimento_divida=recebimento_divida
            )
        self.assertIn("não pode ser superior à dívida", str(ctx.exception))

    # 13. Rejeição: Venda sem itens e sem recebimento de dívida
    def test_13_rejeicao_venda_vazia(self):
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('10.00'), 'troco': Decimal('0.00')}
        ]

        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa,
                operador=self.operador,
                sessao_caixa=self.sessao_caixa,
                itens_data=[],
                pagamentos_data=pagamentos_data,
                cliente=self.cliente_carlin,
                recebimento_divida=None
            )
        self.assertIn("precisa conter ao menos um item", str(ctx.exception))

    # 14. Checkout Misto: Produtos + Dívida no mesmo checkout com 1 pagamento
    def test_14_checkout_misto_produtos_mais_divida_um_pagamento(self):
        self._criar_contas_carlin(['50.00'])
        itens_data = [
            {'produto_id': self.produto.id, 'quantidade': Decimal('2'), 'preco_venda': Decimal('20.00')}
        ]
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('50.00'),
            'valor_abatimento': Decimal('0.00'),
            'motivo_abatimento': ''
        }
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('90.00'), 'troco': Decimal('0.00')}
        ]

        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao_caixa,
            itens_data=itens_data,
            pagamentos_data=pagamentos_data,
            cliente=self.cliente_carlin,
            recebimento_divida=recebimento_divida
        )

        self.assertIsInstance(venda, Venda)
        self.assertEqual(venda.total, Decimal('40.00'))
        self.produto.refresh_from_db()
        self.assertEqual(self.produto.estoque_atual, Decimal('48.000'))
        conta = ContaReceber.objects.get(cliente=self.cliente_carlin)
        self.assertEqual(conta.status, 'QUITADA')
        self.assertEqual(conta.saldo, Decimal('0.00'))

    # 15. Checkout Misto: Produtos + Dívida com múltiplos pagamentos (Dinheiro + PIX + Débito)
    def test_15_checkout_misto_multiplos_pagamentos(self):
        self._criar_contas_carlin(['10.00'])
        itens_data = [
            {'produto_id': self.produto.id, 'quantidade': Decimal('1'), 'preco_venda': Decimal('20.00')}
        ]
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('10.00'),
            'valor_abatimento': Decimal('0.00'),
            'motivo_abatimento': ''
        }
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('10.00'), 'troco': Decimal('0.00')}
        ]

        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao_caixa,
            itens_data=itens_data,
            pagamentos_data=[
                {'forma': 'DINHEIRO', 'valor': Decimal('10.00'), 'troco': Decimal('0.00')},
                {'forma': 'PIX', 'valor': Decimal('10.00'), 'troco': Decimal('0.00')},
                {'forma': 'CARTAO_DEBITO', 'valor': Decimal('10.00'), 'troco': Decimal('0.00')}
            ],
            cliente=self.cliente_carlin,
            recebimento_divida=recebimento_divida
        )

        self.assertIsInstance(venda, Venda)
        conta = ContaReceber.objects.get(cliente=self.cliente_carlin)
        self.assertEqual(conta.status, 'QUITADA')

    # 16. Validação de Caixa: Abatimento NÃO entra no caixa / Pagamento reflete valor líquido
    def test_16_validacao_caixa_abatimento_nao_entra_no_caixa(self):
        self._criar_contas_carlin(['100.00'])
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('75.00'),
            'valor_abatimento': Decimal('25.00'),
            'motivo_abatimento': 'Desconto'
        }
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('75.00'), 'troco': Decimal('0.00')}
        ]

        res = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao_caixa,
            itens_data=[],
            pagamentos_data=pagamentos_data,
            cliente=self.cliente_carlin,
            recebimento_divida=recebimento_divida
        )

        pgto = PagamentoContaReceber.objects.filter(conta_receber__cliente=self.cliente_carlin).first()
        self.assertEqual(pgto.valor, Decimal('75.00'))
        self.assertEqual(pgto.valor_abatimento, Decimal('25.00'))

    # 17. Validação de Estoque: Recebimento de dívida pura NÃO altera estoque
    def test_17_divida_pura_nao_altera_estoque(self):
        self._criar_contas_carlin(['50.00'])
        estoque_antes = self.produto.estoque_atual
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('50.00'),
            'valor_abatimento': Decimal('0.00'),
            'motivo_abatimento': ''
        }
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('50.00'), 'troco': Decimal('0.00')}
        ]

        SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao_caixa,
            itens_data=[],
            pagamentos_data=pagamentos_data,
            cliente=self.cliente_carlin,
            recebimento_divida=recebimento_divida
        )

        self.produto.refresh_from_db()
        self.assertEqual(self.produto.estoque_atual, estoque_antes)

    # 18. Validação de Venda: Recebimento de dívida pura NÃO cria ItemVenda fictício
    def test_18_divida_pura_nao_cria_item_venda_nem_venda(self):
        self._criar_contas_carlin(['50.00'])
        itens_antes = ItemVenda.objects.count()
        vendas_antes = Venda.objects.count()
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('50.00'),
            'valor_abatimento': Decimal('0.00'),
            'motivo_abatimento': ''
        }
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('50.00'), 'troco': Decimal('0.00')}
        ]

        res = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao_caixa,
            itens_data=[],
            pagamentos_data=pagamentos_data,
            cliente=self.cliente_carlin,
            recebimento_divida=recebimento_divida
        )

        self.assertEqual(ItemVenda.objects.count(), itens_antes)
        self.assertEqual(Venda.objects.count(), vendas_antes)
        self.assertEqual(res['tipo'], 'RECEBIMENTO_DIVIDA')

    # 19. Endpoint ContasPendentesClienteAPIView retorna total_divida e lista de contas
    def test_19_api_contas_pendentes_cliente(self):
        self._criar_contas_carlin(['30.00', '45.00'])
        url = f'/api/v1/financeiro/contas-pendentes/{self.cliente_carlin.id}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(Decimal(str(data['total_divida'])), Decimal('75.00'))
        self.assertEqual(len(data['contas']), 2)

    # 20. Endpoint de Vendas / Processar Venda via API - Dívida Pura
    def test_20_api_processar_divida_pura(self):
        self._criar_contas_carlin(['55.50'])
        url = '/api/v1/vendas/'
        payload = {
            'sessao_caixa_id': self.sessao_caixa.id,
            'cliente_id': self.cliente_carlin.id,
            'itens': [],
            'recebimento_divida': {
                'cliente_id': self.cliente_carlin.id,
                'valor_pago': '45.50',
                'valor_abatimento': '10.00',
                'motivo_abatimento': 'Desconto'
            },
            'pagamentos': [
                {'forma': 'DINHEIRO', 'valor': '45.50', 'troco': '0.00'}
            ]
        }
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'CONCLUIDA')

    # 21. Endpoint de Vendas / Processar Venda via API - Misto
    def test_21_api_processar_venda_mista(self):
        self._criar_contas_carlin(['50.00'])
        url = '/api/v1/vendas/'
        payload = {
            'sessao_caixa_id': self.sessao_caixa.id,
            'cliente_id': self.cliente_carlin.id,
            'itens': [
                {'produto_id': self.produto.id, 'quantidade': '1', 'preco_venda': '20.00'}
            ],
            'recebimento_divida': {
                'cliente_id': self.cliente_carlin.id,
                'valor_pago': '50.00',
                'valor_abatimento': '0.00',
                'motivo_abatimento': ''
            },
            'pagamentos': [
                {'forma': 'DINHEIRO', 'valor': '70.00', 'troco': '0.00'}
            ]
        }
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('id', response.data)

    # 22. Transação Atômica: Se ocorrer erro na finalização, toda a operação faz rollback
    def test_22_transacao_atomica_rollback(self):
        self._criar_contas_carlin(['50.00'])
        estoque_antes = self.produto.estoque_atual
        itens_data = [
            {'produto_id': self.produto.id, 'quantidade': Decimal('1'), 'preco_venda': Decimal('20.00')}
        ]
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('50.00'),
            'valor_abatimento': Decimal('0.00'),
            'motivo_abatimento': ''
        }
        # Pagamento com valor insuficiente gera erro de saldo
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('30.00'), 'troco': Decimal('0.00')}
        ]

        with self.assertRaises(ValueError):
            SaleService.processar_venda(
                empresa=self.empresa,
                operador=self.operador,
                sessao_caixa=self.sessao_caixa,
                itens_data=itens_data,
                pagamentos_data=pagamentos_data,
                cliente=self.cliente_carlin,
                recebimento_divida=recebimento_divida
            )

        self.produto.refresh_from_db()
        self.assertEqual(self.produto.estoque_atual, estoque_antes)
        conta = ContaReceber.objects.get(cliente=self.cliente_carlin)
        self.assertEqual(conta.status, 'ABERTA')
        self.assertEqual(conta.saldo, Decimal('50.00'))

    # 23. Desconto do Produto NÃO altera Valor da Dívida
    def test_23_desconto_produto_isolado_da_divida(self):
        self._criar_contas_carlin(['50.00'])
        itens_data = [
            {'produto_id': self.produto.id, 'quantidade': Decimal('1'), 'preco_venda': Decimal('20.00')}
        ]
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('50.00'),
            'valor_abatimento': Decimal('0.00'),
            'motivo_abatimento': ''
        }
        # Desconto de 5.00 na venda -> total venda = 15.00 + divida 50.00 = 65.00
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('65.00'), 'troco': Decimal('0.00')}
        ]

        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao_caixa,
            itens_data=itens_data,
            pagamentos_data=pagamentos_data,
            cliente=self.cliente_carlin,
            desconto=Decimal('5.00'),
            recebimento_divida=recebimento_divida
        )

        self.assertEqual(venda.subtotal, Decimal('20.00'))
        self.assertEqual(venda.desconto, Decimal('5.00'))
        self.assertEqual(venda.total, Decimal('15.00'))
        conta = ContaReceber.objects.get(cliente=self.cliente_carlin)
        self.assertEqual(conta.status, 'QUITADA')

    # 24. Atualização progressiva de status: ABERTA -> PARCIAL -> QUITADA
    def test_24_ciclo_de_vida_status_conta(self):
        contas = self._criar_contas_carlin(['100.00'])
        c = contas[0]
        self.assertEqual(c.status, 'ABERTA')

        # 1o pagamento parcial: 30.00
        SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao_caixa,
            itens_data=[],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('30.00'), 'troco': Decimal('0.00')}],
            cliente=self.cliente_carlin,
            recebimento_divida={
                'cliente_id': self.cliente_carlin.id,
                'valor_pago': Decimal('30.00'),
                'valor_abatimento': Decimal('0.00'),
                'motivo_abatimento': ''
            }
        )

        c.refresh_from_db()
        self.assertEqual(c.status, 'PARCIAL')
        self.assertEqual(c.saldo, Decimal('70.00'))

        # 2o pagamento com abatimento quitando o restante: paga 50, abate 20
        SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao_caixa,
            itens_data=[],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('50.00'), 'troco': Decimal('0.00')}],
            cliente=self.cliente_carlin,
            recebimento_divida={
                'cliente_id': self.cliente_carlin.id,
                'valor_pago': Decimal('50.00'),
                'valor_abatimento': Decimal('20.00'),
                'motivo_abatimento': 'Acordo Final'
            }
        )

        c.refresh_from_db()
        self.assertEqual(c.status, 'QUITADA')
        self.assertEqual(c.saldo, Decimal('0.00'))

    # 25. Múltiplos Pagamentos com Rateio Exato no Misto
    def test_25_rateio_multiplos_pagamentos_misto(self):
        self._criar_contas_carlin(['50.00'])
        itens_data = [
            {'produto_id': self.produto.id, 'quantidade': Decimal('2'), 'preco_venda': Decimal('25.00')}
        ]
        recebimento_divida = {
            'cliente_id': self.cliente_carlin.id,
            'valor_pago': Decimal('50.00'),
            'valor_abatimento': Decimal('0.00'),
            'motivo_abatimento': ''
        }
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('30.00'), 'troco': Decimal('0.00')},
            {'forma': 'PIX', 'valor': Decimal('70.00'), 'troco': Decimal('0.00')}
        ]

        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao_caixa,
            itens_data=itens_data,
            pagamentos_data=pagamentos_data,
            cliente=self.cliente_carlin,
            recebimento_divida=recebimento_divida
        )

        self.assertEqual(venda.total, Decimal('50.00'))
        self.assertEqual(venda.pagamentos.count(), 2)
        conta = ContaReceber.objects.get(cliente=self.cliente_carlin)
        self.assertEqual(conta.status, 'QUITADA')
        self.assertEqual(conta.saldo, Decimal('0.00'))
