from decimal import Decimal
import json
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.produtos.models import Produto, Categoria, MovimentacaoEstoque
from apps.clientes.models import Cliente
from apps.caixas.models import Caixa, SessaoCaixa
from apps.vendas.models import Venda, ItemVenda, PagamentoVenda
from apps.vendas.services import SaleService
from apps.financeiro.models import ContaReceber, FluxoCaixa


class Etapa14UsuariosPermissoesMultiempresaTests(TestCase):
    def setUp(self):
        # 1. Cria Empresas
        self.empresa_a = Empresa.objects.create(
            nome_fantasia="Adega Alfa",
            razao_social="Alfa Bebidas LTDA",
            cnpj="11.111.111/0001-11"
        )
        self.empresa_b = Empresa.objects.create(
            nome_fantasia="Adega Beta",
            razao_social="Beta Bebidas LTDA",
            cnpj="22.222.222/0001-22"
        )
        self.empresa_sem_razao = Empresa.objects.create(
            nome_fantasia="Adega Sem Razão",
            razao_social="",
            cnpj="33.333.333/0001-33"
        )

        # 2. Cria Usuários Empresa A
        self.admin_a = Usuario.objects.create_user(
            username='admin_a',
            password='password123',
            first_name='Admin',
            last_name='Alfa',
            empresa=self.empresa_a,
            cargo='ADMIN'
        )
        self.operador_a1 = Usuario.objects.create_user(
            username='op_a1',
            password='password123',
            first_name='Operador 1',
            empresa=self.empresa_a,
            cargo='OPERADOR'
        )
        self.operador_a2 = Usuario.objects.create_user(
            username='op_a2',
            password='password123',
            first_name='Operador 2',
            empresa=self.empresa_a,
            cargo='OPERADOR'
        )

        # 3. Cria Usuários Empresa B
        self.admin_b = Usuario.objects.create_user(
            username='admin_b',
            password='password123',
            first_name='Admin',
            last_name='Beta',
            empresa=self.empresa_b,
            cargo='ADMIN'
        )
        self.operador_b = Usuario.objects.create_user(
            username='op_b',
            password='password123',
            first_name='Operador B',
            empresa=self.empresa_b,
            cargo='OPERADOR'
        )

        # 4. Cria Produtos e Caixas para Empresa A
        self.cat_a = Categoria.objects.create(empresa=self.empresa_a, nome="Vinhos", ativo=True)
        self.prod_vinho_a = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Vinho Tinto Seco",
            codigo_barras="7890001",
            categoria=self.cat_a,
            preco_custo=Decimal('20.00'),
            preco_venda=Decimal('35.00'),
            estoque_atual=Decimal('50.000'),
            estoque_minimo=Decimal('5.000'),
            ativo=True
        )
        self.caixa_a = Caixa.objects.create(
            empresa=self.empresa_a,
            nome="Caixa Principal A",
            codigo_identificador="CX01"
        )
        self.sessao_a = SessaoCaixa.objects.create(
            empresa=self.empresa_a,
            caixa=self.caixa_a,
            operador=self.operador_a1,
            saldo_inicial=Decimal('100.00'),
            status='ABERTA'
        )

        # Cliente Empresa A com limite
        self.cliente_a = Cliente.objects.create(
            empresa=self.empresa_a,
            nome="Cliente Especial A",
            cpf_cnpj="12345678901",
            limite_credito=Decimal('500.00'),
            saldo_devedor=Decimal('0.00'),
            ativo=True
        )

        # 5. Cliente e Produto Empresa B
        self.prod_b = Produto.objects.create(
            empresa=self.empresa_b,
            nome="Produto Exclusivo B",
            codigo_barras="7890002",
            preco_custo=Decimal('10.00'),
            preco_venda=Decimal('20.00'),
            estoque_atual=Decimal('30.000'),
            ativo=True
        )
        self.cliente_b = Cliente.objects.create(
            empresa=self.empresa_b,
            nome="Cliente Exclusivo B",
            ativo=True
        )

        self.client = Client()

    # =========================================================================
    # 1. TESTES DE GESTÃO DE USUÁRIOS E VÍNCULO AUTOMÁTICO DE TENANT
    # =========================================================================
    def test_admin_cria_usuario_vinculado_automaticamente_a_mesma_empresa(self):
        """Admin cria usuário via POST e o backend vincula obrigatoriamente à empresa do admin."""
        self.client.force_login(self.admin_a)

        post_data = {
            'username': 'novo_operador_a',
            'first_name': 'Novo',
            'last_name': 'Operador',
            'email': 'novo@alfa.com',
            'cargo': 'OPERADOR',
            'password': 'password123',
            'confirmar_senha': 'password123',
            'pin_caixa': '9876',
            'telefone': '11999998888',
            'limite_desconto_pct': '10.00',
            'is_active': 'on',
        }
        response = self.client.post(reverse('usuario_novo'), post_data)
        self.assertRedirects(response, reverse('usuarios_list'))

        novo_user = Usuario.objects.get(username='novo_operador_a')
        self.assertEqual(novo_user.empresa, self.empresa_a)
        self.assertEqual(novo_user.cargo, 'OPERADOR')
        self.assertTrue(novo_user.is_active)
        self.assertEqual(novo_user.pin_caixa, '9876')

    def test_admin_nao_pode_escolher_ou_alterar_empresa_do_usuario(self):
        """Tentativa de enviar empresa_id diferente via POST é totalmente ignorada pelo backend."""
        self.client.force_login(self.admin_a)

        # Tentativa de injeção de empresa_id=empresa_b na criação
        post_data = {
            'username': 'usuario_spoof_empresa',
            'first_name': 'Hacker',
            'cargo': 'OPERADOR',
            'password': 'password123',
            'confirmar_senha': 'password123',
            'empresa_id': str(self.empresa_b.id),  # Injeção maliciosa
            'empresa': str(self.empresa_b.id),
            'is_active': 'on',
        }
        self.client.post(reverse('usuario_novo'), post_data)

        user_criado = Usuario.objects.get(username='usuario_spoof_empresa')
        self.assertEqual(user_criado.empresa, self.empresa_a)
        self.assertNotEqual(user_criado.empresa, self.empresa_b)

        # Tentativa de injeção na edição
        edit_data = {
            'first_name': 'Nome Alterado',
            'cargo': 'GERENTE',
            'empresa_id': str(self.empresa_b.id),
            'empresa': str(self.empresa_b.id),
            'is_active': 'on',
        }
        self.client.post(reverse('usuario_editar', args=[user_criado.id]), edit_data)
        user_criado.refresh_from_db()
        self.assertEqual(user_criado.empresa, self.empresa_a)

    def test_isolamento_empresa_a_nao_acessa_usuarios_empresa_b(self):
        """Admin da Empresa A não visualiza os usuários da Empresa B na listagem."""
        self.client.force_login(self.admin_a)

        response = self.client.get(reverse('usuarios_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'op_a1')
        self.assertContains(response, 'op_a2')
        self.assertNotContains(response, 'op_b')
        self.assertNotContains(response, 'admin_b')

    def test_tentativa_manipulacao_id_usuario_outra_empresa_retorna_404(self):
        """Admin da Empresa A tenta editar, inativar ou resetar senha de usuário da Empresa B -> 404."""
        self.client.force_login(self.admin_a)

        # Tenta editar usuário da empresa B
        resp_edit = self.client.get(reverse('usuario_editar', args=[self.operador_b.id]))
        self.assertEqual(resp_edit.status_code, 404)

        # Tenta toggle ativo de usuário da empresa B
        resp_toggle = self.client.get(reverse('usuario_toggle_ativo', args=[self.operador_b.id]))
        self.assertEqual(resp_toggle.status_code, 404)

        # Tenta resetar senha de usuário da empresa B
        resp_senha = self.client.get(reverse('usuario_redefinir_senha', args=[self.operador_b.id]))
        self.assertEqual(resp_senha.status_code, 404)

    def test_toggle_ativo_e_redefinir_senha_usuario(self):
        """Valida inativação/ativação e redefinição de senha com sucesso."""
        self.client.force_login(self.admin_a)

        # Inativa operador A2
        self.client.get(reverse('usuario_toggle_ativo', args=[self.operador_a2.id]))
        self.operador_a2.refresh_from_db()
        self.assertFalse(self.operador_a2.is_active)

        # Redefine senha do operador A2
        resp = self.client.post(reverse('usuario_redefinir_senha', args=[self.operador_a2.id]), {
            'nova_senha': 'novaSenhaSegura123',
            'confirmar_senha': 'novaSenhaSegura123'
        })
        self.assertRedirects(resp, reverse('usuarios_list'))

        # Confirma que a nova senha funciona
        # Reativa via toggle ativo
        self.client.force_login(self.admin_a)
        self.client.get(reverse('usuario_toggle_ativo', args=[self.operador_a2.id]))
        self.operador_a2.refresh_from_db()
        self.assertTrue(self.operador_a2.is_active)

        # Testa login com a nova senha após reativação
        self.client.logout()
        login_ok = self.client.login(username='op_a2', password='novaSenhaSegura123')
        self.assertTrue(login_ok)

    # =========================================================================
    # 2. TESTES DE PDV, OPERAÇÃO E CANCELAMENTO DE VENDAS
    # =========================================================================
    def test_operador_acessa_pdv_e_realiza_venda(self):
        """Operador acessa o PDV e realiza venda com sucesso."""
        self.client.force_login(self.operador_a1)

        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a1,
            sessao_caixa=self.sessao_a,
            itens_data=[{'produto_id': self.prod_vinho_a.id, 'quantidade': 2, 'preco_venda': '35.00'}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': '70.00', 'troco': '0.00'}]
        )

        self.assertEqual(venda.status, 'CONCLUIDA')
        self.assertEqual(venda.total, Decimal('70.00'))
        self.prod_vinho_a.refresh_from_db()
        self.assertEqual(self.prod_vinho_a.estoque_atual, Decimal('48.000'))

    def test_operador_cancela_propria_venda_com_sucesso(self):
        """Operador pode cancelar a venda que ele próprio realizou."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a1,
            sessao_caixa=self.sessao_a,
            itens_data=[{'produto_id': self.prod_vinho_a.id, 'quantidade': 3, 'preco_venda': '35.00'}],
            pagamentos_data=[{'forma': 'PIX', 'valor': '105.00', 'troco': '0.00'}]
        )

        # Operador 1 cancela sua própria venda
        venda_cancelada = SaleService.cancelar_venda(
            venda_id=venda.id,
            empresa=self.empresa_a,
            usuario=self.operador_a1,
            motivo="Cliente desistiu da compra"
        )
        self.assertEqual(venda_cancelada.status, 'CANCELADA')
        self.assertEqual(venda_cancelada.cancelado_por, self.operador_a1)

    def test_operador_bloqueado_ao_tentar_cancelar_venda_de_outro_operador(self):
        """Operador A2 tenta cancelar venda realizada pelo Operador A1 -> PermissionError."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a1,
            sessao_caixa=self.sessao_a,
            itens_data=[{'produto_id': self.prod_vinho_a.id, 'quantidade': 1, 'preco_venda': '35.00'}],
            pagamentos_data=[{'forma': 'CARTAO_DEBITO', 'valor': '35.00', 'troco': '0.00'}]
        )

        with self.assertRaises(PermissionError):
            SaleService.cancelar_venda(
                venda_id=venda.id,
                empresa=self.empresa_a,
                usuario=self.operador_a2,  # Operador diferente!
                motivo="Tentativa não autorizada"
            )

        # Venda permanece CONCLUIDA
        venda.refresh_from_db()
        self.assertEqual(venda.status, 'CONCLUIDA')

    def test_admin_cancela_venda_de_qualquer_operador_na_propria_empresa(self):
        """Administrador pode cancelar vendas de qualquer operador dentro da sua empresa."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a1,
            sessao_caixa=self.sessao_a,
            itens_data=[{'produto_id': self.prod_vinho_a.id, 'quantidade': 2, 'preco_venda': '35.00'}],
            pagamentos_data=[{'forma': 'CARTAO_CREDITO', 'valor': '70.00', 'troco': '0.00'}]
        )

        venda_cancelada = SaleService.cancelar_venda(
            venda_id=venda.id,
            empresa=self.empresa_a,
            usuario=self.admin_a,
            motivo="Cancelamento administrativo"
        )
        self.assertEqual(venda_cancelada.status, 'CANCELADA')
        self.assertEqual(venda_cancelada.cancelado_por, self.admin_a)

    def test_cancelamento_reverte_estoque_caixa_e_gera_estorno(self):
        """Cancelamento de venda reverte estoque (Movimentacao tipo ESTORNO) e gera saída de estorno no FluxoCaixa."""
        estoque_inicial = self.prod_vinho_a.estoque_atual

        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a1,
            sessao_caixa=self.sessao_a,
            itens_data=[{'produto_id': self.prod_vinho_a.id, 'quantidade': 5, 'preco_venda': '35.00'}],
            pagamentos_data=[{'forma': 'PIX', 'valor': '175.00', 'troco': '0.00'}]
        )

        self.prod_vinho_a.refresh_from_db()
        self.assertEqual(self.prod_vinho_a.estoque_atual, estoque_inicial - Decimal('5.000'))

        SaleService.cancelar_venda(
            venda_id=venda.id,
            empresa=self.empresa_a,
            usuario=self.admin_a,
            motivo="Estorno completo"
        )

        # 1. Estoque 100% restaurado
        self.prod_vinho_a.refresh_from_db()
        self.assertEqual(self.prod_vinho_a.estoque_atual, estoque_inicial)

        # 2. Movimentação de estoque do tipo ESTORNO gerada
        mov = MovimentacaoEstoque.objects.filter(produto=self.prod_vinho_a, tipo='ESTORNO').latest('data_hora')
        self.assertEqual(mov.quantidade, Decimal('5.000'))
        self.assertEqual(mov.estoque_posterior, estoque_inicial)

        # 3. Fluxo de caixa registrou SAÍDA de estorno
        fc_estorno = FluxoCaixa.objects.filter(referencia_origem=f"CANC-{venda.codigo_venda}").first()
        self.assertIsNotNone(fc_estorno)
        self.assertEqual(fc_estorno.tipo, 'SAIDA')
        self.assertEqual(fc_estorno.valor, Decimal('175.00'))

    def test_cancelamento_venda_com_pagamentos_multiplos(self):
        """Cancelamento de venda com múltiplos pagamentos (Dinheiro + PIX) reverte ambos corretamente."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a1,
            sessao_caixa=self.sessao_a,
            itens_data=[{'produto_id': self.prod_vinho_a.id, 'quantidade': 4, 'preco_venda': '35.00'}],
            pagamentos_data=[
                {'forma': 'DINHEIRO', 'valor': '40.00', 'troco': '0.00'},
                {'forma': 'PIX', 'valor': '100.00', 'troco': '0.00'}
            ]
        )

        SaleService.cancelar_venda(
            venda_id=venda.id,
            empresa=self.empresa_a,
            usuario=self.admin_a,
            motivo="Estorno múltiplos pagamentos"
        )

        estornos = FluxoCaixa.objects.filter(referencia_origem=f"CANC-{venda.codigo_venda}")
        self.assertEqual(estornos.count(), 2)
        valores_estornados = sorted([e.valor for e in estornos])
        self.assertEqual(valores_estornados, [Decimal('40.00'), Decimal('100.00')])

    def test_cancelamento_venda_crediario_reverte_saldo_devedor(self):
        """Venda no Crediário/Fiado ao ser cancelada reverte saldo devedor do cliente e cancela ContaReceber."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a1,
            sessao_caixa=self.sessao_a,
            cliente=self.cliente_a,
            itens_data=[{'produto_id': self.prod_vinho_a.id, 'quantidade': 2, 'preco_venda': '35.00'}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': '70.00', 'troco': '0.00'}]
        )

        self.cliente_a.refresh_from_db()
        self.assertEqual(self.cliente_a.saldo_devedor, Decimal('70.00'))

        conta = ContaReceber.objects.get(venda=venda, empresa=self.empresa_a)
        self.assertEqual(conta.status, 'ABERTA')

        # Cancela venda
        SaleService.cancelar_venda(
            venda_id=venda.id,
            empresa=self.empresa_a,
            usuario=self.admin_a,
            motivo="Cliente devolveu mercadoria fiada"
        )

        # Saldo devedor do cliente é zerado
        self.cliente_a.refresh_from_db()
        self.assertEqual(self.cliente_a.saldo_devedor, Decimal('0.00'))

        # Conta a receber fica com status CANCELADA
        conta.refresh_from_db()
        self.assertEqual(conta.status, 'CANCELADA')

    def test_bloqueio_duplo_cancelamento(self):
        """Tentar cancelar duas vezes a mesma venda deve levantar erro."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a1,
            sessao_caixa=self.sessao_a,
            itens_data=[{'produto_id': self.prod_vinho_a.id, 'quantidade': 1, 'preco_venda': '35.00'}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': '35.00', 'troco': '0.00'}]
        )

        SaleService.cancelar_venda(venda.id, self.empresa_a, self.admin_a, "Primeiro cancelamento")

        with self.assertRaises(ValueError):
            SaleService.cancelar_venda(venda.id, self.empresa_a, self.admin_a, "Segundo cancelamento")

    # =========================================================================
    # 3. TESTES DE EMPRESA SEM RAZÃO SOCIAL E NOVO CADASTRO DE EMPRESA
    # =========================================================================
    def test_empresa_sem_razao_social_funciona_normalmente(self):
        """Empresa criada sem razão social não causa erros no dashboard ou autenticação."""
        user_sem_razao = Usuario.objects.create_user(
            username='user_sem_razao',
            password='password123',
            empresa=self.empresa_sem_razao,
            cargo='ADMIN'
        )
        self.client.force_login(user_sem_razao)

        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)

        # __str__ seguro
        self.assertIn("Adega Sem Razão", str(self.empresa_sem_razao))
        self.assertIn("user_sem_razao", str(user_sem_razao))

    def test_novo_cadastro_empresa_inicia_totalmente_isolada_sem_dados(self):
        """Fluxo de cadastro de nova empresa cria empresa e admin inicial, sem dados das outras empresas."""
        post_data = {
            'nome_fantasia': 'Adega Nova Estrela',
            'razao_social': '',
            'cnpj': '44.444.444/0001-44',
            'nome_admin': 'Carlos Proprietário',
            'username': 'admin_nova_estrela',
            'email': 'carlos@novaestrela.com',
            'password': 'password123',
            'confirmar_senha': 'password123'
        }
        response = self.client.post(reverse('cadastro_empresa'), post_data)
        self.assertRedirects(response, reverse('dashboard'))

        nova_empresa = Empresa.objects.get(cnpj='44.444.444/0001-44')
        admin_novo = Usuario.objects.get(username='admin_nova_estrela')

        self.assertEqual(admin_novo.empresa, nova_empresa)
        self.assertEqual(admin_novo.cargo, 'ADMIN')

        # Garante que a nova empresa NÃO tem produtos, clientes ou vendas das outras
        self.assertEqual(Produto.objects.filter(empresa=nova_empresa).count(), 0)
        self.assertEqual(Cliente.objects.filter(empresa=nova_empresa).count(), 0)
        self.assertEqual(Venda.objects.filter(empresa=nova_empresa).count(), 0)
        self.assertEqual(Caixa.objects.filter(empresa=nova_empresa).count(), 0)
