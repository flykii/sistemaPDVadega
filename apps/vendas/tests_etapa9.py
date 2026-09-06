"""
ETAPA 9 — Testes de Auditoria, Permissões por Cargo e Cancelamento/Estorno.
27+ testes cobrindo todos os cenários definidos na especificação.
"""
from decimal import Decimal
from django.test import TestCase, RequestFactory
from django.utils import timezone
from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.caixas.models import Caixa, SessaoCaixa
from apps.caixas.services import CashService
from apps.produtos.models import Produto, MovimentacaoEstoque
from apps.vendas.models import Venda, ItemVenda, PagamentoVenda
from apps.vendas.services import SaleService
from apps.clientes.models import Cliente
from apps.financeiro.models import FluxoCaixa, ContaReceber
from apps.core.models import AuditLog, AuditService


class BaseEtapa9TestCase(TestCase):
    """Setup compartilhado para os testes da Etapa 9."""

    def setUp(self):
        self.empresa = Empresa.objects.create(
            razao_social="Empresa Teste LTDA",
            nome_fantasia="Empresa Teste",
            cnpj="11.111.111/0001-11"
        )
        self.empresa2 = Empresa.objects.create(
            razao_social="Outra Empresa LTDA",
            nome_fantasia="Outra Empresa",
            cnpj="22.222.222/0001-22"
        )

        # Usuários com diferentes cargos
        self.admin = Usuario.objects.create_user(
            username='admin_teste', password='pass123',
            empresa=self.empresa, cargo='ADMIN'
        )
        self.gerente = Usuario.objects.create_user(
            username='gerente_teste', password='pass123',
            empresa=self.empresa, cargo='GERENTE'
        )
        self.operador = Usuario.objects.create_user(
            username='operador_teste', password='pass123',
            empresa=self.empresa, cargo='OPERADOR'
        )
        self.estoquista = Usuario.objects.create_user(
            username='estoquista_teste', password='pass123',
            empresa=self.empresa, cargo='ESTOQUISTA'
        )
        self.financeiro = Usuario.objects.create_user(
            username='financeiro_teste', password='pass123',
            empresa=self.empresa, cargo='FINANCEIRO'
        )

        # Caixa e sessão
        self.caixa = Caixa.objects.create(
            empresa=self.empresa, nome="Caixa 01", codigo_identificador="CX-01"
        )
        self.sessao = CashService.abrir_caixa(
            caixa=self.caixa, operador=self.operador,
            saldo_inicial=Decimal('200.00'), nome_operador="Operador"
        )

        # Produtos
        self.produto_a = Produto.objects.create(
            empresa=self.empresa, nome="Produto A", codigo_barras="111",
            preco_custo=Decimal('10.00'), preco_venda=Decimal('20.00'),
            estoque_atual=Decimal('50.000'), estoque_minimo=Decimal('5.000'),
            controle_estoque=True
        )
        self.produto_b = Produto.objects.create(
            empresa=self.empresa, nome="Produto B", codigo_barras="222",
            preco_custo=Decimal('5.00'), preco_venda=Decimal('15.00'),
            estoque_atual=Decimal('30.000'), estoque_minimo=Decimal('3.000'),
            controle_estoque=True
        )

        # Cliente
        self.cliente = Cliente.objects.create(
            empresa=self.empresa, nome="João Teste",
            cpf_cnpj="12345678901",
            limite_credito=Decimal('500.00'),
            saldo_devedor=Decimal('0.00')
        )

    def _criar_venda_dinheiro(self, total_desconto=Decimal('0.00')):
        """Helper: cria venda com dinheiro simples."""
        return SaleService.processar_venda(
            empresa=self.empresa,
            sessao_caixa=self.sessao,
            operador=self.operador,
            itens_data=[
                {'produto_id': self.produto_a.id, 'quantidade': 2},
            ],
            pagamentos_data=[
                {'forma': 'DINHEIRO', 'valor': Decimal('40.00') - total_desconto, 'troco': Decimal('0.00')},
            ],
            desconto=total_desconto,
        )

    def _criar_venda_pix(self):
        """Helper: cria venda com PIX."""
        return SaleService.processar_venda(
            empresa=self.empresa,
            sessao_caixa=self.sessao,
            operador=self.operador,
            itens_data=[
                {'produto_id': self.produto_a.id, 'quantidade': 1},
            ],
            pagamentos_data=[
                {'forma': 'PIX', 'valor': Decimal('20.00'), 'troco': Decimal('0.00')},
            ],
        )

    def _criar_venda_crediario(self):
        """Helper: cria venda com crediário."""
        return SaleService.processar_venda(
            empresa=self.empresa,
            sessao_caixa=self.sessao,
            operador=self.operador,
            cliente=self.cliente,
            itens_data=[
                {'produto_id': self.produto_b.id, 'quantidade': 2},
            ],
            pagamentos_data=[
                {'forma': 'CREDIARIO', 'valor': Decimal('30.00'), 'troco': Decimal('0.00')},
            ],
        )

    def _criar_venda_dividida(self):
        """Helper: cria venda com pagamento dividido (PIX R$20 + Dinheiro R$30 com troco R$10)."""
        return SaleService.processar_venda(
            empresa=self.empresa,
            sessao_caixa=self.sessao,
            operador=self.operador,
            itens_data=[
                {'produto_id': self.produto_a.id, 'quantidade': 2},
            ],
            pagamentos_data=[
                {'forma': 'PIX', 'valor': Decimal('20.00'), 'troco': Decimal('0.00')},
                {'forma': 'DINHEIRO', 'valor': Decimal('30.00'), 'troco': Decimal('10.00')},
            ],
        )

    def _criar_venda_crediario_dividida(self):
        """Helper: cria venda com PIX R$10 + Crediário R$20."""
        return SaleService.processar_venda(
            empresa=self.empresa,
            sessao_caixa=self.sessao,
            operador=self.operador,
            cliente=self.cliente,
            itens_data=[
                {'produto_id': self.produto_b.id, 'quantidade': 2},
            ],
            pagamentos_data=[
                {'forma': 'PIX', 'valor': Decimal('10.00'), 'troco': Decimal('0.00')},
                {'forma': 'CREDIARIO', 'valor': Decimal('20.00'), 'troco': Decimal('0.00')},
            ],
        )


