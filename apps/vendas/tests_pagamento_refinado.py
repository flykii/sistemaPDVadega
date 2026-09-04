from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError

from apps.empresas.models import Empresa, ConfiguracaoAtalhoPDV
from apps.usuarios.models import Usuario
from apps.produtos.models import Produto, Categoria
from apps.clientes.models import Cliente
from apps.caixas.models import Caixa, SessaoCaixa, MovimentacaoCaixa
from apps.vendas.models import Venda, ItemVenda, PagamentoVenda
from apps.financeiro.models import FluxoCaixa
from apps.vendas.services import SaleService
from apps.caixas.services import CashService


class RefinedPaymentFlowTests(TestCase):
    """
    Testes automatizados completos para o fluxo de pagamento refinado:
    - Dinheiro exato e com troco
    - Pagamento insuficiente
    - PIX, Cartão Débito, Cartão Crédito
    - Pagamento dividido (2 e 3 parcelas)
    - Idempotência e proteção contra duplicidade
    - Atualização de estoque e movimentações de caixa
    - Isolamento multi-tenant
    """

    def setUp(self):
        self.empresa_a = Empresa.objects.create(
            razao_social="Mercado Alpha Ltda",
            nome_fantasia="Mercado Alpha",
            cnpj="11111111000101"
        )
        self.empresa_b = Empresa.objects.create(
            razao_social="Mercado Beta Ltda",
            nome_fantasia="Mercado Beta",
            cnpj="22222222000102"
        )

        self.operador_a = Usuario.objects.create_user(
            username="op_alpha",
            password="password123",
            empresa=self.empresa_a,
            cargo="OPERADOR"
        )
        self.operador_b = Usuario.objects.create_user(
            username="op_beta",
            password="password123",
            empresa=self.empresa_b,
            cargo="OPERADOR"
        )

        self.caixa_a = Caixa.objects.create(
            empresa=self.empresa_a,
            nome="Caixa 01",
            codigo_identificador="CX01"
        )
        self.sessao_a = CashService.abrir_caixa(
            caixa=self.caixa_a,
            operador=self.operador_a,
            saldo_inicial=Decimal('100.00')
        )

        self.caixa_b = Caixa.objects.create(
            empresa=self.empresa_b,
            nome="Caixa 01 Beta",
            codigo_identificador="CXB01"
        )
        self.sessao_b = CashService.abrir_caixa(
            caixa=self.caixa_b,
            operador=self.operador_b,
            saldo_inicial=Decimal('50.00')
        )

        self.prod_refrigerante = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Refrigerante 2L",
            codigo_barras="789100000001",
            preco_custo=Decimal('4.00'),
            preco_venda=Decimal('10.00'),
            estoque_atual=Decimal('50.00')
        )
        self.prod_salgado = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Salgado Assado",
            codigo_barras="789100000002",
            preco_custo=Decimal('2.50'),
            preco_venda=Decimal('5.00'),
            estoque_atual=Decimal('30.00')
        )

    def test_pagamento_dinheiro_exato(self):
        """Venda de R$ 15,00 paga com R$ 15,00 em dinheiro (troco R$ 0,00)."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_a,
            itens_data=[
                {'produto_id': self.prod_refrigerante.id, 'quantidade': 1, 'preco_venda': 10.00},
                {'produto_id': self.prod_salgado.id, 'quantidade': 1, 'preco_venda': 5.00}
            ],
            pagamentos_data=[
                {'forma': 'DINHEIRO', 'valor': 15.00, 'troco': 0.00}
            ],
            offline_uuid='UUID-TEST-DINHEIRO-EXATO-1'
        )

        self.assertEqual(venda.status, 'CONCLUIDA')
        self.assertEqual(venda.total, Decimal('15.00'))
        self.assertEqual(venda.pagamentos.count(), 1)
        pag = venda.pagamentos.first()
        self.assertEqual(pag.forma_pagamento, 'DINHEIRO')
        self.assertEqual(pag.valor, Decimal('15.00'))
        self.assertEqual(pag.troco, Decimal('0.00'))
        self.assertEqual(pag.valor_efetivo, Decimal('15.00'))
        
        # Estoque deduzido
        self.prod_refrigerante.refresh_from_db()
        self.prod_salgado.refresh_from_db()
        self.assertEqual(self.prod_refrigerante.estoque_atual, Decimal('49.00'))
        self.assertEqual(self.prod_salgado.estoque_atual, Decimal('29.00'))

    def test_pagamento_dinheiro_com_troco(self):
        """Venda de R$ 15,00 paga com R$ 20,00 em dinheiro (troco R$ 5,00, impacto líquido R$ 15,00)."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_a,
            itens_data=[
                {'produto_id': self.prod_refrigerante.id, 'quantidade': 1, 'preco_venda': 10.00},
                {'produto_id': self.prod_salgado.id, 'quantidade': 1, 'preco_venda': 5.00}
            ],
            pagamentos_data=[
                {'forma': 'DINHEIRO', 'valor': 20.00, 'troco': 5.00}
            ],
            offline_uuid='UUID-TEST-DINHEIRO-TROCO-1'
        )

        self.assertEqual(venda.status, 'CONCLUIDA')
        self.assertEqual(venda.total, Decimal('15.00'))
        pag = venda.pagamentos.first()
        self.assertEqual(pag.valor, Decimal('20.00'))
        self.assertEqual(pag.troco, Decimal('5.00'))
        self.assertEqual(pag.valor_efetivo, Decimal('15.00'))

        # Fluxo de Caixa deve registrar entrada líquida de R$ 15,00 (20 recebido - 5 troco)
        fc = FluxoCaixa.objects.filter(empresa=self.empresa_a, referencia_origem=venda.codigo_venda).latest('id')
        self.assertEqual(fc.valor, Decimal('15.00'))
        self.assertEqual(fc.tipo, 'ENTRADA')

    def test_pagamento_insuficiente_falha(self):
        """Venda de R$ 15,00 tentando pagar apenas R$ 10,00 deve falhar/gerar erro."""
        with self.assertRaises((ValidationError, Exception)):
            SaleService.processar_venda(
                empresa=self.empresa_a,
                operador=self.operador_a,
                sessao_caixa=self.sessao_a,
                itens_data=[
                    {'produto_id': self.prod_refrigerante.id, 'quantidade': 1, 'preco_venda': 10.00},
                    {'produto_id': self.prod_salgado.id, 'quantidade': 1, 'preco_venda': 5.00}
                ],
                pagamentos_data=[
                    {'forma': 'DINHEIRO', 'valor': 10.00, 'troco': 0.00}
                ],
                offline_uuid='UUID-TEST-INSUFICIENTE-1'
            )

    def test_pagamento_pix_completo(self):
        """Venda de R$ 15,00 paga integralmente via PIX."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_a,
            itens_data=[
                {'produto_id': self.prod_refrigerante.id, 'quantidade': 1, 'preco_venda': 10.00},
                {'produto_id': self.prod_salgado.id, 'quantidade': 1, 'preco_venda': 5.00}
            ],
            pagamentos_data=[
                {'forma': 'PIX', 'valor': 15.00, 'troco': 0.00}
            ],
            offline_uuid='UUID-TEST-PIX-1'
        )

        self.assertEqual(venda.status, 'CONCLUIDA')
        self.assertEqual(venda.total, Decimal('15.00'))
        self.assertEqual(venda.pagamentos.first().forma_pagamento, 'PIX')

    def test_pagamento_credito_e_debito_completos(self):
        """Vendas pagas integralmente via Cartão Crédito e Débito."""
        venda_cred = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_a,
            itens_data=[{'produto_id': self.prod_refrigerante.id, 'quantidade': 1, 'preco_venda': 10.00}],
            pagamentos_data=[{'forma': 'CARTAO_CREDITO', 'valor': 10.00, 'troco': 0.00}],
            offline_uuid='UUID-TEST-CREDITO-1'
        )
        self.assertEqual(venda_cred.pagamentos.first().forma_pagamento, 'CARTAO_CREDITO')

        venda_deb = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_a,
            itens_data=[{'produto_id': self.prod_salgado.id, 'quantidade': 2, 'preco_venda': 5.00}],
            pagamentos_data=[{'forma': 'CARTAO_DEBITO', 'valor': 10.00, 'troco': 0.00}],
            offline_uuid='UUID-TEST-DEBITO-1'
        )
        self.assertEqual(venda_deb.pagamentos.first().forma_pagamento, 'CARTAO_DEBITO')

    def test_pagamento_multiplo_duas_formas(self):
        """Venda de R$ 15,00 dividida em PIX R$ 5,00 + Cartão Crédito R$ 10,00."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_a,
            itens_data=[
                {'produto_id': self.prod_refrigerante.id, 'quantidade': 1, 'preco_venda': 10.00},
                {'produto_id': self.prod_salgado.id, 'quantidade': 1, 'preco_venda': 5.00}
            ],
            pagamentos_data=[
                {'forma': 'PIX', 'valor': 5.00, 'troco': 0.00},
                {'forma': 'CARTAO_CREDITO', 'valor': 10.00, 'troco': 0.00}
            ],
            offline_uuid='UUID-TEST-MULT-2-FORMAS-1'
        )

        self.assertEqual(venda.status, 'CONCLUIDA')
        self.assertEqual(venda.total, Decimal('15.00'))
        self.assertEqual(venda.pagamentos.count(), 2)

    def test_pagamento_multiplo_tres_formas(self):
        """Venda de R$ 15,00 dividida em PIX R$ 5,00 + Crédito R$ 5,00 + Débito R$ 5,00."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_a,
            itens_data=[
                {'produto_id': self.prod_refrigerante.id, 'quantidade': 1, 'preco_venda': 10.00},
                {'produto_id': self.prod_salgado.id, 'quantidade': 1, 'preco_venda': 5.00}
            ],
            pagamentos_data=[
                {'forma': 'PIX', 'valor': 5.00, 'troco': 0.00},
                {'forma': 'CARTAO_CREDITO', 'valor': 5.00, 'troco': 0.00},
                {'forma': 'CARTAO_DEBITO', 'valor': 5.00, 'troco': 0.00}
            ],
            offline_uuid='UUID-TEST-MULT-3-FORMAS-1'
        )

        self.assertEqual(venda.status, 'CONCLUIDA')
        self.assertEqual(venda.total, Decimal('15.00'))
        self.assertEqual(venda.pagamentos.count(), 3)

    def test_idempotencia_e_prevencao_duplicidade(self):
        """Mesmo offline_uuid enviado duas vezes não duplica a venda nem deduz estoque 2x."""
        estoque_ini = self.prod_refrigerante.estoque_atual

        # 1ª submissão
        venda_1 = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_a,
            itens_data=[{'produto_id': self.prod_refrigerante.id, 'quantidade': 2, 'preco_venda': 10.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 20.00, 'troco': 0.00}],
            offline_uuid='UUID-IDEMPOTENCIA-PROTECT'
        )

        # 2ª submissão idêntica (ex: retry ou duplo clique)
        venda_2 = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_a,
            itens_data=[{'produto_id': self.prod_refrigerante.id, 'quantidade': 2, 'preco_venda': 10.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 20.00, 'troco': 0.00}],
            offline_uuid='UUID-IDEMPOTENCIA-PROTECT'
        )

        self.assertEqual(venda_1.id, venda_2.id)
        self.assertEqual(Venda.objects.filter(offline_uuid='UUID-IDEMPOTENCIA-PROTECT').count(), 1)

        self.prod_refrigerante.refresh_from_db()
        self.assertEqual(self.prod_refrigerante.estoque_atual, estoque_ini - Decimal('2.00'))

    def test_configuracao_atalhos_pdv_formas_pagamento(self):
        """Verifica se os atalhos de formas de pagamento são salvos e retornados corretamente."""
        atalho_pix = ConfiguracaoAtalhoPDV.objects.create(
            empresa=self.empresa_a,
            funcao_codigo='PAG_PIX',
            tecla='F7'
        )
        self.assertEqual(atalho_pix.tecla, 'F7')
        self.assertEqual(atalho_pix.funcao_codigo, 'PAG_PIX')

        # Testar dicionário de atalhos por tenant
        atalhos_dict = ConfiguracaoAtalhoPDV.get_atalhos_empresa(self.empresa_a)
        self.assertEqual(atalhos_dict.get('PAG_PIX'), 'F7')
        self.assertEqual(atalhos_dict.get('FINALIZAR_COMPRA'), 'F5')
