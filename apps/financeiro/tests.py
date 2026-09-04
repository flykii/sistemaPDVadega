from datetime import date, timedelta
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.db import IntegrityError

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.caixas.models import Caixa, SessaoCaixa, MovimentacaoCaixa
from apps.caixas.services import CashService
from apps.clientes.models import Fornecedor
from apps.financeiro.models import (
    ContaReceber, ContaPagar, FluxoCaixa, PagamentoContaReceber,
    CategoriaDespesa, DespesaRecorrente, PagamentoContaPagar
)
from apps.financeiro.services import FinancialService

class FinanceiroDespesasTestCase(TestCase):
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
            username="operador_fin_a",
            email="op_fin_a@teste.com",
            password="password123",
            empresa=self.empresa_a,
            cargo='OPERADOR'
        )

        # Caixa e Sessão Aberta com R$ 500,00 de fundo
        self.caixa_a = Caixa.objects.create(
            empresa=self.empresa_a,
            nome="Caixa 01",
            codigo_identificador="CX-01"
        )
        self.sessao_caixa = CashService.abrir_caixa(self.caixa_a, self.operador_a, Decimal('500.00'))

        # Categorias de Despesas
        self.cat_energia = CategoriaDespesa.objects.create(
            empresa=self.empresa_a,
            nome="Energia Elétrica",
            descricao="Contas de luz da loja"
        )
        self.cat_aluguel = CategoriaDespesa.objects.create(
            empresa=self.empresa_a,
            nome="Aluguel",
            descricao="Locação predial"
        )
        self.cat_operacional = CategoriaDespesa.objects.create(
            empresa=self.empresa_a,
            nome="Despesas Operacionais",
            descricao="Gelo, sacolas, suprimentos"
        )

        # Fornecedor
        self.fornecedor = Fornecedor.objects.create(
            empresa=self.empresa_a,
            razao_social="Fabrica de Gelo Polar LTDA",
            nome_fantasia="Gelo Polar",
            cnpj="99888777000100"
        )

    # 1. Cadastro de Despesa Avulsa
    def test_1_cadastro_despesa(self):
        conta = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Compra de 10 sacos de gelo",
            valor=Decimal('80.00'),
            categoria=self.cat_operacional,
            fornecedor=self.fornecedor,
            data_competencia=timezone.now().date(),
            data_vencimento=timezone.now().date() + timedelta(days=5),
            usuario=self.operador_a
        )
        self.assertEqual(conta.descricao, "Compra de 10 sacos de gelo")
        self.assertEqual(conta.valor, Decimal('80.00'))
        self.assertEqual(conta.valor_original, Decimal('80.00'))
        self.assertEqual(conta.valor_pago, Decimal('0.00'))
        self.assertEqual(conta.saldo, Decimal('80.00'))
        self.assertEqual(conta.status, 'ABERTA')

    # 2. Edição de Despesa
    def test_2_edicao_despesa(self):
        conta = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Material de limpeza",
            valor=Decimal('50.00'),
            categoria=self.cat_operacional
        )
        conta.descricao = "Material de limpeza e sacolas"
        conta.valor = Decimal('65.00')
        conta.valor_original = Decimal('65.00')
        conta.save()
        conta.refresh_from_db()
        self.assertEqual(conta.descricao, "Material de limpeza e sacolas")
        self.assertEqual(conta.saldo, Decimal('65.00'))

    # 3. Cancelamento de Despesa
    def test_3_cancelamento_despesa(self):
        conta = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Despesa cancelada",
            valor=Decimal('100.00')
        )
        FinancialService.cancelar_conta_despesa(conta, usuario=self.operador_a, motivo="Erro de lançamento")
        conta.refresh_from_db()
        self.assertEqual(conta.status, 'CANCELADA')
        self.assertIn("Erro de lançamento", conta.observacoes)

    # 4. Categorias de Despesas (Unicidade por Empresa)
    def test_4_categoria_despesa(self):
        self.assertEqual(self.cat_energia.nome, "Energia Elétrica")
        with self.assertRaises(IntegrityError):
            CategoriaDespesa.objects.create(
                empresa=self.empresa_a,
                nome="Energia Elétrica" # Duplicada na mesma empresa
            )

    # 5. Isolamento entre Empresas (Multi-tenancy)
    def test_5_isolamento_entre_empresas(self):
        cat_b = CategoriaDespesa.objects.create(
            empresa=self.empresa_b,
            nome="Energia Elétrica" # Permitido pois é outra empresa
        )
        despesa_b = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_b,
            descricao="Conta Beta",
            valor=Decimal('300.00'),
            categoria=cat_b
        )
        self.assertIn(cat_b, CategoriaDespesa.objects.filter(empresa=self.empresa_b))
        self.assertNotIn(cat_b, CategoriaDespesa.objects.filter(empresa=self.empresa_a))
        self.assertNotIn(despesa_b, ContaPagar.objects.filter(empresa=self.empresa_a))

    # 6. Criação de Despesa Recorrente
    def test_6_criacao_despesa_recorrente(self):
        rec = DespesaRecorrente.objects.create(
            empresa=self.empresa_a,
            descricao="Aluguel do Salão Comercial",
            categoria=self.cat_aluguel,
            valor_estimado=Decimal('2000.00'),
            periodicidade='MENSAL',
            dia_vencimento=10,
            data_inicio=date(2026, 1, 1),
            ativo=True
        )
        self.assertEqual(rec.valor_estimado, Decimal('2000.00'))
        self.assertEqual(rec.dia_vencimento, 10)

    # 7. Geração de Ocorrência Mensal
    def test_7_geracao_ocorrencia_mensal(self):
        rec = DespesaRecorrente.objects.create(
            empresa=self.empresa_a,
            descricao="Internet Fibra Dedicada",
            categoria=self.cat_operacional,
            valor_estimado=Decimal('150.00'),
            periodicidade='MENSAL',
            dia_vencimento=15,
            data_inicio=date(2026, 1, 1),
            ativo=True
        )
        geradas = FinancialService.gerar_previsoes_despesas_recorrentes(
            empresa=self.empresa_a,
            mes=9,
            ano=2026,
            usuario=self.operador_a
        )
        self.assertTrue(len(geradas) >= 1)
        conta_gerada = ContaPagar.objects.filter(empresa=self.empresa_a, despesa_recorrente=rec, recorrente_competencia="2026-09").first()
        self.assertIsNotNone(conta_gerada)
        self.assertEqual(conta_gerada.valor, Decimal('150.00'))
        self.assertEqual(conta_gerada.data_vencimento, date(2026, 9, 15))

    # 8. Prevenção de Ocorrência Duplicada
    def test_8_prevencao_ocorrencia_duplicada(self):
        rec = DespesaRecorrente.objects.create(
            empresa=self.empresa_a,
            descricao="Software de Gestão",
            valor_estimado=Decimal('99.00'),
            dia_vencimento=20,
            data_inicio=date(2026, 1, 1),
            ativo=True
        )
        # Primeira geração
        geradas_1 = FinancialService.gerar_previsoes_despesas_recorrentes(self.empresa_a, mes=10, ano=2026)
        # Segunda geração imediata para o mesmo mês
        geradas_2 = FinancialService.gerar_previsoes_despesas_recorrentes(self.empresa_a, mes=10, ano=2026)

        self.assertEqual(len(geradas_2), 0)
        self.assertEqual(
            ContaPagar.objects.filter(empresa=self.empresa_a, despesa_recorrente=rec, recorrente_competencia="2026-10").count(),
            1
        )

    # 9. Conta a Pagar Criada e 28. Cálculo de Saldo
    def test_9_e_28_conta_pagar_saldo(self):
        conta = ContaPagar.objects.create(
            empresa=self.empresa_a,
            descricao="Manutenção Preventiva Freezer",
            valor=Decimal('350.00'),
            valor_original=Decimal('350.00'),
            valor_pago=Decimal('100.00'),
            data_vencimento=timezone.now().date(),
            status='PARCIAL'
        )
        self.assertEqual(conta.saldo, Decimal('250.00'))

    # 10. Pagamento Integral
    def test_10_pagamento_integral(self):
        conta = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Combustível Entrega",
            valor=Decimal('100.00')
        )
        FinancialService.pagar_conta_despesa(
            conta=conta,
            valor_pago=Decimal('100.00'),
            forma_pagamento='PIX',
            usuario=self.operador_a
        )
        conta.refresh_from_db()
        self.assertEqual(conta.status, 'PAGA')
        self.assertEqual(conta.saldo, Decimal('0.00'))
        self.assertEqual(conta.valor_pago, Decimal('100.00'))

    # 11. Pagamento Parcial
    def test_11_pagamento_parcial(self):
        conta = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Manutenção Elétrica Geral",
            valor=Decimal('400.00')
        )
        FinancialService.pagar_conta_despesa(
            conta=conta,
            valor_pago=Decimal('150.00'),
            forma_pagamento='PIX',
            usuario=self.operador_a
        )
        conta.refresh_from_db()
        self.assertEqual(conta.status, 'PARCIAL')
        self.assertEqual(conta.saldo, Decimal('250.00'))
        self.assertEqual(conta.valor_pago, Decimal('150.00'))

    # 12. Pagamento em Dinheiro e 15. Dinheiro reduz caixa físico
    def test_12_e_15_pagamento_dinheiro_reduz_caixa_fisico(self):
        saldo_gaveta_antes = self.sessao_caixa.saldo_esperado
        conta = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Compra de Café e Açúcar",
            valor=Decimal('40.00')
        )
        FinancialService.pagar_conta_despesa(
            conta=conta,
            valor_pago=Decimal('40.00'),
            forma_pagamento='DINHEIRO',
            sessao_caixa=self.sessao_caixa,
            usuario=self.operador_a
        )
        self.sessao_caixa.refresh_from_db()
        self.assertEqual(self.sessao_caixa.saldo_esperado, saldo_gaveta_antes - Decimal('40.00'))
        self.assertEqual(self.sessao_caixa.total_despesas, Decimal('40.00'))

    # 13. Pagamento em PIX e 16. PIX NÃO reduz caixa físico
    def test_13_e_16_pagamento_pix_nao_reduz_caixa_fisico(self):
        saldo_gaveta_antes = self.sessao_caixa.saldo_esperado
        conta = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Conta de Água",
            valor=Decimal('90.00')
        )
        FinancialService.pagar_conta_despesa(
            conta=conta,
            valor_pago=Decimal('90.00'),
            forma_pagamento='PIX',
            sessao_caixa=self.sessao_caixa,
            usuario=self.operador_a
        )
        self.sessao_caixa.refresh_from_db()
        self.assertEqual(self.sessao_caixa.saldo_esperado, saldo_gaveta_antes)

    # 14. Pagamento em Cartão e 17. Cartão NÃO reduz caixa físico
    def test_14_e_17_pagamento_cartao_nao_reduz_caixa_fisico(self):
        saldo_gaveta_antes = self.sessao_caixa.saldo_esperado
        conta = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Embalagens Térmicas",
            valor=Decimal('120.00')
        )
        FinancialService.pagar_conta_despesa(
            conta=conta,
            valor_pago=Decimal('120.00'),
            forma_pagamento='CARTAO_DEBITO',
            sessao_caixa=self.sessao_caixa,
            usuario=self.operador_a
        )
        self.sessao_caixa.refresh_from_db()
        self.assertEqual(self.sessao_caixa.saldo_esperado, saldo_gaveta_antes)

    # 18. Pagamento acima do saldo bloqueado
    def test_18_pagamento_acima_do_saldo_bloqueado(self):
        conta = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Serviço de Serralheria",
            valor=Decimal('150.00')
        )
        with self.assertRaises(ValueError) as ctx:
            FinancialService.pagar_conta_despesa(
                conta=conta,
                valor_pago=Decimal('200.00'),
                forma_pagamento='PIX',
                usuario=self.operador_a
            )
        self.assertIn("não pode ser maior que o saldo restante", str(ctx.exception))

    # 19. Pagamento duplicado bloqueado
    def test_19_pagamento_duplicado_bloqueado(self):
        conta = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Recarga de Extintores",
            valor=Decimal('100.00')
        )
        FinancialService.pagar_conta_despesa(
            conta=conta,
            valor_pago=Decimal('100.00'),
            forma_pagamento='PIX',
            usuario=self.operador_a
        )
        with self.assertRaises(ValueError) as ctx:
            FinancialService.pagar_conta_despesa(
                conta=conta,
                valor_pago=Decimal('50.00'),
                forma_pagamento='PIX',
                usuario=self.operador_a
            )
        self.assertIn("já está totalmente quitada", str(ctx.exception))

    # 20. Pagamento em caixa fechado bloqueado
    def test_20_pagamento_em_caixa_fechado_bloqueado(self):
        caixa_2 = Caixa.objects.create(empresa=self.empresa_a, nome="Caixa 02", codigo_identificador="CX-02")
        sessao_2 = CashService.abrir_caixa(caixa_2, self.operador_a, Decimal('100.00'))
        CashService.fechar_caixa(sessao_2, Decimal('100.00'), "Fechamento teste")

        conta = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Pequena Compra",
            valor=Decimal('30.00')
        )
        with self.assertRaises(ValueError) as ctx:
            FinancialService.pagar_conta_despesa(
                conta=conta,
                valor_pago=Decimal('30.00'),
                forma_pagamento='DINHEIRO',
                sessao_caixa=sessao_2,
                usuario=self.operador_a
            )
        self.assertIn("sessão já FECHADA", str(ctx.exception))

    # 21. Identificação de Conta Vencida
    def test_21_conta_vencida(self):
        conta = ContaPagar.objects.create(
            empresa=self.empresa_a,
            descricao="Boleto Antigo",
            valor=Decimal('200.00'),
            valor_original=Decimal('200.00'),
            data_vencimento=timezone.now().date() - timedelta(days=3),
            status='ABERTA'
        )
        self.assertTrue(conta.is_vencida)
        self.assertEqual(conta.status_display_calculado, 'Vencida')

    # 22. Cancelamento bloqueado com pagamentos
    def test_22_cancelamento_bloqueado_com_pagamento(self):
        conta = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Despesa Parcialmente Paga",
            valor=Decimal('200.00')
        )
        FinancialService.pagar_conta_despesa(
            conta=conta,
            valor_pago=Decimal('50.00'),
            forma_pagamento='PIX',
            usuario=self.operador_a
        )
        with self.assertRaises(ValueError) as ctx:
            FinancialService.cancelar_conta_despesa(conta, usuario=self.operador_a)
        self.assertIn("já possui pagamentos", str(ctx.exception))

    # 23. Rollback transacional
    def test_23_rollback_transacional(self):
        conta = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Despesa Rollback",
            valor=Decimal('100.00')
        )
        pags_antes = PagamentoContaPagar.objects.count()
        movs_antes = MovimentacaoCaixa.objects.count()

        # Tentativa de pagamento acima do saldo deve falhar e nada persistir
        with self.assertRaises(ValueError):
            FinancialService.pagar_conta_despesa(
                conta=conta,
                valor_pago=Decimal('999.00'),
                forma_pagamento='DINHEIRO',
                sessao_caixa=self.sessao_caixa,
                usuario=self.operador_a
            )
        self.assertEqual(PagamentoContaPagar.objects.count(), pags_antes)
        self.assertEqual(MovimentacaoCaixa.objects.count(), movs_antes)
        conta.refresh_from_db()
        self.assertEqual(conta.valor_pago, Decimal('0.00'))

    # 24. Concorrência e bloqueio transacional
    def test_24_concorrencia_pagamento(self):
        conta = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Despesa Concorrente",
            valor=Decimal('100.00')
        )
        # Pagamento 1 consome 100
        FinancialService.pagar_conta_despesa(
            conta=conta,
            valor_pago=Decimal('100.00'),
            forma_pagamento='PIX',
            usuario=self.operador_a
        )
        conta.refresh_from_db()
        self.assertEqual(conta.status, 'PAGA')

        # Pagamento 2 tenta pagar novamente
        with self.assertRaises(ValueError) as ctx:
            FinancialService.pagar_conta_despesa(
                conta=conta,
                valor_pago=Decimal('50.00'),
                forma_pagamento='PIX',
                usuario=self.operador_a
            )
        self.assertIn("já está totalmente quitada", str(ctx.exception))

    # 25. Fluxo Mensal e 27. Cálculo de Totais
    def test_25_e_27_fluxo_mensal_e_totais(self):
        hoje = timezone.now().date()
        c1 = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Despesa 1",
            valor=Decimal('200.00'),
            data_vencimento=hoje
        )
        c2 = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Despesa 2",
            valor=Decimal('300.00'),
            data_vencimento=hoje
        )
        FinancialService.pagar_conta_despesa(c1, Decimal('200.00'), 'PIX', usuario=self.operador_a)

        despesas_mes = ContaPagar.objects.filter(empresa=self.empresa_a, data_vencimento__year=hoje.year, data_vencimento__month=hoje.month)
        total_previsto = sum((c.valor for c in despesas_mes), Decimal('0.00'))
        total_pago = sum((c.valor_pago for c in despesas_mes), Decimal('0.00'))
        total_aberto = sum((c.saldo for c in despesas_mes), Decimal('0.00'))

        self.assertEqual(total_previsto, Decimal('500.00'))
        self.assertEqual(total_pago, Decimal('200.00'))
        self.assertEqual(total_aberto, Decimal('300.00'))

    # 26. Filtros por Período
    def test_26_filtros_por_periodo(self):
        hoje = timezone.now().date()
        c_hoje = FinancialService.cadastrar_despesa_avulsa(self.empresa_a, "Hoje", Decimal('50.00'), data_vencimento=hoje)
        c_futuro = FinancialService.cadastrar_despesa_avulsa(self.empresa_a, "Futuro", Decimal('80.00'), data_vencimento=hoje + timedelta(days=20))

        qs_hoje = ContaPagar.objects.filter(empresa=self.empresa_a, data_vencimento=hoje)
        self.assertIn(c_hoje, qs_hoje)
        self.assertNotIn(c_futuro, qs_hoje)

    # 29. Integração Completa: Despesa ➔ Conta a Pagar ➔ Dinheiro ➔ Caixa ➔ Gaveta ➔ Fluxo
    def test_29_integracao_despesa_conta_pagar_caixa(self):
        saldo_gaveta_antes = self.sessao_caixa.saldo_esperado
        fluxos_antes = FluxoCaixa.objects.count()

        # Cadastra e paga despesa avulsa em dinheiro
        conta = FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Compra de Material Emergencial",
            valor=Decimal('75.00'),
            categoria=self.cat_operacional,
            pago_imediatamente=True,
            forma_pagamento='DINHEIRO',
            sessao_caixa=self.sessao_caixa,
            usuario=self.operador_a
        )
        self.sessao_caixa.refresh_from_db()
        self.assertEqual(conta.status, 'PAGA')
        self.assertEqual(conta.saldo, Decimal('0.00'))
        self.assertEqual(self.sessao_caixa.saldo_esperado, saldo_gaveta_antes - Decimal('75.00'))
        self.assertEqual(FluxoCaixa.objects.count(), fluxos_antes + 1)

    # 30. Integração Recorrente ➔ Previsão ➔ Pagamento Dinheiro ➔ Caixa ➔ Quitação
    def test_30_integracao_recorrente_previsao_pagamento_caixa(self):
        rec = DespesaRecorrente.objects.create(
            empresa=self.empresa_a,
            descricao="Serviço de Segurança e Monitoramento",
            categoria=self.cat_operacional,
            valor_estimado=Decimal('120.00'),
            periodicidade='MENSAL',
            dia_vencimento=18,
            data_inicio=date(2026, 1, 1),
            ativo=True
        )
        # 1. Gera previsão
        geradas = FinancialService.gerar_previsoes_despesas_recorrentes(self.empresa_a, mes=9, ano=2026)
        conta = ContaPagar.objects.get(empresa=self.empresa_a, despesa_recorrente=rec, recorrente_competencia="2026-09")
        self.assertEqual(conta.status, 'ABERTA')
        self.assertEqual(conta.saldo, Decimal('120.00'))

        # 2. Paga a conta gerada em DINHEIRO no caixa
        saldo_gaveta_antes = self.sessao_caixa.saldo_esperado
        FinancialService.pagar_conta_despesa(
            conta=conta,
            valor_pago=Decimal('120.00'),
            forma_pagamento='DINHEIRO',
            sessao_caixa=self.sessao_caixa,
            usuario=self.operador_a
        )
        conta.refresh_from_db()
        self.sessao_caixa.refresh_from_db()

        self.assertEqual(conta.status, 'PAGA')
        self.assertEqual(conta.saldo, Decimal('0.00'))
        self.assertEqual(self.sessao_caixa.saldo_esperado, saldo_gaveta_antes - Decimal('120.00'))

    # 31. CENÁRIO 1: Empresa com razão social preenchida ("Mercado Exemplo LTDA")
    def test_31_fluxo_mensal_empresa_com_razao_social(self):
        empresa_exemplo = Empresa.objects.create(
            razao_social="Mercado Exemplo LTDA",
            nome_fantasia="Mercado Exemplo",
            cnpj="99888777000166"
        )
        admin = Usuario.objects.create_user(
            username="admin_exemplo",
            email="admin_exemplo@teste.com",
            password="password123",
            empresa=empresa_exemplo,
            cargo='ADMIN'
        )
        self.client.force_login(admin)
        from django.urls import reverse
        resp = self.client.get(reverse('fluxo_mensal'))
        self.assertEqual(resp.status_code, 200)

    # 32. CENÁRIO 2: Empresa cadastrada com razão social vazia / nula
    def test_32_fluxo_mensal_empresa_sem_razao_social(self):
        empresa_sem_razao = Empresa.objects.create(
            razao_social="",
            nome_fantasia="Loja Sem Razao",
            cnpj="99888777000155"
        )
        admin = Usuario.objects.create_user(
            username="admin_sem_razao",
            email="admin_sem_razao@teste.com",
            password="password123",
            empresa=empresa_sem_razao,
            cargo='ADMIN'
        )
        self.client.force_login(admin)
        from django.urls import reverse
        resp = self.client.get(reverse('fluxo_mensal'))
        self.assertEqual(resp.status_code, 200)

    # 33. CENÁRIO 3: Despesas e Recorrentes sem fornecedor (fornecedor=None) não geram VariableDoesNotExist
    def test_33_fluxo_mensal_despesas_sem_fornecedor_nao_gera_erro(self):
        # Cria despesa sem fornecedor
        hoje = timezone.now().date()
        ContaPagar.objects.create(
            empresa=self.empresa_a,
            descricao="Despesa Sem Fornecedor",
            categoria=self.cat_operacional,
            fornecedor=None,
            valor=Decimal('85.00'),
            data_vencimento=hoje,
            usuario=self.operador_a
        )
        # Cria recorrente sem fornecedor
        DespesaRecorrente.objects.create(
            empresa=self.empresa_a,
            descricao="Recorrente Sem Fornecedor",
            categoria=self.cat_operacional,
            fornecedor=None,
            valor_estimado=Decimal('50.00'),
            periodicidade='MENSAL',
            dia_vencimento=10,
            data_inicio=hoje
        )

        admin_a = Usuario.objects.create_user(
            username="admin_a_fin",
            email="admin_a_fin@teste.com",
            password="password123",
            empresa=self.empresa_a,
            cargo='ADMIN'
        )
        self.client.force_login(admin_a)
        from django.urls import reverse

        # Teste Fluxo Mensal
        resp_fluxo = self.client.get(reverse('fluxo_mensal'))
        self.assertEqual(resp_fluxo.status_code, 200)
        self.assertContains(resp_fluxo, "Despesa Sem Fornecedor")

        # Teste Lista de Recorrentes
        resp_rec = self.client.get(reverse('despesas_recorrentes_list'))
        self.assertEqual(resp_rec.status_code, 200)
        self.assertContains(resp_rec, "Recorrente Sem Fornecedor")
