from decimal import Decimal
from django.test import TestCase
from django.db import IntegrityError
from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.caixas.models import Caixa, SessaoCaixa
from apps.caixas.services import CashService
from apps.produtos.models import Produto, MovimentacaoEstoque
from apps.vendas.models import Venda, ItemVenda, PagamentoVenda
from apps.vendas.services import SaleService
from apps.clientes.models import Cliente
from apps.financeiro.models import FluxoCaixa

class PDVCoreSaleServiceTestCase(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            razao_social="Adega & Comercio LTDA",
            nome_fantasia="Adega Enterprise",
            cnpj="12.345.678/0001-90"
        )
        self.operador = Usuario.objects.create_user(
            username='operador_pdv',
            password='password123',
            empresa=self.empresa
        )
        self.caixa = Caixa.objects.create(
            empresa=self.empresa,
            nome="Caixa 01 - Principal",
            codigo_identificador="CX-01"
        )
        self.sessao = CashService.abrir_caixa(
            caixa=self.caixa,
            operador=self.operador,
            saldo_inicial=Decimal('100.00'),
            nome_operador="Operador Teste"
        )

        # Produto A: Cerveja Antarctica (Custo: 4.55, Venda: 6.50, Estoque: 100)
        self.produto_cerveja = Produto.objects.create(
            empresa=self.empresa,
            codigo_barras="7891991000833",
            sku="CERV-ANTARCTICA",
            nome="Cerveja Antarctica 350ml",
            preco_custo=Decimal('4.55'),
            preco_venda=Decimal('6.50'),
            estoque_atual=Decimal('100.000'),
            estoque_minimo=Decimal('10.000')
        )

        # Produto B: Vinho Tinto (Custo: 30.00, Venda: 50.00, Estoque: 20)
        self.produto_vinho = Produto.objects.create(
            empresa=self.empresa,
            codigo_barras="7898901234567",
            sku="VINHO-TINTO",
            nome="Vinho Tinto Seco 750ml",
            preco_custo=Decimal('30.00'),
            preco_venda=Decimal('50.00'),
            estoque_atual=Decimal('20.000'),
            estoque_minimo=Decimal('5.000')
        )

        # Produto C: Item de R$ 100 para testes de desconto exato
        self.produto_100 = Produto.objects.create(
            empresa=self.empresa,
            codigo_barras="7891001001001",
            sku="ITEM-100",
            nome="Item Promocional R$ 100",
            preco_custo=Decimal('70.00'),
            preco_venda=Decimal('100.00'),
            estoque_atual=Decimal('50.000'),
            estoque_minimo=Decimal('2.000')
        )

        self.cliente = Cliente.objects.create(
            empresa=self.empresa,
            nome="Cliente João Silva",
            cpf_cnpj="111.222.333-44",
            limite_credito=Decimal('500.00'),
            saldo_devedor=Decimal('0.00')
        )

    # TESTE 1: Venda de um produto (quantidade 1)
    def test_1_venda_de_um_produto(self):
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.produto_cerveja.id, 'quantidade': 1, 'preco_venda': 6.50}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 6.50, 'troco': 0.00}]
        )
        self.assertEqual(venda.subtotal, Decimal('6.50'))
        self.assertEqual(venda.total, Decimal('6.50'))
        self.assertEqual(venda.status, 'CONCLUIDA')
        self.assertEqual(venda.itens.count(), 1)
        self.assertEqual(venda.pagamentos.count(), 1)

        # Verifica baixa do estoque
        self.produto_cerveja.refresh_from_db()
        self.assertEqual(self.produto_cerveja.estoque_atual, Decimal('99.000'))

    # TESTE 2: Venda com quantidade 10 (inclusão com quantidade prévia)
    def test_2_venda_com_quantidade_10(self):
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.produto_cerveja.id, 'quantidade': 10, 'preco_venda': 6.50}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 65.00, 'troco': 0.00}]
        )
        self.assertEqual(venda.subtotal, Decimal('65.00'))
        self.assertEqual(venda.total, Decimal('65.00'))

        item = venda.itens.first()
        self.assertEqual(item.quantidade, Decimal('10.000'))
        self.assertEqual(item.preco_venda_unitario, Decimal('6.50'))
        self.assertEqual(item.subtotal, Decimal('65.00'))

        self.produto_cerveja.refresh_from_db()
        self.assertEqual(self.produto_cerveja.estoque_atual, Decimal('90.000'))

    # TESTE 3: Alteração de quantidade e recálculo correto de item
    def test_3_alteracao_de_quantidade_recalculo(self):
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.produto_cerveja.id, 'quantidade': 5, 'preco_venda': 6.50}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 32.50, 'troco': 0.00}]
        )
        item = venda.itens.first()
        self.assertEqual(item.subtotal, Decimal('32.50'))

        # Alterando para 8 unidades
        item.quantidade = Decimal('8')
        item.save()
        self.assertEqual(item.subtotal, Decimal('52.00'))

    # TESTE 4: Desconto em reais (Subtotal R$ 100, Desconto R$ 15 -> Total R$ 85)
    def test_4_desconto_em_reais(self):
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.produto_100.id, 'quantidade': 1, 'preco_venda': 100.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 85.00, 'troco': 0.00}],
            desconto=Decimal('15.00')
        )
        self.assertEqual(venda.subtotal, Decimal('100.00'))
        self.assertEqual(venda.desconto, Decimal('15.00'))
        self.assertEqual(venda.total, Decimal('85.00'))

    # TESTE 5: Desconto percentual (Subtotal R$ 100, 10% = R$ 10 -> Total R$ 90)
    def test_5_desconto_percentual(self):
        subtotal = Decimal('100.00')
        percentual = Decimal('10.00')
        desconto_calculado = (subtotal * percentual) / Decimal('100.00')

        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.produto_100.id, 'quantidade': 1, 'preco_venda': 100.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 90.00, 'troco': 0.00}],
            desconto=desconto_calculado
        )
        self.assertEqual(venda.subtotal, Decimal('100.00'))
        self.assertEqual(venda.desconto, Decimal('10.00'))
        self.assertEqual(venda.total, Decimal('90.00'))

    # TESTE 6: Pagamento em dinheiro com valor exato
    def test_6_pagamento_dinheiro_valor_exato(self):
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.produto_vinho.id, 'quantidade': 1, 'preco_venda': 50.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 50.00, 'troco': 0.00}]
        )
        pag = venda.pagamentos.first()
        self.assertEqual(pag.forma_pagamento, 'DINHEIRO')
        self.assertEqual(pag.valor, Decimal('50.00'))
        self.assertEqual(pag.troco, Decimal('0.00'))

    # TESTE 7: Pagamento em dinheiro com troco (Valor: R$ 77,30, Recebido: R$ 100,00, Troco: R$ 22,70)
    def test_7_pagamento_dinheiro_com_troco(self):
        prod_7730 = Produto.objects.create(
            empresa=self.empresa,
            codigo_barras="7897730773011",
            nome="Cesta Diversos",
            preco_custo=Decimal('50.00'),
            preco_venda=Decimal('77.30'),
            estoque_atual=Decimal('10.000')
        )
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': prod_7730.id, 'quantidade': 1, 'preco_venda': 77.30}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 100.00, 'troco': 22.70}]
        )
        self.assertEqual(venda.total, Decimal('77.30'))
        pag = venda.pagamentos.first()
        self.assertEqual(pag.valor, Decimal('100.00'))
        self.assertEqual(pag.troco, Decimal('22.70'))
        self.assertEqual(pag.valor - pag.troco, Decimal('77.30'))

    # TESTE 8: Pagamento em PIX
    def test_8_pagamento_pix(self):
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.produto_vinho.id, 'quantidade': 2, 'preco_venda': 50.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 100.00, 'troco': 0.00}]
        )
        self.assertEqual(venda.pagamentos.first().forma_pagamento, 'PIX')
        self.assertEqual(venda.pagamentos.first().valor, Decimal('100.00'))

    # TESTE 9: Pagamento em Débito
    def test_9_pagamento_debito(self):
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.produto_cerveja.id, 'quantidade': 2, 'preco_venda': 6.50}],
            pagamentos_data=[{'forma': 'CARTAO_DEBITO', 'valor': 13.00, 'troco': 0.00}]
        )
        self.assertEqual(venda.pagamentos.first().forma_pagamento, 'CARTAO_DEBITO')
        self.assertEqual(venda.total, Decimal('13.00'))

    # TESTE 10: Pagamento em Crédito
    def test_10_pagamento_credito(self):
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.produto_vinho.id, 'quantidade': 1, 'preco_venda': 50.00}],
            pagamentos_data=[{'forma': 'CARTAO_CREDITO', 'valor': 50.00, 'troco': 0.00}]
        )
        self.assertEqual(venda.pagamentos.first().forma_pagamento, 'CARTAO_CREDITO')
        self.assertEqual(venda.total, Decimal('50.00'))

    # TESTE 11: Pagamento dividido (R$ 50 PIX + R$ 50 Dinheiro = R$ 100)
    def test_11_pagamento_dividido_duas_formas(self):
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.produto_100.id, 'quantidade': 1, 'preco_venda': 100.00}],
            pagamentos_data=[
                {'forma': 'PIX', 'valor': 50.00, 'troco': 0.00},
                {'forma': 'DINHEIRO', 'valor': 50.00, 'troco': 0.00}
            ]
        )
        self.assertEqual(venda.total, Decimal('100.00'))
        self.assertEqual(venda.pagamentos.count(), 2)
        total_pago_efetivo = sum(p.valor - p.troco for p in venda.pagamentos.all())
        self.assertEqual(total_pago_efetivo, Decimal('100.00'))

    # TESTE 12: Pagamento dividido em três formas (R$ 30 PIX + R$ 50 Débito + R$ 20 Dinheiro = R$ 100)
    def test_12_pagamento_dividido_tres_formas(self):
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.produto_100.id, 'quantidade': 1, 'preco_venda': 100.00}],
            pagamentos_data=[
                {'forma': 'PIX', 'valor': 30.00, 'troco': 0.00},
                {'forma': 'CARTAO_DEBITO', 'valor': 50.00, 'troco': 0.00},
                {'forma': 'DINHEIRO', 'valor': 20.00, 'troco': 0.00}
            ]
        )
        self.assertEqual(venda.total, Decimal('100.00'))
        self.assertEqual(venda.pagamentos.count(), 3)
        formas = [p.forma_pagamento for p in venda.pagamentos.all()]
        self.assertIn('PIX', formas)
        self.assertIn('CARTAO_DEBITO', formas)
        self.assertIn('DINHEIRO', formas)

    # TESTE 13: Pagamento insuficiente (rejeição com ValueError)
    def test_13_pagamento_insuficiente_rejeicao(self):
        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa,
                operador=self.operador,
                sessao_caixa=self.sessao,
                itens_data=[{'produto_id': self.produto_100.id, 'quantidade': 1, 'preco_venda': 100.00}],
                pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 80.00, 'troco': 0.00}]
            )
        self.assertIn("Pagamento insuficiente", str(ctx.exception))

    # TESTE 14: Desconto maior que o subtotal (rejeição com ValueError)
    def test_14_desconto_maior_que_subtotal_rejeicao(self):
        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa,
                operador=self.operador,
                sessao_caixa=self.sessao,
                itens_data=[{'produto_id': self.produto_100.id, 'quantidade': 1, 'preco_venda': 100.00}],
                pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 100.00, 'troco': 0.00}],
                desconto=Decimal('150.00')
            )
        self.assertIn("não pode ser maior que o subtotal", str(ctx.exception))

    # TESTE 15: Quantidade inválida (zero ou negativa)
    def test_15_quantidade_invalida_rejeicao(self):
        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa,
                operador=self.operador,
                sessao_caixa=self.sessao,
                itens_data=[{'produto_id': self.produto_cerveja.id, 'quantidade': 0, 'preco_venda': 6.50}],
                pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 6.50, 'troco': 0.00}]
            )
        self.assertIn("maior que zero", str(ctx.exception))

    # TESTE 16: Produto inexistente
    def test_16_produto_inexistente_rejeicao(self):
        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa,
                operador=self.operador,
                sessao_caixa=self.sessao,
                itens_data=[{'produto_id': 999999, 'quantidade': 1, 'preco_venda': 10.00}],
                pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 10.00, 'troco': 0.00}]
            )
        self.assertIn("não encontrado", str(ctx.exception))

    # TESTE 17: Venda sem estoque suficiente (conforme regra do sistema)
    def test_17_venda_sem_estoque_suficiente(self):
        # Produto Vinho possui 20 unidades em estoque. Tentamos vender 25.
        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa,
                operador=self.operador,
                sessao_caixa=self.sessao,
                itens_data=[{'produto_id': self.produto_vinho.id, 'quantidade': 25, 'preco_venda': 50.00}],
                pagamentos_data=[{'forma': 'PIX', 'valor': 1250.00, 'troco': 0.00}]
            )
        self.assertIn("Estoque insuficiente", str(ctx.exception))
        # Verifica se o estoque do vinho permaneceu intacto em 20
        self.produto_vinho.refresh_from_db()
        self.assertEqual(self.produto_vinho.estoque_atual, Decimal('20.000'))

    # TESTE 18: Falha durante finalização e rollback transacional
    def test_18_falha_finalizacao_rollback_transacional(self):
        estoque_inicial = self.produto_cerveja.estoque_atual
        total_vendas_inicial = Venda.objects.count()

        # Simula tentativa com pagamento inválido que falha após validação preliminar
        with self.assertRaises(ValueError):
            SaleService.processar_venda(
                empresa=self.empresa,
                operador=self.operador,
                sessao_caixa=self.sessao,
                itens_data=[{'produto_id': self.produto_cerveja.id, 'quantidade': 5, 'preco_venda': 6.50}],
                pagamentos_data=[
                    {'forma': 'DINHEIRO', 'valor': 10.00, 'troco': 0.00} # Faltam 22.50
                ]
            )

        # Confirma que nenhuma venda ou item foi gravado (Rollback total)
        self.assertEqual(Venda.objects.count(), total_vendas_inicial)
        self.produto_cerveja.refresh_from_db()
        self.assertEqual(self.produto_cerveja.estoque_atual, estoque_inicial)

    # TESTE 19: Pagamento dividido com dinheiro e troco (PIX R$ 60 + Dinheiro R$ 50 [Troco R$ 10] = Venda R$ 100)
    def test_19_pagamento_dividido_com_dinheiro_e_troco(self):
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.produto_100.id, 'quantidade': 1, 'preco_venda': 100.00}],
            pagamentos_data=[
                {'forma': 'PIX', 'valor': 60.00, 'troco': 0.00},
                {'forma': 'DINHEIRO', 'valor': 50.00, 'troco': 10.00}
            ]
        )
        self.assertEqual(venda.total, Decimal('100.00'))
        self.assertEqual(venda.pagamentos.count(), 2)

        pag_pix = venda.pagamentos.get(forma_pagamento='PIX')
        pag_din = venda.pagamentos.get(forma_pagamento='DINHEIRO')

        self.assertEqual(pag_pix.valor_efetivo, Decimal('60.00'))
        self.assertEqual(pag_din.valor, Decimal('50.00'))
        self.assertEqual(pag_din.troco, Decimal('10.00'))
        self.assertEqual(pag_din.valor_efetivo, Decimal('40.00'))

        total_efetivo = pag_pix.valor_efetivo + pag_din.valor_efetivo
        self.assertEqual(total_efetivo, Decimal('100.00'))

        # Confirma lançamentos de fluxo de caixa (entradas líquidas de receita)
        fluxos = FluxoCaixa.objects.filter(referencia_origem=venda.codigo_venda)
        total_entradas_fluxo = sum(f.valor for f in fluxos)
        self.assertEqual(total_entradas_fluxo, Decimal('100.00'))

    # TESTE 20: Pagamento dividido PIX R$ 80 + Dinheiro R$ 50 com troco R$ 30 (Venda R$ 100)
    def test_20_pagamento_dividido_pix_80_dinheiro_50_troco_30(self):
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.produto_100.id, 'quantidade': 1, 'preco_venda': 100.00}],
            pagamentos_data=[
                {'forma': 'PIX', 'valor': 80.00, 'troco': 0.00},
                {'forma': 'DINHEIRO', 'valor': 50.00, 'troco': 30.00}
            ]
        )
        self.assertEqual(venda.total, Decimal('100.00'))
        pag_din = venda.pagamentos.get(forma_pagamento='DINHEIRO')
        self.assertEqual(pag_din.valor_efetivo, Decimal('20.00'))
        self.assertEqual(pag_din.troco, Decimal('30.00'))

    # TESTE 21: Integração Completa (PDV -> Venda -> Itens -> Pagamentos -> Estoque -> Caixa -> Relatório)
    def test_21_integracao_completa_pdv_venda_estoque_caixa_relatorio(self):
        from django.db.models import Sum, F, ExpressionWrapper, DecimalField

        # 1. Produto com estoque inicial = 20 e preço = R$ 10,00
        prod = Produto.objects.create(
            empresa=self.empresa,
            codigo_barras="7890000000021",
            nome="Produto Teste Integração",
            preco_custo=Decimal('6.00'),
            preco_venda=Decimal('10.00'),
            estoque_atual=Decimal('20.000'),
            estoque_minimo=Decimal('2.000')
        )

        # 2. Venda de 10 unidades com PIX R$ 60,00 + Dinheiro R$ 50,00 (Troco R$ 10,00)
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': prod.id, 'quantidade': 10, 'preco_venda': 10.00}],
            pagamentos_data=[
                {'forma': 'PIX', 'valor': 60.00, 'troco': 0.00},
                {'forma': 'DINHEIRO', 'valor': 50.00, 'troco': 10.00}
            ]
        )

        # 3. Validações da Venda
        self.assertEqual(venda.total, Decimal('100.00'))
        self.assertEqual(venda.subtotal, Decimal('100.00'))
        self.assertEqual(venda.status, 'CONCLUIDA')

        # 4. Validação de Estoque
        prod.refresh_from_db()
        self.assertEqual(prod.estoque_atual, Decimal('10.000')) # 20 - 10 = 10

        # 5. Validação de Pagamentos
        pag_pix = venda.pagamentos.get(forma_pagamento='PIX')
        pag_din = venda.pagamentos.get(forma_pagamento='DINHEIRO')
        self.assertEqual(pag_pix.valor_efetivo, Decimal('60.00'))
        self.assertEqual(pag_din.valor, Decimal('50.00'))
        self.assertEqual(pag_din.troco, Decimal('10.00'))
        self.assertEqual(pag_din.valor_efetivo, Decimal('40.00'))

        # 6. Validação do Caixa (Entrada líquida de dinheiro = R$ 40,00)
        self.sessao.refresh_from_db()
        self.assertEqual(self.sessao.total_vendas_dinheiro, Decimal('40.00'))

        # 7. Validação de Relatório de Formas de Pagamento
        pagamentos_qs = (
            PagamentoVenda.objects.filter(venda=venda)
            .values('forma_pagamento')
            .annotate(
                total_val=Sum(
                    ExpressionWrapper(F('valor') - F('troco'), output_field=DecimalField(max_digits=12, decimal_places=2))
                )
            )
        )
        totais_por_forma = {p['forma_pagamento']: p['total_val'] for p in pagamentos_qs}
        self.assertEqual(totais_por_forma.get('PIX'), Decimal('60.00'))
        self.assertEqual(totais_por_forma.get('DINHEIRO'), Decimal('40.00'))
        self.assertEqual(sum(totais_por_forma.values()), Decimal('100.00'))

    # TESTE 22: Teste de Caixa Físico (PIX não altera dinheiro físico na gaveta)
    def test_22_teste_caixa_fisico_gaveta_nao_alterado_por_pix(self):
        caixa_novo = Caixa.objects.create(empresa=self.empresa, nome="Caixa Balcão", codigo_identificador="CX-BALCAO")
        sessao_caixa = CashService.abrir_caixa(caixa_novo, self.operador, Decimal('200.00'))

        prod = Produto.objects.create(
            empresa=self.empresa,
            codigo_barras="7890000000022",
            nome="Produto Teste Caixa",
            preco_custo=Decimal('50.00'),
            preco_venda=Decimal('100.00'),
            estoque_atual=Decimal('10.000')
        )

        # Venda de R$ 100 com PIX R$ 60 + Dinheiro R$ 50 (Troco R$ 10)
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=sessao_caixa,
            itens_data=[{'produto_id': prod.id, 'quantidade': 1, 'preco_venda': 100.00}],
            pagamentos_data=[
                {'forma': 'PIX', 'valor': 60.00, 'troco': 0.00},
                {'forma': 'DINHEIRO', 'valor': 50.00, 'troco': 10.00}
            ]
        )

        sessao_caixa.refresh_from_db()
        # Saldo físico esperado: R$ 200 (inicial) + R$ 40 (dinheiro líquido) = R$ 240,00
        self.assertEqual(sessao_caixa.saldo_atual, Decimal('240.00'))

        # Fechamento com valor contado correto
        sessao_fechada = CashService.fechar_caixa(sessao_caixa, saldo_final_informado=Decimal('240.00'))
        self.assertEqual(sessao_fechada.saldo_final_calculado, Decimal('240.00'))
        self.assertEqual(sessao_fechada.diferenca, Decimal('0.00'))

    # TESTE 23: Teste de Venda Somente em Dinheiro com Troco no Caixa
    def test_23_teste_venda_somente_em_dinheiro_troco_saldo_fisico(self):
        caixa_novo = Caixa.objects.create(empresa=self.empresa, nome="Caixa Dinheiro", codigo_identificador="CX-DIN")
        sessao_caixa = CashService.abrir_caixa(caixa_novo, self.operador, Decimal('200.00'))

        prod = Produto.objects.create(
            empresa=self.empresa,
            codigo_barras="7890000000023",
            nome="Produto Teste R$ 77,30",
            preco_custo=Decimal('40.00'),
            preco_venda=Decimal('77.30'),
            estoque_atual=Decimal('10.000')
        )

        # Venda de R$ 77,30 paga com R$ 100,00 em dinheiro (Troco R$ 22,70)
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=sessao_caixa,
            itens_data=[{'produto_id': prod.id, 'quantidade': 1, 'preco_venda': 77.30}],
            pagamentos_data=[
                {'forma': 'DINHEIRO', 'valor': 100.00, 'troco': 22.70}
            ]
        )

        sessao_caixa.refresh_from_db()
        # Saldo físico esperado: R$ 200,00 + R$ 77,30 = R$ 277,30
        self.assertEqual(sessao_caixa.saldo_atual, Decimal('277.30'))

        sessao_fechada = CashService.fechar_caixa(sessao_caixa, saldo_final_informado=Decimal('277.30'))
        self.assertEqual(sessao_fechada.saldo_final_calculado, Decimal('277.30'))
        self.assertEqual(sessao_fechada.diferenca, Decimal('0.00'))

    # TESTE 24: Teste de Duplicação e Idempotência via offline_uuid
    def test_24_teste_duplicidade_idempotencia_offline_uuid(self):
        prod = Produto.objects.create(
            empresa=self.empresa,
            codigo_barras="7890000000024",
            nome="Produto Teste Idempotência",
            preco_custo=Decimal('10.00'),
            preco_venda=Decimal('20.00'),
            estoque_atual=Decimal('50.000')
        )

        uuid_venda = "OFF-UUID-TEST-999"
        total_vendas_antes = Venda.objects.count()

        # 1ª Chamada
        venda1 = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': prod.id, 'quantidade': 2, 'preco_venda': 20.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 40.00, 'troco': 0.00}],
            offline_uuid=uuid_venda
        )

        # 2ª Chamada idêntica (simulando repetição de rede ou duplo clique)
        venda2 = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': prod.id, 'quantidade': 2, 'preco_venda': 20.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 40.00, 'troco': 0.00}],
            offline_uuid=uuid_venda
        )

        # Deve retornar exatamente a mesma venda sem duplicar registros
        self.assertEqual(venda1.id, venda2.id)
        self.assertEqual(Venda.objects.count(), total_vendas_antes + 1)

        # Estoque deve ter baixado apenas 2 unidades (50 - 2 = 48)
        prod.refresh_from_db()
        self.assertEqual(prod.estoque_atual, Decimal('48.000'))

        # Apenas 1 item e 1 pagamento
        self.assertEqual(venda1.itens.count(), 1)
        self.assertEqual(venda1.pagamentos.count(), 1)

    # TESTE 25: Idempotência Semântica com Payload Diferente
    def test_25_idempotencia_semantica_payload_diferente(self):
        prod1 = Produto.objects.create(
            empresa=self.empresa,
            codigo_barras="7890000000025",
            nome="Produto Original R$ 100",
            preco_custo=Decimal('50.00'),
            preco_venda=Decimal('100.00'),
            estoque_atual=Decimal('10.000')
        )
        prod2 = Produto.objects.create(
            empresa=self.empresa,
            codigo_barras="7890000000026",
            nome="Produto Divergente R$ 900",
            preco_custo=Decimal('500.00'),
            preco_venda=Decimal('900.00'),
            estoque_atual=Decimal('10.000')
        )

        uuid_semantico = "UUID-SEMANTICO-ABC123"
        total_vendas_antes = Venda.objects.count()

        # 1ª Requisição: Venda de R$ 100
        venda_original = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': prod1.id, 'quantidade': 1, 'preco_venda': 100.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 100.00, 'troco': 0.00}],
            offline_uuid=uuid_semantico
        )
        self.assertEqual(venda_original.total, Decimal('100.00'))

        # 2ª Requisição: Mesmo UUID com payload divergente de R$ 900
        venda_retornada = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': prod2.id, 'quantidade': 1, 'preco_venda': 900.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 900.00, 'troco': 0.00}],
            offline_uuid=uuid_semantico
        )

        # Deve retornar a venda original intacta sem criar/modificar para R$ 900
        self.assertEqual(venda_retornada.id, venda_original.id)
        self.assertEqual(venda_retornada.total, Decimal('100.00'))
        self.assertEqual(Venda.objects.count(), total_vendas_antes + 1)

        # O produto 2 não deve ter sido consumido
        prod2.refresh_from_db()
        self.assertEqual(prod2.estoque_atual, Decimal('10.000'))

    # TESTE 26: Teste de Concorrência de Estoque Unitário (1 unidade disponível)
    def test_26_teste_concorrencia_simulada_estoque_unitario(self):
        prod_unico = Produto.objects.create(
            empresa=self.empresa,
            codigo_barras="7890000000027",
            nome="Última Unidade em Estoque",
            preco_custo=Decimal('30.00'),
            preco_venda=Decimal('60.00'),
            estoque_atual=Decimal('1.000') # Apenas 1 unidade
        )

        # Operação A: Vende a única unidade disponível com sucesso
        venda_a = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': prod_unico.id, 'quantidade': 1, 'preco_venda': 60.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 60.00, 'troco': 0.00}]
        )
        self.assertIsNotNone(venda_a)
        prod_unico.refresh_from_db()
        self.assertEqual(prod_unico.estoque_atual, Decimal('0.000'))

        # Operação B: Tentativa de vender a mesma unidade que acabou de ser consumida
        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa,
                operador=self.operador,
                sessao_caixa=self.sessao,
                itens_data=[{'produto_id': prod_unico.id, 'quantidade': 1, 'preco_venda': 60.00}],
                pagamentos_data=[{'forma': 'PIX', 'valor': 60.00, 'troco': 0.00}]
            )
        self.assertIn("Estoque insuficiente", str(ctx.exception))
        prod_unico.refresh_from_db()
        self.assertEqual(prod_unico.estoque_atual, Decimal('0.000'))

    # TESTE 27: Integridade Transacional - Rollback Completo ao Falhar
    def test_27_integridade_transacional_rollback_completo_ao_falhar(self):
        prod_rollback = Produto.objects.create(
            empresa=self.empresa,
            codigo_barras="7890000000028",
            nome="Produto Teste Rollback",
            preco_custo=Decimal('15.00'),
            preco_venda=Decimal('30.00'),
            estoque_atual=Decimal('10.000')
        )

        vendas_antes = Venda.objects.count()
        itens_antes = ItemVenda.objects.count()
        pagamentos_antes = PagamentoVenda.objects.count()
        fluxos_antes = FluxoCaixa.objects.count()

        # Tentativa de venda com forma de pagamento inválida que dispara exceção
        with self.assertRaises(ValueError):
            SaleService.processar_venda(
                empresa=self.empresa,
                operador=self.operador,
                sessao_caixa=self.sessao,
                itens_data=[{'produto_id': prod_rollback.id, 'quantidade': 2, 'preco_venda': 30.00}],
                pagamentos_data=[{'forma': 'FORMA_INEXISTENTE', 'valor': 60.00, 'troco': 0.00}]
            )

        # Verifica rollback de 100% das tabelas
        self.assertEqual(Venda.objects.count(), vendas_antes)
        self.assertEqual(ItemVenda.objects.count(), itens_antes)
        self.assertEqual(PagamentoVenda.objects.count(), pagamentos_antes)
        self.assertEqual(FluxoCaixa.objects.count(), fluxos_antes)

        # O estoque não deve ter sido alterado
        prod_rollback.refresh_from_db()
        self.assertEqual(prod_rollback.estoque_atual, Decimal('10.000'))