# =============================================================================
# TESTES DE PERMISSÕES POR CARGO
# =============================================================================
class PermissoesPorCargoTest(BaseEtapa9TestCase):

    def test_01_admin_pode_cancelar_venda(self):
        self.assertTrue(self.admin.pode_cancelar_venda)

    def test_02_gerente_pode_cancelar_venda(self):
        self.assertTrue(self.gerente.pode_cancelar_venda)

    def test_03_operador_pode_cancelar_venda(self):
        self.assertTrue(self.operador.pode_cancelar_venda)

    def test_04_estoquista_nao_pode_cancelar_venda(self):
        self.assertFalse(self.estoquista.pode_cancelar_venda)

    def test_05_financeiro_nao_pode_cancelar_venda(self):
        self.assertFalse(self.financeiro.pode_cancelar_venda)

    def test_06_admin_pode_autorizar_desconto(self):
        self.assertTrue(self.admin.pode_autorizar_desconto)

    def test_07_operador_nao_pode_autorizar_desconto(self):
        self.assertFalse(self.operador.pode_autorizar_desconto)

    def test_08_operador_pode_operar_caixa(self):
        self.assertTrue(self.operador.pode_operar_caixa)

    def test_09_estoquista_nao_pode_operar_caixa(self):
        self.assertFalse(self.estoquista.pode_operar_caixa)

    def test_10_estoquista_pode_ajustar_estoque(self):
        self.assertTrue(self.estoquista.pode_ajustar_estoque)

    def test_11_operador_nao_pode_ajustar_estoque(self):
        self.assertFalse(self.operador.pode_ajustar_estoque)

    def test_12_financeiro_pode_operar_financeiro(self):
        self.assertTrue(self.financeiro.pode_operar_financeiro)

    def test_13_operador_nao_pode_operar_financeiro(self):
        self.assertFalse(self.operador.pode_operar_financeiro)

    def test_14_admin_pode_gerenciar_usuarios(self):
        self.assertTrue(self.admin.pode_gerenciar_usuarios)

    def test_15_gerente_nao_pode_gerenciar_usuarios(self):
        self.assertFalse(self.gerente.pode_gerenciar_usuarios)

    def test_16_superuser_tem_todas_permissoes(self):
        superuser = Usuario.objects.create_superuser(
            username='super', password='pass123', empresa=self.empresa
        )
        self.assertTrue(superuser.pode_cancelar_venda)
        self.assertTrue(superuser.pode_autorizar_desconto)
        self.assertTrue(superuser.pode_operar_caixa)
        self.assertTrue(superuser.pode_ajustar_estoque)
        self.assertTrue(superuser.pode_operar_financeiro)
        self.assertTrue(superuser.pode_gerenciar_usuarios)


