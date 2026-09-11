from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.produtos.models import Produto, Categoria
from apps.clientes.models import Cliente
from apps.caixas.models import Caixa, SessaoCaixa, MovimentacaoCaixa
from apps.vendas.models import Venda, ItemVenda, PagamentoVenda
from apps.financeiro.models import FluxoCaixa
from apps.vendas.services import SaleService
from apps.caixas.services import CashService
from apps.api.serializers import ProcessarVendaInputSerializer, VendaItemInputSerializer


class PDVCriticoTests(TestCase):
    """
    Testes automatizados cobrindo a auditoria e correções críticas do PDV:
    - Prevenção rigorosa de produtos com preço zero / inválido / negativo
    - Serializers e validações transacionais atômicas
    - Fluxo de pagamento dividido (ex: R$ 15,00 = R$ 11,00 Dinheiro + R$ 4,00 Débito)
    - Cálculo preciso de troco exclusivamente em Dinheiro
    - Bloqueio de troco em formas não-monetárias (PIX, Débito, Crédito)
    - Isolamento Multi-tenant estrito por empresa
    - Idempotência semântica e integridade de estoque e caixa
    """

    def setUp(self):
        self.empresa_a = Empresa.objects.create(
            razao_social="Adega Central Ltda",
            nome_fantasia="Adega Central",
            cnpj="12345678000199"
        )
        self.empresa_b = Empresa.objects.create(
            razao_social="Adega Norte Ltda",
            nome_fantasia="Adega Norte",
            cnpj="98765432000111"
        )

        self.operador_a = Usuario.objects.create_user(
            username="operador_a",
            password="password123",
            empresa=self.empresa_a,
            cargo="OPERADOR"
        )
        self.operador_b = Usuario.objects.create_user(
            username="operador_b",
            password="password123",
            empresa=self.empresa_b,
            cargo="OPERADOR"
        )

        self.caixa_a = Caixa.objects.create(
            empresa=self.empresa_a,
            nome="Caixa Balcão 1",
            codigo_identificador="CX01"
        )
        self.sessao_a = CashService.abrir_caixa(
            caixa=self.caixa_a,
            operador=self.operador_a,
            saldo_inicial=Decimal('100.00')
        )

        self.cat_a = Categoria.objects.create(
            empresa=self.empresa_a,
            nome="Bebidas"
        )

        self.prod_cerveja = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Cerveja Lata 350ml",
            codigo_barras="7891234567890",
            sku="CERV-350",
            categoria=self.cat_a,
            preco_custo=Decimal('3.00'),
            preco_venda=Decimal('5.00'),
            estoque_atual=Decimal('50.000'),
            estoque_minimo=Decimal('10.000'),
            unidade_medida="UN",
            ativo=True
        )

        self.prod_refrigerante = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Refrigerante 2L",
            codigo_barras="7890001112223",
            sku="REF-2L",
            categoria=self.cat_a,
            preco_custo=Decimal('4.00'),
            preco_venda=Decimal('10.00'),
            estoque_atual=Decimal('30.000'),
            estoque_minimo=Decimal('5.000'),
            unidade_medida="UN",
            ativo=True
        )

        self.prod_empresa_b = Produto.objects.create(
            empresa=self.empresa_b,
            nome="Vinho Tinto B",
            codigo_barras="7899999999999",
            sku="VINHO-B",
            preco_custo=Decimal('20.00'),
            preco_venda=Decimal('45.00'),
            estoque_atual=Decimal('10.000'),
            ativo=True
        )

        self.cliente = Cliente.objects.create(
            empresa=self.empresa_a,
            nome="João da Silva",
            cpf_cnpj="11122233344",
            limite_credito=Decimal('500.00')
        )

    # -------------------------------------------------------------
    # 1. VALIDAÇÃO DE PREÇO ZERO E DADOS DE PRODUTO
    # -------------------------------------------------------------

    def test_bloqueio_produto_preco_zero_backend(self):
        """Backend deve rejeitar qualquer item com preco_venda <= 0"""
        itens_data = [
            {'produto_id': self.prod_cerveja.id, 'quantidade': 1, 'preco_venda': Decimal('0.00')}
        ]
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('5.00'), 'troco': Decimal('0.00')}
        ]

        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa_a,
                operador=self.operador_a,
                sessao_caixa=self.sessao_a,
                itens_data=itens_data,
                pagamentos_data=pagamentos_data
            )
        self.assertIn("Preço de venda inválido", str(ctx.exception))

    def test_bloqueio_produto_preco_negativo_backend(self):
        """Backend deve rejeitar qualquer item com preco_venda negativo"""
        itens_data = [
            {'produto_id': self.prod_cerveja.id, 'quantidade': 1, 'preco_venda': Decimal('-5.00')}
        ]
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('5.00'), 'troco': Decimal('0.00')}
        ]

        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa_a,
                operador=self.operador_a,
                sessao_caixa=self.sessao_a,
                itens_data=itens_data,
                pagamentos_data=pagamentos_data
            )
        self.assertIn("Preço de venda inválido", str(ctx.exception))

    def test_serializer_rejeita_preco_zero_ou_invalido(self):
        """VendaItemInputSerializer deve rejeitar preco_venda <= 0"""
        serializer = VendaItemInputSerializer(data={
            'produto_id': self.prod_cerveja.id,
            'quantidade': 1,
            'preco_venda': '0.00'
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('preco_venda', serializer.errors)

    def test_serializer_rejeita_quantidade_zero(self):
        """VendaItemInputSerializer deve rejeitar quantidade <= 0"""
        serializer = VendaItemInputSerializer(data={
            'produto_id': self.prod_cerveja.id,
            'quantidade': 0,
            'preco_venda': '5.00'
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('quantidade', serializer.errors)

    # -------------------------------------------------------------
    # 2. FLUXO DE PAGAMENTO DIVIDIDO (CENÁRIO EXATO DO BUG)
    # -------------------------------------------------------------

    def test_pagamento_dividido_cenario_usuario_15_reais(self):
        """
        Cenário relatado pelo usuário:
        - 1x Cerveja (R$ 5,00) + 1x Refrigerante (R$ 10,00) = Total R$ 15,00
        - Parcela 1: R$ 11,00 em DINHEIRO
        - Parcela 2: R$ 4,00 em CARTAO_DEBITO
        - Saldo restante = R$ 0,00. Venda deve ser processada com sucesso.
        """
        itens_data = [
            {'produto_id': self.prod_cerveja.id, 'quantidade': 1, 'preco_venda': Decimal('5.00')},
            {'produto_id': self.prod_refrigerante.id, 'quantidade': 1, 'preco_venda': Decimal('10.00')}
        ]
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('11.00'), 'troco': Decimal('0.00')},
            {'forma': 'CARTAO_DEBITO', 'valor': Decimal('4.00'), 'troco': Decimal('0.00')}
        ]

        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_a,
            itens_data=itens_data,
            pagamentos_data=pagamentos_data
        )

        self.assertIsNotNone(venda.id)
        self.assertEqual(venda.total, Decimal('15.00'))
        self.assertEqual(venda.pagamentos.count(), 2)
        
        # Verifica pagamentos gravados
        pag_dinheiro = venda.pagamentos.get(forma_pagamento='DINHEIRO')
        self.assertEqual(pag_dinheiro.valor, Decimal('11.00'))
        self.assertEqual(pag_dinheiro.troco, Decimal('0.00'))

        pag_debito = venda.pagamentos.get(forma_pagamento='CARTAO_DEBITO')
        self.assertEqual(pag_debito.valor, Decimal('4.00'))
        self.assertEqual(pag_debito.troco, Decimal('0.00'))

        # Verifica estoque debitado
        self.prod_cerveja.refresh_from_db()
        self.prod_refrigerante.refresh_from_db()
        self.assertEqual(self.prod_cerveja.estoque_atual, Decimal('49.000'))
        self.assertEqual(self.prod_refrigerante.estoque_atual, Decimal('29.000'))

    def test_pagamento_dividido_com_troco_no_dinheiro(self):
        """
        Venda de R$ 15,00:
        - Parcela 1: R$ 5,00 em PIX
        - Parcela 2: R$ 20,00 em DINHEIRO (cobrindo os R$ 10,00 restantes com R$ 10,00 de troco)
        """
        itens_data = [
            {'produto_id': self.prod_cerveja.id, 'quantidade': 3, 'preco_venda': Decimal('5.00')}
        ]
        pagamentos_data = [
            {'forma': 'PIX', 'valor': Decimal('5.00'), 'troco': Decimal('0.00')},
            {'forma': 'DINHEIRO', 'valor': Decimal('20.00'), 'troco': Decimal('10.00')}
        ]

        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_a,
            itens_data=itens_data,
            pagamentos_data=pagamentos_data
        )

        self.assertEqual(venda.total, Decimal('15.00'))
        pag_dinheiro = venda.pagamentos.get(forma_pagamento='DINHEIRO')
        self.assertEqual(pag_dinheiro.valor, Decimal('20.00'))
        self.assertEqual(pag_dinheiro.troco, Decimal('10.00'))

    def test_bloqueio_troco_em_cartao_ou_pix(self):
        """Formas eletrônicas (CARTAO_DEBITO, CARTAO_CREDITO, PIX) não podem registrar troco"""
        itens_data = [
            {'produto_id': self.prod_cerveja.id, 'quantidade': 1, 'preco_venda': Decimal('5.00')}
        ]
        pagamentos_data = [
            {'forma': 'CARTAO_DEBITO', 'valor': Decimal('10.00'), 'troco': Decimal('5.00')}
        ]

        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa_a,
                operador=self.operador_a,
                sessao_caixa=self.sessao_a,
                itens_data=itens_data,
                pagamentos_data=pagamentos_data
            )
        self.assertIn("Troco", str(ctx.exception))

    def test_bloqueio_pagamento_insuficiente(self):
        """Venda deve ser rejeitada se os pagamentos não cobrirem o total"""
        itens_data = [
            {'produto_id': self.prod_cerveja.id, 'quantidade': 1, 'preco_venda': Decimal('5.00')}
        ]
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('3.00'), 'troco': Decimal('0.00')}
        ]

        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa_a,
                operador=self.operador_a,
                sessao_caixa=self.sessao_a,
                itens_data=itens_data,
                pagamentos_data=pagamentos_data
            )
        self.assertIn("Pagamento insuficiente", str(ctx.exception))

    def test_bloqueio_crediario_sem_cliente(self):
        """Venda no crediário sem cliente deve ser rejeitada"""
        itens_data = [
            {'produto_id': self.prod_cerveja.id, 'quantidade': 1, 'preco_venda': Decimal('5.00')}
        ]
        pagamentos_data = [
            {'forma': 'CREDIARIO', 'valor': Decimal('5.00'), 'troco': Decimal('0.00')}
        ]

        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa_a,
                operador=self.operador_a,
                sessao_caixa=self.sessao_a,
                itens_data=itens_data,
                pagamentos_data=pagamentos_data,
                cliente=None
            )
        self.assertIn("Crediário/Fiado", str(ctx.exception))

    # -------------------------------------------------------------
    # 3. ISOLAMENTO MULTI-TENANT & IDEMPOTÊNCIA
    # -------------------------------------------------------------

    def test_multi_tenant_rejeita_produto_outra_empresa(self):
        """Operador da Empresa A não pode vender produto da Empresa B"""
        itens_data = [
            {'produto_id': self.prod_empresa_b.id, 'quantidade': 1, 'preco_venda': Decimal('45.00')}
        ]
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('45.00'), 'troco': Decimal('0.00')}
        ]

        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa_a,
                operador=self.operador_a,
                sessao_caixa=self.sessao_a,
                itens_data=itens_data,
                pagamentos_data=pagamentos_data
            )
        self.assertIn("não encontrado ou inativo", str(ctx.exception))

    def test_idempotencia_offline_uuid(self):
        """Envio duplicado do mesmo offline_uuid deve retornar a venda sem duplicar movimentações"""
        uuid_teste = "uuid-venda-critica-12345"
        itens_data = [
            {'produto_id': self.prod_cerveja.id, 'quantidade': 2, 'preco_venda': Decimal('5.00')}
        ]
        pagamentos_data = [
            {'forma': 'DINHEIRO', 'valor': Decimal('10.00'), 'troco': Decimal('0.00')}
        ]

        # 1ª chamada
        venda_1 = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_a,
            itens_data=itens_data,
            pagamentos_data=pagamentos_data,
            offline_uuid=uuid_teste
        )

        self.prod_cerveja.refresh_from_db()
        estoque_apos_primeira = self.prod_cerveja.estoque_atual
        self.assertEqual(estoque_apos_primeira, Decimal('48.000'))

        # 2ª chamada (idempotente)
        venda_2 = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_a,
            itens_data=itens_data,
            pagamentos_data=pagamentos_data,
            offline_uuid=uuid_teste
        )

        self.assertEqual(venda_1.id, venda_2.id)
        self.prod_cerveja.refresh_from_db()
        self.assertEqual(self.prod_cerveja.estoque_atual, Decimal('48.000'))
        self.assertEqual(Venda.objects.filter(offline_uuid=uuid_teste).count(), 1)
