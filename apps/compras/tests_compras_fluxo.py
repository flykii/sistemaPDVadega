from decimal import Decimal
from datetime import date, timedelta
from django.test import TestCase, Client
from django.utils import timezone
from django.urls import reverse

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.clientes.models import Fornecedor
from apps.produtos.models import Produto, Categoria, MovimentacaoEstoque
from apps.financeiro.models import ContaPagar
from apps.compras.models import Compra, ItemCompra, RecebimentoCompra, ItemRecebimentoCompra
from apps.compras.services import PurchaseService
from apps.financeiro.services import FinancialService


class ComprasFluxoSeparadoTestCase(TestCase):
    def setUp(self):
        # 1. Empresas
        self.empresa_a = Empresa.objects.create(
            razao_social="Adega Teste A LTDA",
            nome_fantasia="Adega A",
            cnpj="11222333000199"
        )
        self.empresa_b = Empresa.objects.create(
            razao_social="Adega Teste B LTDA",
            nome_fantasia="Adega B",
            cnpj="99888777000111"
        )

        # 2. Usuários
        self.user_gerente = Usuario.objects.create_user(
            username="gerente_a",
            email="gerente_a@teste.com",
            password="password123",
            empresa=self.empresa_a,
            cargo='GERENTE'
        )
        self.user_estoquista = Usuario.objects.create_user(
            username="estoquista_a",
            email="estoquista_a@teste.com",
            password="password123",
            empresa=self.empresa_a,
            cargo='ESTOQUISTA'
        )
        self.user_financeiro = Usuario.objects.create_user(
            username="financeiro_a",
            email="fin_a@teste.com",
            password="password123",
            empresa=self.empresa_a,
            cargo='FINANCEIRO'
        )
        self.user_operador = Usuario.objects.create_user(
            username="operador_a",
            email="op_a@teste.com",
            password="password123",
            empresa=self.empresa_a,
            cargo='OPERADOR'
        )
        self.user_empresa_b = Usuario.objects.create_user(
            username="gerente_b",
            email="gerente_b@teste.com",
            password="password123",
            empresa=self.empresa_b,
            cargo='GERENTE'
        )

        # 3. Categorias e Fornecedores
        self.categoria = Categoria.objects.create(
            empresa=self.empresa_a,
            nome="Bebidas"
        )
        self.fornecedor = Fornecedor.objects.create(
            empresa=self.empresa_a,
            razao_social="Distribuidora de Bebidas Brasil LTDA",
            nome_fantasia="Distribuidora Brasil",
            cnpj="12345678000100",
            ativo=True
        )

        # 4. Produtos
        self.produto_1 = Produto.objects.create(
            empresa=self.empresa_a,
            categoria=self.categoria,
            nome="Vinho Tinto Reserva 750ml",
            codigo_barras="789000111",
            preco_custo=Decimal('30.00'),
            preco_venda=Decimal('60.00'),
            estoque_atual=Decimal('10.000'),
            estoque_minimo=Decimal('5.000'),
            ativo=True
        )
        self.produto_2 = Produto.objects.create(
            empresa=self.empresa_a,
            categoria=self.categoria,
            nome="Cerveja Artesanal IPA 500ml",
            codigo_barras="789000222",
            preco_custo=Decimal('8.00'),
            preco_venda=Decimal('16.00'),
            estoque_atual=Decimal('25.000'),
            estoque_minimo=Decimal('10.000'),
            ativo=True
        )

        self.client = Client()

    def test_01_pedido_compra_criado_com_status_pendente(self):
        vencimento = timezone.now().date() + timedelta(days=20)
        itens = [{
            'produto_id': self.produto_1.id,
            'quantidade': Decimal('50.000'),
            'preco_custo_unitario': Decimal('32.00')
        }]

        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-1001",
            itens_data=itens,
            data_vencimento=vencimento,
            usuario=self.user_gerente
        )

        self.assertEqual(compra.status, 'PENDENTE')
        self.assertEqual(compra.total, Decimal('1600.00'))
        self.assertEqual(compra.total_itens_pedidos, Decimal('50.000'))
        self.assertEqual(compra.total_itens_recebidos, Decimal('0.000'))
        self.assertEqual(compra.total_itens_pendentes, Decimal('50.000'))
        self.assertFalse(compra.is_totalmente_recebida)

    def test_02_pedido_compra_nao_altera_estoque_atual(self):
        estoque_antes = self.produto_1.estoque_atual

        PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-1002",
            itens_data=[{
                'produto_id': self.produto_1.id,
                'quantidade': Decimal('100.000'),
                'preco_custo_unitario': Decimal('35.00')
            }],
            usuario=self.user_gerente
        )

        self.produto_1.refresh_from_db()
        self.assertEqual(self.produto_1.estoque_atual, estoque_antes)

    def test_03_pedido_compra_nao_cria_movimentacao_estoque(self):
        movs_antes = MovimentacaoEstoque.objects.filter(produto=self.produto_1).count()

        PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-1003",
            itens_data=[{
                'produto_id': self.produto_1.id,
                'quantidade': Decimal('30.000'),
                'preco_custo_unitario': Decimal('29.00')
            }],
            usuario=self.user_gerente
        )

        movs_depois = MovimentacaoEstoque.objects.filter(produto=self.produto_1).count()
        self.assertEqual(movs_depois, movs_antes)

    def test_04_pedido_compra_nao_altera_preco_custo_produto(self):
        custo_antes = self.produto_1.preco_custo

        PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-1004",
            itens_data=[{
                'produto_id': self.produto_1.id,
                'quantidade': Decimal('20.000'),
                'preco_custo_unitario': Decimal('45.00')
            }],
            usuario=self.user_gerente
        )

        self.produto_1.refresh_from_db()
        self.assertEqual(self.produto_1.preco_custo, custo_antes)

    def test_05_pedido_compra_gera_conta_a_pagar_com_vencimento(self):
        data_venc = timezone.now().date() + timedelta(days=45)
        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-1005",
            itens_data=[{
                'produto_id': self.produto_1.id,
                'quantidade': Decimal('10.000'),
                'preco_custo_unitario': Decimal('30.00')
            }],
            data_vencimento=data_venc,
            usuario=self.user_gerente
        )

        conta = ContaPagar.objects.filter(compra=compra).first()
        self.assertIsNotNone(conta)
        self.assertEqual(conta.valor, Decimal('300.00'))
        self.assertEqual(conta.status, 'ABERTA')
        self.assertEqual(conta.data_vencimento, data_venc)
        self.assertEqual(conta.fornecedor, self.fornecedor)

    def test_06_pedido_compra_multiplos_itens_totais(self):
        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-MULTI",
            itens_data=[
                {'produto_id': self.produto_1.id, 'quantidade': Decimal('10.000'), 'preco_custo_unitario': Decimal('30.00')},
                {'produto_id': self.produto_2.id, 'quantidade': Decimal('20.000'), 'preco_custo_unitario': Decimal('8.50')}
            ],
            usuario=self.user_gerente
        )

        self.assertEqual(compra.total, Decimal('470.00'))
        self.assertEqual(compra.itens.count(), 2)

    def test_07_pedido_compra_validacoes_erro(self):
        with self.assertRaises(ValueError):
            PurchaseService.criar_pedido_compra(
                empresa=self.empresa_a,
                fornecedor=self.fornecedor,
                numero_nota="NF-ERR",
                itens_data=[],
                usuario=self.user_gerente
            )

        with self.assertRaises(ValueError):
            PurchaseService.criar_pedido_compra(
                empresa=self.empresa_a,
                fornecedor=self.fornecedor,
                numero_nota="NF-ERR2",
                itens_data=[{'produto_id': self.produto_1.id, 'quantidade': Decimal('0.000'), 'preco_custo_unitario': Decimal('10.00')}],
                usuario=self.user_gerente
            )

    def test_08_recebimento_total_atualiza_estoque_e_custo(self):
        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-REC-TOTAL",
            itens_data=[{
                'produto_id': self.produto_1.id,
                'quantidade': Decimal('20.000'),
                'preco_custo_unitario': Decimal('35.00')
            }],
            usuario=self.user_gerente
        )
        item = compra.itens.first()
        estoque_antes = self.produto_1.estoque_atual

        recebimento = PurchaseService.registrar_recebimento(
            compra=compra,
            itens_recebidos=[{
                'item_compra_id': item.id,
                'quantidade_recebida': Decimal('20.000'),
                'preco_custo': Decimal('35.00')
            }],
            observacao="Entrega completa no galpão",
            usuario=self.user_estoquista
        )

        self.produto_1.refresh_from_db()
        compra.refresh_from_db()

        self.assertEqual(self.produto_1.estoque_atual, estoque_antes + Decimal('20.000'))
        self.assertEqual(self.produto_1.preco_custo, Decimal('35.00'))
        self.assertEqual(compra.status, 'CONCLUIDA')
        self.assertTrue(compra.is_totalmente_recebida)
        self.assertEqual(compra.recebimentos.count(), 1)

        mov = MovimentacaoEstoque.objects.filter(produto=self.produto_1, tipo='ENTRADA').order_by('-data_hora').first()
        self.assertEqual(mov.quantidade, Decimal('20.000'))
        self.assertIn("Recebimento Compra", mov.motivo)

    def test_09_recebimento_parcial_com_saldo_pendente(self):
        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-REC-PARCIAL",
            itens_data=[{
                'produto_id': self.produto_1.id,
                'quantidade': Decimal('50.000'),
                'preco_custo_unitario': Decimal('30.00')
            }],
            usuario=self.user_gerente
        )
        item = compra.itens.first()
        estoque_antes = self.produto_1.estoque_atual

        PurchaseService.registrar_recebimento(
            compra=compra,
            itens_recebidos=[{
                'item_compra_id': item.id,
                'quantidade_recebida': Decimal('15.000')
            }],
            encerrar_compra=False,
            usuario=self.user_estoquista
        )

        self.produto_1.refresh_from_db()
        compra.refresh_from_db()
        item.refresh_from_db()

        self.assertEqual(self.produto_1.estoque_atual, estoque_antes + Decimal('15.000'))
        self.assertEqual(item.quantidade_recebida, Decimal('15.000'))
        self.assertEqual(item.quantidade_pendente, Decimal('35.000'))
        self.assertFalse(item.is_totalmente_recebido)
        self.assertEqual(compra.status, 'PARCIAL')
        self.assertEqual(compra.total_itens_pendentes, Decimal('35.000'))

    def test_10_multiplos_recebimentos_sequenciais(self):
        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-MULTI-REC",
            itens_data=[{
                'produto_id': self.produto_1.id,
                'quantidade': Decimal('100.000'),
                'preco_custo_unitario': Decimal('30.00')
            }],
            usuario=self.user_gerente
        )
        item = compra.itens.first()
        estoque_inicial = self.produto_1.estoque_atual

        PurchaseService.registrar_recebimento(
            compra=compra,
            itens_recebidos=[{'item_compra_id': item.id, 'quantidade_recebida': Decimal('40.000')}],
            usuario=self.user_estoquista
        )
        compra.refresh_from_db()
        self.assertEqual(compra.status, 'PARCIAL')
        self.assertEqual(compra.total_itens_recebidos, Decimal('40.000'))

        PurchaseService.registrar_recebimento(
            compra=compra,
            itens_recebidos=[{'item_compra_id': item.id, 'quantidade_recebida': Decimal('60.000')}],
            usuario=self.user_estoquista
        )
        compra.refresh_from_db()
        self.produto_1.refresh_from_db()

        self.assertEqual(compra.status, 'CONCLUIDA')
        self.assertEqual(compra.total_itens_recebidos, Decimal('100.000'))
        self.assertEqual(compra.total_itens_pendentes, Decimal('0.000'))
        self.assertEqual(compra.recebimentos.count(), 2)
        self.assertEqual(self.produto_1.estoque_atual, estoque_inicial + Decimal('100.000'))

    def test_11_recebimento_parcial_com_encerramento_manual(self):
        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-ENCERRAMENTO",
            itens_data=[{
                'produto_id': self.produto_1.id,
                'quantidade': Decimal('80.000'),
                'preco_custo_unitario': Decimal('30.00')
            }],
            usuario=self.user_gerente
        )
        item = compra.itens.first()

        PurchaseService.registrar_recebimento(
            compra=compra,
            itens_recebidos=[{'item_compra_id': item.id, 'quantidade_recebida': Decimal('50.000')}],
            encerrar_compra=True,
            observacao="Fornecedor comunicou falta do saldo de 30 unidades.",
            usuario=self.user_gerente
        )

        compra.refresh_from_db()
        self.assertEqual(compra.status, 'CONCLUIDA')
        self.assertEqual(compra.total_itens_recebidos, Decimal('50.000'))

        with self.assertRaises(ValueError):
            PurchaseService.registrar_recebimento(
                compra=compra,
                itens_recebidos=[{'item_compra_id': item.id, 'quantidade_recebida': Decimal('10.000')}],
                usuario=self.user_estoquista
            )

    def test_12_recebimento_com_quantidade_excedente(self):
        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-EXCEDENTE",
            itens_data=[{
                'produto_id': self.produto_2.id,
                'quantidade': Decimal('20.000'),
                'preco_custo_unitario': Decimal('8.00')
            }],
            usuario=self.user_gerente
        )
        item = compra.itens.first()
        estoque_antes = self.produto_2.estoque_atual

        PurchaseService.registrar_recebimento(
            compra=compra,
            itens_recebidos=[{'item_compra_id': item.id, 'quantidade_recebida': Decimal('24.000')}],
            observacao="Recebido 4 unidades a mais como brinde",
            usuario=self.user_estoquista
        )

        self.produto_2.refresh_from_db()
        item.refresh_from_db()
        compra.refresh_from_db()

        self.assertEqual(self.produto_2.estoque_atual, estoque_antes + Decimal('24.000'))
        self.assertEqual(item.quantidade_recebida, Decimal('24.000'))
        self.assertEqual(item.excedente, Decimal('4.000'))
        self.assertEqual(compra.status, 'CONCLUIDA')

    def test_13_recebimento_com_custo_praticado_customizado(self):
        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-CUSTO-ATT",
            itens_data=[{
                'produto_id': self.produto_1.id,
                'quantidade': Decimal('10.000'),
                'preco_custo_unitario': Decimal('30.00')
            }],
            usuario=self.user_gerente
        )
        item = compra.itens.first()

        PurchaseService.registrar_recebimento(
            compra=compra,
            itens_recebidos=[{
                'item_compra_id': item.id,
                'quantidade_recebida': Decimal('10.000'),
                'preco_custo': Decimal('34.50')
            }],
            usuario=self.user_estoquista
        )

        self.produto_1.refresh_from_db()
        self.assertEqual(self.produto_1.preco_custo, Decimal('34.50'))

    def test_14_recebimento_vincula_fornecedor_principal_se_vazio(self):
        prod_sem_fornec = Produto.objects.create(
            empresa=self.empresa_a,
            categoria=self.categoria,
            nome="Espumante Brut 750ml",
            codigo_barras="789000999",
            preco_custo=Decimal('40.00'),
            preco_venda=Decimal('80.00'),
            estoque_atual=Decimal('0.000'),
            fornecedor_principal=None,
            ativo=True
        )

        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-FORNEC",
            itens_data=[{
                'produto_id': prod_sem_fornec.id,
                'quantidade': Decimal('12.000'),
                'preco_custo_unitario': Decimal('40.00')
            }],
            usuario=self.user_gerente
        )
        item = compra.itens.first()

        PurchaseService.registrar_recebimento(
            compra=compra,
            itens_recebidos=[{'item_compra_id': item.id, 'quantidade_recebida': Decimal('12.000')}],
            usuario=self.user_estoquista
        )

        prod_sem_fornec.refresh_from_db()
        self.assertEqual(prod_sem_fornec.fornecedor_principal, self.fornecedor)

    def test_15_recebimento_validacao_itens_zerados_gera_erro(self):
        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-ZERO",
            itens_data=[{'produto_id': self.produto_1.id, 'quantidade': Decimal('10.000'), 'preco_custo_unitario': Decimal('30.00')}],
            usuario=self.user_gerente
        )
        item = compra.itens.first()

        with self.assertRaises(ValueError):
            PurchaseService.registrar_recebimento(
                compra=compra,
                itens_recebidos=[{'item_compra_id': item.id, 'quantidade_recebida': Decimal('0.000')}],
                usuario=self.user_estoquista
            )

    def test_16_cancelar_compra_pendente_cancela_conta_sem_mexer_estoque(self):
        estoque_antes = self.produto_1.estoque_atual
        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-CANC-1",
            itens_data=[{'produto_id': self.produto_1.id, 'quantidade': Decimal('20.000'), 'preco_custo_unitario': Decimal('30.00')}],
            usuario=self.user_gerente
        )

        PurchaseService.cancelar_compra(compra=compra, usuario=self.user_gerente, motivo="Erro de digitação do pedido")

        compra.refresh_from_db()
        self.produto_1.refresh_from_db()
        conta = ContaPagar.objects.get(compra=compra)

        self.assertEqual(compra.status, 'CANCELADA')
        self.assertEqual(conta.status, 'CANCELADA')
        self.assertEqual(self.produto_1.estoque_atual, estoque_antes)

    def test_17_cancelar_compra_apos_recebimento_estorna_estoque(self):
        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-CANC-2",
            itens_data=[{'produto_id': self.produto_1.id, 'quantidade': Decimal('30.000'), 'preco_custo_unitario': Decimal('30.00')}],
            usuario=self.user_gerente
        )
        item = compra.itens.first()
        estoque_inicial = self.produto_1.estoque_atual

        PurchaseService.registrar_recebimento(
            compra=compra,
            itens_recebidos=[{'item_compra_id': item.id, 'quantidade_recebida': Decimal('20.000')}],
            usuario=self.user_estoquista
        )
        self.produto_1.refresh_from_db()
        self.assertEqual(self.produto_1.estoque_atual, estoque_inicial + Decimal('20.000'))

        PurchaseService.cancelar_compra(compra=compra, usuario=self.user_gerente, motivo="Devolução total por avaria")

        compra.refresh_from_db()
        self.produto_1.refresh_from_db()
        conta = ContaPagar.objects.get(compra=compra)

        self.assertEqual(compra.status, 'CANCELADA')
        self.assertEqual(conta.status, 'CANCELADA')
        self.assertEqual(self.produto_1.estoque_atual, estoque_inicial)

        mov_estorno = MovimentacaoEstoque.objects.filter(produto=self.produto_1, tipo='SAIDA').order_by('-data_hora').first()
        self.assertIsNotNone(mov_estorno)
        self.assertEqual(mov_estorno.quantidade, Decimal('20.000'))
        self.assertIn("Estorno por Cancelamento", mov_estorno.motivo)

    def test_18_cancelar_compra_com_conta_pagar_paga_bloqueia(self):
        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-PAGA-BLOQ",
            itens_data=[{'produto_id': self.produto_1.id, 'quantidade': Decimal('10.000'), 'preco_custo_unitario': Decimal('30.00')}],
            usuario=self.user_gerente
        )
        conta = ContaPagar.objects.get(compra=compra)
        conta.status = 'PAGA'
        conta.valor_pago = Decimal('300.00')
        conta.save()

        with self.assertRaises(ValueError):
            PurchaseService.cancelar_compra(compra=compra, usuario=self.user_gerente, motivo="Tentativa de cancelamento")

    def test_19_pagamento_conta_independe_de_recebimento_fisico(self):
        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-PAG-ANTECIPADO",
            itens_data=[{'produto_id': self.produto_1.id, 'quantidade': Decimal('10.000'), 'preco_custo_unitario': Decimal('30.00')}],
            usuario=self.user_gerente
        )
        conta = ContaPagar.objects.get(compra=compra)

        FinancialService.pagar_conta_despesa(
            conta=conta,
            valor_pago=Decimal('300.00'),
            forma_pagamento='TRANSFERENCIA',
            usuario=self.user_financeiro
        )

        conta.refresh_from_db()
        compra.refresh_from_db()

        self.assertEqual(conta.status, 'PAGA')
        self.assertEqual(compra.status, 'PENDENTE')
        self.assertEqual(self.produto_1.estoque_atual, Decimal('10.000'))

        item = compra.itens.first()
        PurchaseService.registrar_recebimento(
            compra=compra,
            itens_recebidos=[{'item_compra_id': item.id, 'quantidade_recebida': Decimal('10.000')}],
            usuario=self.user_estoquista
        )
        compra.refresh_from_db()
        self.assertEqual(compra.status, 'CONCLUIDA')

    def test_20_contas_pagar_com_vencimento_futuro_visivel_na_listagem(self):
        venc_futuro = timezone.now().date() + timedelta(days=60)
        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-FUTURO",
            itens_data=[{'produto_id': self.produto_1.id, 'quantidade': Decimal('5.000'), 'preco_custo_unitario': Decimal('30.00')}],
            data_vencimento=venc_futuro,
            usuario=self.user_gerente
        )

        self.client.force_login(self.user_financeiro)
        response = self.client.get(reverse('contas_pagar_list'))
        self.assertEqual(response.status_code, 200)
        contas_no_contexto = response.context['contas']
        conta_ids = [c.id for c in contas_no_contexto]
        conta_criada = ContaPagar.objects.get(compra=compra)
        self.assertIn(conta_criada.id, conta_ids)

    def test_21_isolamento_multitenant_compras(self):
        compra_a = PurchaseService.criar_pedido_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-TENANT-A",
            itens_data=[{'produto_id': self.produto_1.id, 'quantidade': Decimal('10.000'), 'preco_custo_unitario': Decimal('30.00')}],
            usuario=self.user_gerente
        )

        self.client.force_login(self.user_empresa_b)
        response = self.client.get(reverse('compra_detalhe', kwargs={'pk': compra_a.id}))
        self.assertEqual(response.status_code, 404)

        response_rec = self.client.get(reverse('compra_receber', kwargs={'pk': compra_a.id}))
        self.assertEqual(response_rec.status_code, 404)

    def test_22_views_fluxo_completo_compras(self):
        self.client.force_login(self.user_gerente)

        data_venc = (timezone.now().date() + timedelta(days=15)).isoformat()
        response = self.client.post(reverse('compra_nova'), {
            'fornecedor_id': self.fornecedor.id,
            'numero_nota': 'NF-HTTP-999',
            'data_vencimento': data_venc,
            'observacoes': 'Pedido criado via View',
            'produto_id[]': [self.produto_1.id],
            'quantidade[]': ['25.0'],
            'preco_custo[]': ['31.50']
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        compra = Compra.objects.filter(numero_nota='NF-HTTP-999').first()
        self.assertIsNotNone(compra)
        self.assertEqual(compra.status, 'PENDENTE')

        response = self.client.get(reverse('compra_receber', kwargs={'pk': compra.id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Conferência e Recebimento')

        item = compra.itens.first()
        response = self.client.post(reverse('compra_receber', kwargs={'pk': compra.id}), {
            'item_compra_id[]': [item.id],
            'quantidade_recebida[]': ['25.0'],
            'preco_custo[]': ['31.50'],
            'observacao': 'Tudo conferido na doca 1'
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        compra.refresh_from_db()
        self.assertEqual(compra.status, 'CONCLUIDA')
        self.assertEqual(compra.recebimentos.count(), 1)


class PrazosVencimentoCompraTestCase(TestCase):
    """Testes específicos para cálculo de vencimento baseado no prazo do fornecedor e preservação de edição manual."""

    def setUp(self):
        self.empresa = Empresa.objects.create(
            razao_social="Adega Prazos LTDA",
            nome_fantasia="Adega Prazos",
            cnpj="55443322000188"
        )
        self.usuario = Usuario.objects.create_user(
            username="gerente_prazos",
            email="prazos@teste.com",
            password="password123",
            empresa=self.empresa,
            cargo='GERENTE'
        )
        self.fornecedor_28d = Fornecedor.objects.create(
            empresa=self.empresa,
            razao_social="Distribuidora 28 Dias LTDA",
            condicao_pagamento_padrao="28_DIAS",
            prazo_pagamento_dias=28
        )
        self.fornecedor_avista = Fornecedor.objects.create(
            empresa=self.empresa,
            razao_social="Distribuidora A Vista LTDA",
            condicao_pagamento_padrao="A_VISTA",
            prazo_pagamento_dias=0
        )
        self.produto = Produto.objects.create(
            empresa=self.empresa,
            nome="Cerveja Teste",
            preco_custo=Decimal('5.00'),
            preco_venda=Decimal('10.00'),
            estoque_atual=Decimal('50.000')
        )
        self.client = Client()
        self.client.force_login(self.usuario)

    # Teste 1: Fornecedor com 28 dias -> vencimento = data atual + 28 dias
    def test_fornecedor_28_dias_calculo_vencimento(self):
        hoje = timezone.now().date()
        venc_esperado = hoje + timedelta(days=28)

        # 1. Via GET (sugestão inicial da view)
        response = self.client.get(reverse('compra_nova') + f"?fornecedor_id={self.fornecedor_28d.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['data_vencimento_inicial'], venc_esperado.strftime('%Y-%m-%d'))

        # 2. Via Service com fallback automático
        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa,
            fornecedor=self.fornecedor_28d,
            numero_nota="NF-28D",
            itens_data=[{'produto_id': self.produto.id, 'quantidade': 10, 'preco_custo_unitario': 5.00}],
            data_vencimento=None,
            usuario=self.usuario
        )
        conta = ContaPagar.objects.get(compra=compra)
        self.assertEqual(conta.data_vencimento, venc_esperado)

    # Teste 2: Fornecedor À Vista -> vencimento = mesma data do pedido (prazo 0)
    def test_fornecedor_a_vista_vencimento_mesmo_dia(self):
        hoje = timezone.now().date()

        # 1. Via GET (sugestão inicial da view)
        response = self.client.get(reverse('compra_nova') + f"?fornecedor_id={self.fornecedor_avista.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['data_vencimento_inicial'], hoje.strftime('%Y-%m-%d'))

        # 2. Via Service com fallback automático (não deve virar 30 dias!)
        compra = PurchaseService.criar_pedido_compra(
            empresa=self.empresa,
            fornecedor=self.fornecedor_avista,
            numero_nota="NF-AVISTA",
            itens_data=[{'produto_id': self.produto.id, 'quantidade': 10, 'preco_custo_unitario': 5.00}],
            data_vencimento=None,
            usuario=self.usuario
        )
        conta = ContaPagar.objects.get(compra=compra)
        self.assertEqual(conta.data_vencimento, hoje)

    # Teste 3: Usuário altera manualmente o vencimento -> valor manual é preservado no POST e no banco
    def test_vencimento_manual_preservado_no_post_e_banco(self):
        data_manual = (timezone.now().date() + timedelta(days=45)).strftime('%Y-%m-%d')

        response = self.client.post(reverse('compra_nova'), {
            'fornecedor_id': self.fornecedor_28d.id,
            'numero_nota': 'NF-MANUAL-01',
            'data_vencimento': data_manual,
            'produto_id[]': [self.produto.id],
            'quantidade[]': ['10'],
            'preco_custo[]': ['5.00']
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        compra = Compra.objects.filter(numero_nota='NF-MANUAL-01').first()
        self.assertIsNotNone(compra)
        conta = ContaPagar.objects.get(compra=compra)
        self.assertEqual(conta.data_vencimento.strftime('%Y-%m-%d'), data_manual)

    # Teste 4: Serialização JSON correta para o frontend (incluindo prazo 0 e prazo 28)
    def test_fornecedores_json_contem_prazos_corretos(self):
        response = self.client.get(reverse('compra_nova'))
        self.assertEqual(response.status_code, 200)
        fornecedores_json = response.context['fornecedores_json']
        self.assertIn('"prazo_dias": 28', fornecedores_json)
        self.assertIn('"prazo_dias": 0', fornecedores_json)