# =============================================================================
# TESTES DE CANCELAMENTO DE VENDA
# =============================================================================
class CancelamentoVendaTest(BaseEtapa9TestCase):

    def test_17_cancelar_venda_dinheiro_estorna_estoque(self):
        """Cancelar venda em dinheiro deve devolver itens ao estoque."""
        venda = self._criar_venda_dinheiro()
        estoque_antes = Decimal('48.000')  # 50 - 2
        self.produto_a.refresh_from_db()
        self.assertEqual(self.produto_a.estoque_atual, estoque_antes)

        venda_cancelada = SaleService.cancelar_venda(
            venda_id=venda.id, empresa=self.empresa,
            usuario=self.admin, motivo="Teste de cancelamento"
        )
        self.assertEqual(venda_cancelada.status, 'CANCELADA')
        self.produto_a.refresh_from_db()
        self.assertEqual(self.produto_a.estoque_atual, Decimal('50.000'))

    def test_18_cancelar_venda_cria_movimentacao_estorno(self):
        """Cancelar deve criar MovimentacaoEstoque tipo ESTORNO."""
        venda = self._criar_venda_dinheiro()
        SaleService.cancelar_venda(
            venda_id=venda.id, empresa=self.empresa,
            usuario=self.admin, motivo="Teste estorno"
        )
        estornos = MovimentacaoEstoque.objects.filter(
            empresa=self.empresa, tipo='ESTORNO',
            origem_ref__startswith='CANC-'
        )
        self.assertEqual(estornos.count(), 1)
        self.assertEqual(estornos.first().quantidade, Decimal('2.000'))

    def test_19_cancelar_venda_dinheiro_cria_fluxo_saida(self):
        """Cancelar venda em dinheiro cria FluxoCaixa de SAIDA (estorno)."""
        venda = self._criar_venda_dinheiro()
        SaleService.cancelar_venda(
            venda_id=venda.id, empresa=self.empresa,
            usuario=self.admin, motivo="Estorno teste"
        )
        estornos_fluxo = FluxoCaixa.objects.filter(
            empresa=self.empresa, tipo='SAIDA', categoria='Estorno Venda'
        )
        self.assertEqual(estornos_fluxo.count(), 1)
        self.assertEqual(estornos_fluxo.first().valor, Decimal('40.00'))

    def test_20_cancelar_venda_pix_cria_fluxo_saida(self):
        """Cancelar venda em PIX cria FluxoCaixa de SAIDA."""
        venda = self._criar_venda_pix()
        SaleService.cancelar_venda(
            venda_id=venda.id, empresa=self.empresa,
            usuario=self.admin, motivo="Estorno PIX"
        )
        estornos_fluxo = FluxoCaixa.objects.filter(
            empresa=self.empresa, tipo='SAIDA', categoria='Estorno Venda'
        )
        self.assertEqual(estornos_fluxo.count(), 1)
        self.assertEqual(estornos_fluxo.first().valor, Decimal('20.00'))

    def test_21_cancelar_venda_dividida_cria_dois_fluxos(self):
        """Cancelar venda dividida (PIX + Dinheiro com troco) cria FluxoCaixa corretos."""
        venda = self._criar_venda_dividida()
        SaleService.cancelar_venda(
            venda_id=venda.id, empresa=self.empresa,
            usuario=self.admin, motivo="Estorno dividido"
        )
        estornos = FluxoCaixa.objects.filter(
            empresa=self.empresa, tipo='SAIDA', categoria='Estorno Venda'
        ).order_by('valor')
        self.assertEqual(estornos.count(), 2)
        # PIX: R$20 efetivo, Dinheiro: R$30-10=R$20 efetivo
        valores = sorted([e.valor for e in estornos])
        self.assertEqual(valores, [Decimal('20.00'), Decimal('20.00')])

    def test_22_cancelar_venda_crediario_reverte_saldo_devedor(self):
        """Cancelar venda em crediário deve reverter saldo_devedor do cliente."""
        venda = self._criar_venda_crediario()
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.saldo_devedor, Decimal('30.00'))

        SaleService.cancelar_venda(
            venda_id=venda.id, empresa=self.empresa,
            usuario=self.admin, motivo="Estorno crediário"
        )
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.saldo_devedor, Decimal('0.00'))

    def test_23_cancelar_venda_crediario_cancela_conta_receber(self):
        """Cancelar venda em crediário deve marcar ContaReceber como CANCELADA."""
        venda = self._criar_venda_crediario()
        SaleService.cancelar_venda(
            venda_id=venda.id, empresa=self.empresa,
            usuario=self.admin, motivo="Estorno crediário"
        )
        conta = ContaReceber.objects.filter(empresa=self.empresa, venda=venda).first()
        self.assertIsNotNone(conta)
        self.assertEqual(conta.status, 'CANCELADA')

    def test_24_cancelar_venda_dividida_com_crediario(self):
        """Cancelar venda PIX+Crediário: reverte saldo_devedor e cria FluxoCaixa para PIX."""
        venda = self._criar_venda_crediario_dividida()
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.saldo_devedor, Decimal('20.00'))

        SaleService.cancelar_venda(
            venda_id=venda.id, empresa=self.empresa,
            usuario=self.admin, motivo="Estorno dividido com crediário"
        )
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.saldo_devedor, Decimal('0.00'))

        # Verifica FluxoCaixa de estorno (apenas PIX, crediário não gera FluxoCaixa)
        estornos_fluxo = FluxoCaixa.objects.filter(
            empresa=self.empresa, tipo='SAIDA', categoria='Estorno Venda'
        )
        self.assertEqual(estornos_fluxo.count(), 1)
        self.assertEqual(estornos_fluxo.first().valor, Decimal('10.00'))


