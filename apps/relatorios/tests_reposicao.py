from datetime import date, datetime, time, timedelta
from decimal import Decimal
from django.test import TestCase, Client
from django.utils import timezone
from django.urls import reverse

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.produtos.models import Produto, Categoria, MovimentacaoEstoque
from apps.caixas.models import Caixa, SessaoCaixa
from apps.caixas.services import CashService
from apps.vendas.models import Venda, ItemVenda, PagamentoVenda
from apps.vendas.services import SaleService
from apps.relatorios.services import ReportService
from apps.core.operational_day import get_operational_today, get_operational_datetime_range


class RelatorioReposicaoTestCase(TestCase):
    def setUp(self):
        # 1. Empresas (Multi-tenancy)
        self.empresa_a = Empresa.objects.create(
            razao_social="Adega Reposicao A LTDA",
            nome_fantasia="Adega Reposicao A",
            cnpj="11111222000101"
        )
        self.empresa_b = Empresa.objects.create(
            razao_social="Adega Concorrente B LTDA",
            nome_fantasia="Adega B",
            cnpj="99999888000109"
        )

        # 2. Operador
        self.operador = Usuario.objects.create_user(
            username="gerente_reposicao",
            first_name="Carlos",
            last_name="Gerente",
            email="gerente@teste.com",
            password="password123",
            empresa=self.empresa_a,
            cargo='GERENTE'
        )

        # 3. Caixa e Sessão
        self.caixa = Caixa.objects.create(empresa=self.empresa_a, nome="Caixa Principal", codigo_identificador="CX-REP-01")
        self.sessao = CashService.abrir_caixa(self.caixa, self.operador, Decimal('100.00'))

        # 4. Produtos Empresa A
        self.cat_bebidas = Categoria.objects.create(empresa=self.empresa_a, nome="Bebidas")

        self.p_litrinha = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="78900111",
            sku="LIT-01",
            nome="Boa Litrinha",
            categoria=self.cat_bebidas,
            preco_custo=Decimal('2.50'),
            preco_venda=Decimal('4.00'),
            estoque_atual=Decimal('200.000'),
            estoque_minimo=Decimal('20.000'),
            controle_estoque=False
        )

        self.p_cerveja_x = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="78900222",
            sku="CERV-X",
            nome="Cerveja X",
            categoria=self.cat_bebidas,
            preco_custo=Decimal('5.00'),
            preco_venda=Decimal('10.00'),
            estoque_atual=Decimal('100.000'),
            estoque_minimo=Decimal('10.000'),
            controle_estoque=False
        )

        self.p_refri_y = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="78900333",
            sku="REF-Y",
            nome="Refrigerante Y",
            categoria=self.cat_bebidas,
            preco_custo=Decimal('3.00'),
            preco_venda=Decimal('6.00'),
            estoque_atual=Decimal('0.000'),
            estoque_minimo=Decimal('15.000'),
            controle_estoque=False
        )

        # 5. Produto Empresa B (para teste de multi-tenancy)
        self.p_empresa_b = Produto.objects.create(
            empresa=self.empresa_b,
            codigo_barras="78999999",
            sku="PROD-B",
            nome="Produto Empresa B",
            preco_custo=Decimal('10.00'),
            preco_venda=Decimal('20.00'),
            estoque_atual=Decimal('200.000'),
            estoque_minimo=Decimal('5.000'),
            controle_estoque=False
        )

        self.client = Client()
        self.client.force_login(self.operador)

    # 1. Geração Dinâmica de Semanas dos Últimos 18 Meses (ordenada do mais recente ao mais antigo)
    def test_geracao_dinamica_semanas_ultimos_18_meses(self):
        semanas = ReportService.get_semanas_ultimos_18_meses()
        self.assertGreaterEqual(len(semanas), 78)

        # Primeira semana é a semana corrente (mais recente)
        semana_atual = semanas[0]
        self.assertEqual(semana_atual['data_inicio'].weekday(), 0) # Segunda-feira
        self.assertEqual(semana_atual['data_fim'].weekday(), 6)    # Domingo
        self.assertEqual((semana_atual['data_fim'] - semana_atual['data_inicio']).days, 6)

        # Mais recente para a mais antiga
        for i in range(len(semanas) - 1):
            self.assertGreater(semanas[i]['data_inicio'], semanas[i + 1]['data_inicio'])

        # Formato do label
        self.assertIn("Semana", semana_atual['label'])
        self.assertIn("/", semana_atual['label'])
        self.assertIn(" a ", semana_atual['label'])

    # 2. Agrupamento, Soma de Quantidade, Faturamento e Lucro Obtido na Semana com Vendas
    def test_relatorio_reposicao_semana_com_vendas(self):
        semanas = ReportService.get_semanas_ultimos_18_meses()
        sem = semanas[0]
        start_dt, end_dt = get_operational_datetime_range(sem['data_inicio'], sem['data_fim'])

        # Venda 1: 10 Litrinhas (R$ 4.00 cada = 40.00, custo 2.50 = 25.00, lucro 15.00)
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.p_litrinha.id, 'quantidade': 10, 'preco_venda': 4.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 40.00, 'troco': 0.00}]
        )

        # Venda 2: 25 Litrinhas + 5 Cervejas X
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[
                {'produto_id': self.p_litrinha.id, 'quantidade': 25, 'preco_venda': 4.00},
                {'produto_id': self.p_cerveja_x.id, 'quantidade': 5, 'preco_venda': 10.00}
            ],
            pagamentos_data=[{'forma': 'PIX', 'valor': 150.00, 'troco': 0.00}]
        )

        # Ajusta estoque atual para 8 (<= estoque_minimo 20) para testar o status de reposição
        self.p_litrinha.estoque_atual = Decimal('8.000')
        self.p_litrinha.save()

        dados = ReportService.get_reposicao_report(self.empresa_a, start_dt, end_dt)

        self.assertTrue(dados['tem_vendas'])
        self.assertEqual(dados['total_itens_vendidos'], Decimal('40.000')) # 10 + 25 + 5
        self.assertEqual(dados['total_faturamento'], Decimal('190.00'))   # 40 + 100 + 50
        # Custo: Litrinha (35 * 2.50 = 87.50) + Cerveja (5 * 5.00 = 25.00) = 112.50
        # Lucro obtido: 190.00 - 112.50 = 77.50
        self.assertEqual(dados['total_lucro_obtido'], Decimal('77.50'))

        # Verifica produto agrupado
        litrinha_rep = next(p for p in dados['produtos'] if p['id'] == self.p_litrinha.id)
        self.assertEqual(litrinha_rep['quantidade'], Decimal('35.000'))
        self.assertEqual(litrinha_rep['total_vendido'], Decimal('140.00'))
        self.assertEqual(litrinha_rep['lucro_obtido'], Decimal('52.50'))
        self.assertEqual(litrinha_rep['status_reposicao'], 'REPOSIÇÃO NECESSÁRIA')

    # 3. Semana Sem Vendas (Cards com Zero e Lista Vazia Sem Erro)
    def test_relatorio_reposicao_semana_sem_vendas(self):
        semanas = ReportService.get_semanas_ultimos_18_meses()
        # Seleciona uma semana passada qualquer sem vendas
        sem = semanas[10]
        start_dt, end_dt = get_operational_datetime_range(sem['data_inicio'], sem['data_fim'])

        dados = ReportService.get_reposicao_report(self.empresa_a, start_dt, end_dt)

        self.assertFalse(dados['tem_vendas'])
        self.assertEqual(dados['total_itens_vendidos'], Decimal('0.00'))
        self.assertEqual(dados['total_faturamento'], Decimal('0.00'))
        self.assertEqual(dados['total_lucro_obtido'], Decimal('0.00'))
        self.assertIsNone(dados['produto_mais_vendido'])
        self.assertIsNone(dados['produto_maior_faturamento'])
        self.assertEqual(len(dados['produtos']), 0)

    # 4. Ordenação Primária por Quantidade Descendente e Secundária por Nome
    def test_ordenacao_quantidade_descendente_e_empate_nome(self):
        semanas = ReportService.get_semanas_ultimos_18_meses()
        sem = semanas[0]
        start_dt, end_dt = get_operational_datetime_range(sem['data_inicio'], sem['data_fim'])

        # Criar produto adicional com mesmo volume para testar empate alfabético
        p_agua = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="78900999",
            nome="Agua Mineral",
            preco_custo=Decimal('1.00'),
            preco_venda=Decimal('2.00'),
            estoque_atual=Decimal('100.000'),
            controle_estoque=False
        )
        p_energetico = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="78900888",
            nome="Energetico Z",
            preco_custo=Decimal('4.00'),
            preco_venda=Decimal('8.00'),
            estoque_atual=Decimal('50.000'),
            controle_estoque=False
        )

        # Vendas:
        # Boa Litrinha: 50 unidades (1º isolado)
        # Agua Mineral: 10 unidades (empate - 'A' antes de 'E')
        # Energetico Z: 10 unidades (empate)
        # Cerveja X: 5 unidades (último)
        SaleService.processar_venda(
            empresa=self.empresa_a, operador=self.operador, sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.p_litrinha.id, 'quantidade': 50, 'preco_venda': 4.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 200.00, 'troco': 0.00}]
        )
        SaleService.processar_venda(
            empresa=self.empresa_a, operador=self.operador, sessao_caixa=self.sessao,
            itens_data=[{'produto_id': p_energetico.id, 'quantidade': 10, 'preco_venda': 8.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 80.00, 'troco': 0.00}]
        )
        SaleService.processar_venda(
            empresa=self.empresa_a, operador=self.operador, sessao_caixa=self.sessao,
            itens_data=[{'produto_id': p_agua.id, 'quantidade': 10, 'preco_venda': 2.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 20.00, 'troco': 0.00}]
        )
        SaleService.processar_venda(
            empresa=self.empresa_a, operador=self.operador, sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.p_cerveja_x.id, 'quantidade': 5, 'preco_venda': 10.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 50.00, 'troco': 0.00}]
        )

        dados = ReportService.get_reposicao_report(self.empresa_a, start_dt, end_dt)

        nomes_ordenados = [p['nome'] for p in dados['produtos']]
        # 1º: Boa Litrinha (50 un)
        # 2º: Agua Mineral (10 un, 'A' antes de 'E')
        # 3º: Energetico Z (10 un)
        # 4º: Cerveja X (5 un)
        self.assertEqual(nomes_ordenados, ["Boa Litrinha", "Agua Mineral", "Energetico Z", "Cerveja X"])
        self.assertEqual(dados['produtos'][0]['posicao'], 1)
        self.assertEqual(dados['produtos'][1]['posicao'], 2)
        self.assertEqual(dados['produtos'][2]['posicao'], 3)
        self.assertEqual(dados['produtos'][3]['posicao'], 4)

    # 5. Distinção Clara entre Produto Mais Vendido (Quantidade) e Maior Faturamento (R$)
    def test_distincao_mais_vendido_vs_maior_faturamento(self):
        semanas = ReportService.get_semanas_ultimos_18_meses()
        sem = semanas[0]
        start_dt, end_dt = get_operational_datetime_range(sem['data_inicio'], sem['data_fim'])

        # Produto Barato: 100 un x R$ 2.00 = R$ 200.00 (Mais vendido em quantidade)
        p_barato = Produto.objects.create(
            empresa=self.empresa_a, codigo_barras="78901111", nome="Bala Unitária",
            preco_custo=Decimal('0.50'), preco_venda=Decimal('2.00'),
            estoque_atual=Decimal('200.000'),
            controle_estoque=False
        )
        # Produto Caro: 10 un x R$ 100.00 = R$ 1000.00 (Maior Faturamento)
        p_caro = Produto.objects.create(
            empresa=self.empresa_a, codigo_barras="78902222", nome="Whisky 12 Anos",
            preco_custo=Decimal('50.00'), preco_venda=Decimal('100.00'),
            estoque_atual=Decimal('50.000'),
            controle_estoque=False
        )

        SaleService.processar_venda(
            empresa=self.empresa_a, operador=self.operador, sessao_caixa=self.sessao,
            itens_data=[{'produto_id': p_barato.id, 'quantidade': 100, 'preco_venda': 2.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 200.00, 'troco': 0.00}]
        )
        SaleService.processar_venda(
            empresa=self.empresa_a, operador=self.operador, sessao_caixa=self.sessao,
            itens_data=[{'produto_id': p_caro.id, 'quantidade': 10, 'preco_venda': 100.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 1000.00, 'troco': 0.00}]
        )

        dados = ReportService.get_reposicao_report(self.empresa_a, start_dt, end_dt)

        self.assertEqual(dados['produto_mais_vendido']['nome'], "Bala Unitária")
        self.assertEqual(dados['produto_mais_vendido']['quantidade'], Decimal('100.000'))

        self.assertEqual(dados['produto_maior_faturamento']['nome'], "Whisky 12 Anos")
        self.assertEqual(dados['produto_maior_faturamento']['faturamento'], Decimal('1000.00'))

    # 6. Total Vendido por Produto Baseado no Preço Histórico e Não no Cadastro Atual
    def test_total_vendido_baseado_em_historico_real(self):
        semanas = ReportService.get_semanas_ultimos_18_meses()
        sem = semanas[0]
        start_dt, end_dt = get_operational_datetime_range(sem['data_inicio'], sem['data_fim'])

        # Venda 1: 10 unidades a R$ 4.00 = R$ 40.00
        SaleService.processar_venda(
            empresa=self.empresa_a, operador=self.operador, sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.p_litrinha.id, 'quantidade': 10, 'preco_venda': 4.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 40.00, 'troco': 0.00}]
        )
        # Venda 2: 5 unidades a R$ 4.50 = R$ 22.50
        SaleService.processar_venda(
            empresa=self.empresa_a, operador=self.operador, sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.p_litrinha.id, 'quantidade': 5, 'preco_venda': 4.50}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 22.50, 'troco': 0.00}]
        )

        # Alteramos o preço no cadastro atual para R$ 10.00
        self.p_litrinha.preco_venda = Decimal('10.00')
        self.p_litrinha.save()

        dados = ReportService.get_reposicao_report(self.empresa_a, start_dt, end_dt)

        litrinha_rep = next(p for p in dados['produtos'] if p['id'] == self.p_litrinha.id)
        # Total vendido deve ser 40.00 + 22.50 = 62.50 (e NÃO 15 * 10 = 150.00)
        self.assertEqual(litrinha_rep['quantidade'], Decimal('15.000'))
        self.assertEqual(litrinha_rep['total_vendido'], Decimal('62.50'))

    # 7. Exclusão de Vendas Canceladas
    def test_exclusao_de_vendas_canceladas(self):
        semanas = ReportService.get_semanas_ultimos_18_meses()
        sem = semanas[0]
        start_dt, end_dt = get_operational_datetime_range(sem['data_inicio'], sem['data_fim'])

        venda = SaleService.processar_venda(
            empresa=self.empresa_a, operador=self.operador, sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.p_litrinha.id, 'quantidade': 20, 'preco_venda': 4.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 80.00, 'troco': 0.00}]
        )
        # Cancela a venda
        venda.status = 'CANCELADA'
        venda.save()

        dados = ReportService.get_reposicao_report(self.empresa_a, start_dt, end_dt)
        self.assertFalse(dados['tem_vendas'])
        self.assertEqual(dados['total_itens_vendidos'], Decimal('0.00'))

    # 8. Isolamento Multi-tenancy Entre Empresas
    def test_isolamento_multitenancy(self):
        semanas = ReportService.get_semanas_ultimos_18_meses()
        sem = semanas[0]
        start_dt, end_dt = get_operational_datetime_range(sem['data_inicio'], sem['data_fim'])

        # Venda para Empresa B
        caixa_b = Caixa.objects.create(empresa=self.empresa_b, nome="Caixa B", codigo_identificador="CX-B")
        op_b = Usuario.objects.create_user(username="op_b", password="123", empresa=self.empresa_b, cargo='OPERADOR')
        sessao_b = CashService.abrir_caixa(caixa_b, op_b, Decimal('50.00'))

        SaleService.processar_venda(
            empresa=self.empresa_b, operador=op_b, sessao_caixa=sessao_b,
            itens_data=[{'produto_id': self.p_empresa_b.id, 'quantidade': 99, 'preco_venda': 20.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 1980.00, 'troco': 0.00}]
        )

        # Relatório para Empresa A NÃO deve conter o produto da Empresa B
        dados_a = ReportService.get_reposicao_report(self.empresa_a, start_dt, end_dt)
        self.assertEqual(len(dados_a['produtos']), 0)

        # Relatório para Empresa B deve conter apenas seu produto
        dados_b = ReportService.get_reposicao_report(self.empresa_b, start_dt, end_dt)
        self.assertEqual(len(dados_b['produtos']), 1)
        self.assertEqual(dados_b['produtos'][0]['nome'], "Produto Empresa B")

    # 9. Respeito ao Dia Operacional (Corte às 02:00:00 da manhã)
    def test_respeito_ao_dia_operacional_corte_2h(self):
        # Segunda-feira da semana de teste: 2026-08-31
        segunda = date(2026, 8, 31)
        domingo = date(2026, 9, 6)
        start_dt, end_dt = get_operational_datetime_range(segunda, domingo)

        # Início operacional da semana 31/08 é 2026-08-31 02:00:00
        # Fim operacional da semana 31/08 é 2026-09-07 01:59:59.999999 (madrugada de segunda seguinte)
        tz = timezone.get_current_timezone()

        # Venda A: Realizada na segunda-feira 31/08 às 01:30 da manhã -> Pertence ao domingo ANTERIOR (fora desta semana)
        venda_anterior = SaleService.processar_venda(
            empresa=self.empresa_a, operador=self.operador, sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.p_cerveja_x.id, 'quantidade': 10, 'preco_venda': 10.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 100.00, 'troco': 0.00}]
        )
        dt_fora = timezone.make_aware(datetime.combine(segunda, time(1, 30, 0)), tz)
        Venda.objects.filter(id=venda_anterior.id).update(data_venda=dt_fora)

        # Venda B: Realizada na segunda-feira 31/08 às 02:30 da manhã -> Pertence a ESTA semana operacional
        venda_dentro_inicio = SaleService.processar_venda(
            empresa=self.empresa_a, operador=self.operador, sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.p_litrinha.id, 'quantidade': 15, 'preco_venda': 4.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 60.00, 'troco': 0.00}]
        )
        dt_dentro_1 = timezone.make_aware(datetime.combine(segunda, time(2, 30, 0)), tz)
        Venda.objects.filter(id=venda_dentro_inicio.id).update(data_venda=dt_dentro_1)

        # Venda C: Realizada na segunda-feira seguinte 07/09 às 01:45 da manhã -> Pertence ao DOMINGO 06/09 (dentro desta semana)
        proxima_segunda = date(2026, 9, 7)
        venda_dentro_fim = SaleService.processar_venda(
            empresa=self.empresa_a, operador=self.operador, sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.p_litrinha.id, 'quantidade': 5, 'preco_venda': 4.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 20.00, 'troco': 0.00}]
        )
        dt_dentro_2 = timezone.make_aware(datetime.combine(proxima_segunda, time(1, 45, 0)), tz)
        Venda.objects.filter(id=venda_dentro_fim.id).update(data_venda=dt_dentro_2)

        dados = ReportService.get_reposicao_report(self.empresa_a, start_dt, end_dt)

        # Apenas as vendas B e C devem estar computadas (total 20 Litrinhas). Venda A (Cerveja X) ficou de fora.
        self.assertEqual(dados['total_itens_vendidos'], Decimal('20.000'))
        self.assertEqual(len(dados['produtos']), 1)
        self.assertEqual(dados['produtos'][0]['nome'], "Boa Litrinha")
        self.assertEqual(dados['produtos'][0]['quantidade'], Decimal('20.000'))

    # 10. Consulta Não Altera Estoque e Não Cria Movimentação
    def test_consulta_nao_altera_estoque(self):
        semanas = ReportService.get_semanas_ultimos_18_meses()
        sem = semanas[0]
        start_dt, end_dt = get_operational_datetime_range(sem['data_inicio'], sem['data_fim'])

        estoque_antes = Produto.objects.get(id=self.p_litrinha.id).estoque_atual
        movs_antes = MovimentacaoEstoque.objects.count()

        # Executa consulta do relatório
        ReportService.get_reposicao_report(self.empresa_a, start_dt, end_dt)

        estoque_depois = Produto.objects.get(id=self.p_litrinha.id).estoque_atual
        movs_depois = MovimentacaoEstoque.objects.count()

        self.assertEqual(estoque_antes, estoque_depois)
        self.assertEqual(movs_antes, movs_depois)

    # 11. Requisição HTTP da View `relatorio_reposicao_view` (Template e Contexto)
    def test_view_relatorio_reposicao_http(self):
        # 1. Sem parâmetro (usa semana atual)
        url = reverse('relatorio_reposicao')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'relatorios/relatorio_reposicao.html')
        self.assertIn('semanas', response.context)
        self.assertIn('semana_selecionada', response.context)
        self.assertIn('dados', response.context)
        self.assertContains(response, 'RELATÓRIO DE REPOSIÇÃO')
        self.assertContains(response, 'MINI DASHBOARD DE VENDAS')

        # 2. Com parâmetro de semana específica
        semanas = ReportService.get_semanas_ultimos_18_meses()
        semana_especifica = semanas[2]
        response2 = self.client.get(f"{url}?semana={semana_especifica['codigo']}")
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2.context['semana_selecionada']['codigo'], semana_especifica['codigo'])

    # 12. Exportação CSV do Relatório de Reposição
    def test_exportacao_csv_reposicao(self):
        # Cria uma venda na semana atual
        semanas = ReportService.get_semanas_ultimos_18_meses()
        sem_atual = semanas[0]

        SaleService.processar_venda(
            empresa=self.empresa_a, operador=self.operador, sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.p_litrinha.id, 'quantidade': 82, 'preco_venda': 4.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 328.00, 'troco': 0.00}]
        )

        url = reverse('exportar_relatorio_csv', kwargs={'relatorio_tipo': 'reposicao'})
        response = self.client.get(f"{url}?semana={sem_atual['codigo']}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8-sig')
        self.assertIn('attachment; filename="relatorio_reposicao_', response['Content-Disposition'])

        content = response.content.decode('utf-8-sig')
        self.assertIn('Posição;Produto;Código;Categoria;Custo Unitário (R$);Preço Venda Unitário (R$);Qtde. Vendida;Total Vendido (R$);Lucro Obtido (R$);Estoque Atual;Estoque Mínimo;Status Reposição', content)
        self.assertIn('Boa Litrinha', content)
        self.assertIn('82,000', content)
        self.assertIn('328,00', content)
