from datetime import date, datetime, time, timedelta
from decimal import Decimal
from django.test import TestCase, Client
from django.utils import timezone
from django.urls import reverse

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.produtos.models import Produto, Categoria
from apps.clientes.models import Fornecedor
from apps.caixas.models import Caixa, SessaoCaixa
from apps.caixas.services import CashService
from apps.vendas.models import Venda
from apps.vendas.services import SaleService
from apps.compras.models import Compra, ItemCompra
from apps.compras.services import PurchaseService
from apps.relatorios.services import ReportService
from apps.core.operational_day import get_operational_today, get_operational_datetime_range


class ReposicaoV1EBloqueioCaixaTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            razao_social="Adega Teste V1 LTDA",
            nome_fantasia="Adega V1",
            cnpj="12345678000199"
        )
        self.admin = Usuario.objects.create_user(
            username="admin_v1",
            email="admin@v1.com",
            password="pass123",
            empresa=self.empresa,
            cargo='ADMIN'
        )
        self.fornecedor = Fornecedor.objects.create(
            empresa=self.empresa,
            razao_social="Distribuidora Bebidas Brasil LTDA",
            nome_fantasia="Bebidas Brasil",
            condicao_pagamento_padrao="A_PRAZO_15",
            prazo_pagamento_dias=15
        )
        self.categoria = Categoria.objects.create(empresa=self.empresa, nome="Cervejas")
        self.produto_1 = Produto.objects.create(
            empresa=self.empresa,
            nome="Cerveja Pilsen 600ml",
            codigo_barras="789111222",
            sku="PIL-600",
            categoria=self.categoria,
            fornecedor_principal=self.fornecedor,
            preco_custo=Decimal('5.00'),
            preco_venda=Decimal('9.00'),
            estoque_atual=Decimal('10.000'),
            estoque_minimo=Decimal('20.000')
        )
        self.produto_2 = Produto.objects.create(
            empresa=self.empresa,
            nome="Vodka Premium 1L",
            codigo_barras="789333444",
            sku="VOD-1L",
            categoria=self.categoria,
            preco_custo=Decimal('30.00'),
            preco_venda=Decimal('60.00'),
            estoque_atual=Decimal('0.000'),
            estoque_minimo=Decimal('5.000')
        )

        self.caixa = Caixa.objects.create(empresa=self.empresa, nome="Caixa 01", codigo_identificador="CX01")
        self.sessao = CashService.abrir_caixa(self.caixa, self.admin, Decimal('100.00'))

        self.client = Client()
        self.client.force_login(self.admin)

    # 1. Teste dos períodos suportados em parse_periodo
    def test_parse_periodo_todos_os_modos(self):
        hoje = get_operational_today()

        # hoje
        p_hoje = ReportService.parse_periodo('hoje')
        self.assertEqual(p_hoje['data_inicio'], hoje)
        self.assertEqual(p_hoje['data_fim'], hoje)

        # ontem
        p_ontem = ReportService.parse_periodo('ontem')
        self.assertEqual(p_ontem['data_inicio'], hoje - timedelta(days=1))
        self.assertEqual(p_ontem['data_fim'], hoje - timedelta(days=1))

        # 7dias
        p_7d = ReportService.parse_periodo('7dias')
        self.assertEqual(p_7d['data_inicio'], hoje - timedelta(days=6))
        self.assertEqual(p_7d['data_fim'], hoje)

        # 15dias
        p_15d = ReportService.parse_periodo('15dias')
        self.assertEqual(p_15d['data_inicio'], hoje - timedelta(days=14))
        self.assertEqual(p_15d['data_fim'], hoje)

        # 30dias
        p_30d = ReportService.parse_periodo('30dias')
        self.assertEqual(p_30d['data_inicio'], hoje - timedelta(days=29))
        self.assertEqual(p_30d['data_fim'], hoje)

        # semana_atual
        p_sem_atual = ReportService.parse_periodo('semana_atual')
        self.assertEqual(p_sem_atual['data_inicio'].weekday(), 0)
        self.assertEqual(p_sem_atual['data_fim'].weekday(), 6)

        # semana_anterior
        p_sem_ant = ReportService.parse_periodo('semana_anterior')
        self.assertEqual(p_sem_ant['data_inicio'].weekday(), 0)
        self.assertEqual(p_sem_ant['data_fim'].weekday(), 6)
        self.assertEqual(p_sem_ant['data_fim'] + timedelta(days=1), p_sem_atual['data_inicio'])

        # personalizado com inversão
        p_pers = ReportService.parse_periodo('personalizado', data_inicio_str='2026-09-20', data_fim_str='2026-09-10')
        self.assertEqual(p_pers['data_inicio'], date(2026, 9, 10))
        self.assertEqual(p_pers['data_fim'], date(2026, 9, 20))

    # 2. Teste do Relatório de Reposição trazendo Fornecedor
    def test_relatorio_reposicao_traz_fornecedor_e_status(self):
        # Registra venda do produto 1 (vende 5 unidades, estoque cai para 5 <= estoque_minimo de 20)
        SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.admin,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.produto_1.id, 'quantidade': 5, 'preco_venda': 9.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 45.00, 'troco': 0.00}]
        )

        p_info = ReportService.parse_periodo('hoje')
        report = ReportService.get_reposicao_report(self.empresa, p_info['start_datetime'], p_info['end_datetime'])

        self.assertEqual(len(report['produtos']), 1)
        item = report['produtos'][0]
        self.assertEqual(item['nome'], "Cerveja Pilsen 600ml")
        self.assertEqual(item['fornecedor_id'], self.fornecedor.id)
        self.assertEqual(item['fornecedor_nome'], "Bebidas Brasil")
        self.assertEqual(item['status_reposicao'], "REPOSIÇÃO NECESSÁRIA")

    # 3. Teste da View de Relatório de Reposição e Exportação CSV
    def test_view_reposicao_e_exportacao_csv(self):
        # GET na view
        resp = self.client.get(reverse('relatorio_reposicao') + '?periodo=7dias')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "RELATÓRIO DE REPOSIÇÃO")
        self.assertContains(resp, "Novo Pedido de Compra")

        # GET no CSV
        resp_csv = self.client.get(reverse('exportar_relatorio_csv', args=['reposicao']) + '?periodo=7dias')
        self.assertEqual(resp_csv.status_code, 200)
        self.assertEqual(resp_csv['Content-Type'], 'text/csv; charset=utf-8-sig')
        self.assertIn('Fornecedor Principal', resp_csv.content.decode('utf-8-sig'))

    # 4. Teste de Fornecedor: cálculo de prazo dinâmico
    def test_fornecedor_prazos_calculados(self):
        f_avista = Fornecedor.objects.create(
            empresa=self.empresa,
            razao_social="Forn A Vista LTDA",
            condicao_pagamento_padrao="A_VISTA"
        )
        self.assertEqual(f_avista.dias_prazo_calculados, 0)

        f_30d = Fornecedor.objects.create(
            empresa=self.empresa,
            razao_social="Forn 30d LTDA",
            condicao_pagamento_padrao="A_PRAZO_30"
        )
        self.assertEqual(f_30d.dias_prazo_calculados, 30)

        f_outro = Fornecedor.objects.create(
            empresa=self.empresa,
            razao_social="Forn Outro LTDA",
            condicao_pagamento_padrao="OUTRO",
            prazo_pagamento_dias=45
        )
        self.assertEqual(f_outro.dias_prazo_calculados, 45)

    # 5. Teste de Abertura de Novo Pedido de Compra preenchido pela Reposição
    def test_nova_compra_view_preenchimento_inicial(self):
        url = reverse('compra_nova') + f"?fornecedor_id={self.fornecedor.id}&produto_id[]={self.produto_1.id}&quantidade[]=12&preco_custo[]=5.00"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Bebidas Brasil")
        self.assertContains(resp, '"produto_id": ' + str(self.produto_1.id))

    # 6. Teste de Bloqueio de Caixa do Dia Anterior (Exigência de Fechamento Manual)
    def test_bloqueio_caixa_aberto_dia_anterior(self):
        # Simula que a sessão foi aberta ontem
        tz = timezone.get_current_timezone()
        ontem_dt = timezone.make_aware(datetime.combine(date.today() - timedelta(days=1), time(14, 0, 0)), tz)
        SessaoCaixa.objects.filter(id=self.sessao.id).update(data_abertura=ontem_dt)

        self.sessao.refresh_from_db()
        self.assertTrue(self.sessao.is_sessao_dia_anterior)

        # 1. Tentativa de registrar movimentação direta no serviço de caixa é bloqueada
        with self.assertRaises(ValueError) as ctx:
            CashService.registrar_movimentacao(
                sessao=self.sessao,
                tipo='SANGRIA',
                valor=Decimal('10.00'),
                motivo="Teste sangria",
                operador=self.admin
            )
        self.assertIn("precisa ser fechado antes de realizar novas", str(ctx.exception))

        # 2. Tentativa de processar venda atômica no PDV é bloqueada
        with self.assertRaises(ValueError) as ctx_venda:
            SaleService.processar_venda(
                empresa=self.empresa,
                operador=self.admin,
                sessao_caixa=self.sessao,
                itens_data=[{'produto_id': self.produto_1.id, 'quantidade': 1, 'preco_venda': 9.00}],
                pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 9.00, 'troco': 0.00}]
            )
        self.assertIn("precisa ser fechado antes de realizar novas", str(ctx_venda.exception))

        # 3. Tentativa de acessar o PDV front redireciona para a tela de fechar caixa com aviso
        resp_pdv = self.client.get(reverse('pdv_front'))
        self.assertEqual(resp_pdv.status_code, 302)
        self.assertIn('fechar', resp_pdv.url)