# =============================================================================
# TESTES DE BLOQUEIO DE DUPLO CANCELAMENTO
# =============================================================================
class DuploCancelamentoTest(BaseEtapa9TestCase):

    def test_25_duplo_cancelamento_bloqueado(self):
        """Tentar cancelar venda já cancelada deve lançar ValueError."""
        venda = self._criar_venda_dinheiro()
        SaleService.cancelar_venda(
            venda_id=venda.id, empresa=self.empresa,
            usuario=self.admin, motivo="Primeiro cancelamento"
        )
        with self.assertRaises(ValueError) as ctx:
            SaleService.cancelar_venda(
                venda_id=venda.id, empresa=self.empresa,
                usuario=self.admin, motivo="Segundo cancelamento"
            )
        self.assertIn("já foi cancelada", str(ctx.exception))

    def test_26_duplo_cancelamento_nao_duplica_estorno_estoque(self):
        """Duplo cancelamento bloqueado não cria segunda MovimentacaoEstoque de estorno."""
        venda = self._criar_venda_dinheiro()
        SaleService.cancelar_venda(
            venda_id=venda.id, empresa=self.empresa,
            usuario=self.admin, motivo="Cancelamento único"
        )
        estornos_antes = MovimentacaoEstoque.objects.filter(tipo='ESTORNO').count()

        with self.assertRaises(ValueError):
            SaleService.cancelar_venda(
                venda_id=venda.id, empresa=self.empresa,
                usuario=self.admin, motivo="Tentativa de segundo estorno"
            )
        estornos_depois = MovimentacaoEstoque.objects.filter(tipo='ESTORNO').count()
        self.assertEqual(estornos_antes, estornos_depois)


# =============================================================================
# TESTES DE PERMISSÃO NO CANCELAMENTO
# =============================================================================
class PermissaoCancelamentoTest(BaseEtapa9TestCase):

    def test_27_operador_nao_pode_cancelar_venda_de_outro_operador(self):
        """Operador de caixa não tem permissão para cancelar vendas de outro operador."""
        venda = self._criar_venda_dinheiro()
        outro_operador = Usuario.objects.create_user(
            username='outro_operador_teste', password='pass123',
            empresa=self.empresa, cargo='OPERADOR'
        )
        with self.assertRaises(PermissionError) as ctx:
            SaleService.cancelar_venda(
                venda_id=venda.id, empresa=self.empresa,
                usuario=outro_operador, motivo="Tentativa operador"
            )
        self.assertIn("permissão", str(ctx.exception).lower())

    def test_28_motivo_obrigatorio(self):
        """Cancelamento sem motivo deve lançar ValueError."""
        venda = self._criar_venda_dinheiro()
        with self.assertRaises(ValueError) as ctx:
            SaleService.cancelar_venda(
                venda_id=venda.id, empresa=self.empresa,
                usuario=self.admin, motivo=""
            )
        self.assertIn("obrigatório", str(ctx.exception).lower())

    def test_29_motivo_somente_espacos_rejeitado(self):
        """Cancelamento com motivo apenas espaços deve lançar ValueError."""
        venda = self._criar_venda_dinheiro()
        with self.assertRaises(ValueError) as ctx:
            SaleService.cancelar_venda(
                venda_id=venda.id, empresa=self.empresa,
                usuario=self.admin, motivo="   "
            )
        self.assertIn("obrigatório", str(ctx.exception).lower())


# =============================================================================
# TESTES DE AUDITORIA
# =============================================================================
class AuditoriaTest(BaseEtapa9TestCase):

    def test_30_cancelamento_cria_audit_log(self):
        """Cancelar venda cria AuditLog com ação VENDA_CANCELADA."""
        venda = self._criar_venda_dinheiro()
        SaleService.cancelar_venda(
            venda_id=venda.id, empresa=self.empresa,
            usuario=self.admin, motivo="Teste auditoria"
        )
        log = AuditLog.objects.filter(
            empresa=self.empresa, acao='VENDA_CANCELADA'
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.usuario, self.admin)
        self.assertEqual(log.entidade, 'Venda')
        self.assertEqual(log.entidade_id, str(venda.id))
        self.assertIn("Teste auditoria", log.motivo)

    def test_31_audit_log_registra_dados_anteriores_e_posteriores(self):
        """AuditLog deve conter dados_anteriores e dados_posteriores."""
        venda = self._criar_venda_dinheiro()
        SaleService.cancelar_venda(
            venda_id=venda.id, empresa=self.empresa,
            usuario=self.admin, motivo="Teste dados"
        )
        log = AuditLog.objects.get(empresa=self.empresa, acao='VENDA_CANCELADA')
        self.assertEqual(log.dados_anteriores['status'], 'CONCLUIDA')
        self.assertEqual(log.dados_posteriores['status'], 'CANCELADA')
        self.assertEqual(log.dados_posteriores['cancelado_por'], 'admin_teste')

    def test_32_audit_service_registrar_direto(self):
        """AuditService.registrar deve criar AuditLog diretamente."""
        log = AuditService.registrar(
            empresa=self.empresa,
            usuario=self.admin,
            acao='CAIXA_ABERTO',
            entidade='SessaoCaixa',
            entidade_id=99,
            descricao='Caixa aberto para teste',
            motivo='Teste direto'
        )
        self.assertEqual(log.acao, 'CAIXA_ABERTO')
        self.assertEqual(log.entidade_id, '99')
        self.assertIsNotNone(log.data_hora)


# =============================================================================
# TESTES DE CAMPOS DE CANCELAMENTO NA VENDA
# =============================================================================
class CamposCancelamentoTest(BaseEtapa9TestCase):

    def test_33_venda_cancelada_tem_campos_preenchidos(self):
        """Venda cancelada deve ter motivo, cancelado_por e data preenchidos."""
        venda = self._criar_venda_dinheiro()
        venda_cancelada = SaleService.cancelar_venda(
            venda_id=venda.id, empresa=self.empresa,
            usuario=self.gerente, motivo="Cliente desistiu"
        )
        venda_cancelada.refresh_from_db()
        self.assertEqual(venda_cancelada.status, 'CANCELADA')
        self.assertEqual(venda_cancelada.motivo_cancelamento, "Cliente desistiu")
        self.assertEqual(venda_cancelada.cancelado_por, self.gerente)
        self.assertIsNotNone(venda_cancelada.data_cancelamento)

    def test_34_venda_concluida_campos_cancelamento_vazios(self):
        """Venda concluída deve ter campos de cancelamento vazios."""
        venda = self._criar_venda_dinheiro()
        venda.refresh_from_db()
        self.assertEqual(venda.status, 'CONCLUIDA')
        self.assertEqual(venda.motivo_cancelamento, '')
        self.assertIsNone(venda.cancelado_por)
        self.assertIsNone(venda.data_cancelamento)


# =============================================================================
# TESTES DE ISOLAMENTO MULTI-TENANT
# =============================================================================
class MultiTenantCancelamentoTest(BaseEtapa9TestCase):

    def test_35_cancelar_venda_outra_empresa_bloqueado(self):
        """Não é possível cancelar venda de outra empresa."""
        venda = self._criar_venda_dinheiro()
        admin2 = Usuario.objects.create_user(
            username='admin2', password='pass123',
            empresa=self.empresa2, cargo='ADMIN'
        )
        with self.assertRaises(ValueError) as ctx:
            SaleService.cancelar_venda(
                venda_id=venda.id, empresa=self.empresa2,
                usuario=admin2, motivo="Tentativa cross-tenant"
            )
        self.assertIn("não encontrada", str(ctx.exception).lower())

    def test_36_audit_log_pertence_empresa_correta(self):
        """AuditLog de cancelamento pertence à empresa da venda."""
        venda = self._criar_venda_dinheiro()
        SaleService.cancelar_venda(
            venda_id=venda.id, empresa=self.empresa,
            usuario=self.admin, motivo="Teste tenant"
        )
        log = AuditLog.objects.get(acao='VENDA_CANCELADA')
        self.assertEqual(log.empresa, self.empresa)

        # Empresa 2 não deve ver logs
        logs_outra = AuditLog.objects.filter(empresa=self.empresa2)
        self.assertEqual(logs_outra.count(), 0)


# =============================================================================
# TESTES DE VENDAS CANCELADAS NÃO APARECEM NO FATURAMENTO
# =============================================================================
class VendasCanceladasRelatoriosTest(BaseEtapa9TestCase):

    def test_37_venda_cancelada_nao_soma_faturamento(self):
        """Vendas CANCELADAS devem ser excluídas de somas de faturamento."""
        venda1 = self._criar_venda_dinheiro()
        venda2 = self._criar_venda_pix()

        # Cancelar venda1
        SaleService.cancelar_venda(
            venda_id=venda1.id, empresa=self.empresa,
            usuario=self.admin, motivo="Cancelada"
        )

        # Faturamento válido = apenas venda2 (R$20)
        from django.db.models import Sum
        faturamento = Venda.objects.filter(
            empresa=self.empresa, status='CONCLUIDA'
        ).aggregate(total=Sum('total'))['total'] or Decimal('0.00')
        self.assertEqual(faturamento, Decimal('20.00'))

    def test_38_venda_cancelada_permanece_no_historico(self):
        """Vendas canceladas devem permanecer visíveis no histórico (com status CANCELADA)."""
        venda = self._criar_venda_dinheiro()
        SaleService.cancelar_venda(
            venda_id=venda.id, empresa=self.empresa,
            usuario=self.admin, motivo="Cancelada"
        )
        todas = Venda.objects.filter(empresa=self.empresa)
        self.assertEqual(todas.count(), 1)
        self.assertEqual(todas.first().status, 'CANCELADA')


# =============================================================================
# TESTES DA VIEW DE CANCELAMENTO
# =============================================================================
class ViewCancelamentoTest(BaseEtapa9TestCase):

    def test_39_view_cancelar_post_sucesso(self):
        """POST para cancelar venda com usuário autorizado retorna sucesso."""
        venda = self._criar_venda_dinheiro()
        self.client.login(username='admin_teste', password='pass123')
        response = self.client.post(
            f'/vendas/{venda.id}/cancelar/',
            {'motivo': 'Cancelamento via view'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

    def test_40_view_cancelar_sem_motivo_retorna_400(self):
        """POST sem motivo retorna 400."""
        venda = self._criar_venda_dinheiro()
        self.client.login(username='admin_teste', password='pass123')
        response = self.client.post(
            f'/vendas/{venda.id}/cancelar/',
            {'motivo': ''}
        )
        self.assertEqual(response.status_code, 400)

    def test_41_view_cancelar_operador_retorna_403(self):
        """Operador tentando cancelar via view venda de outro operador retorna 403."""
        venda = self._criar_venda_dinheiro()
        Usuario.objects.create_user(
            username='outro_operador_view', password='pass123',
            empresa=self.empresa, cargo='OPERADOR'
        )
        self.client.login(username='outro_operador_view', password='pass123')
        response = self.client.post(
            f'/vendas/{venda.id}/cancelar/',
            {'motivo': 'Tentativa operador'}
        )
        self.assertEqual(response.status_code, 403)

    def test_42_view_cancelar_get_retorna_405(self):
        """GET para cancelar venda retorna 405 (Method Not Allowed)."""
        venda = self._criar_venda_dinheiro()
        self.client.login(username='admin_teste', password='pass123')
        response = self.client.get(f'/vendas/{venda.id}/cancelar/')
        self.assertEqual(response.status_code, 405)

    def test_43_view_cancelar_duplo_retorna_400(self):
        """POST duplo para cancelar mesma venda retorna 400."""
        venda = self._criar_venda_dinheiro()
        self.client.login(username='admin_teste', password='pass123')
        self.client.post(
            f'/vendas/{venda.id}/cancelar/',
            {'motivo': 'Primeiro'}
        )
        response = self.client.post(
            f'/vendas/{venda.id}/cancelar/',
            {'motivo': 'Segundo'}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('cancelada', response.json()['error'].lower())
