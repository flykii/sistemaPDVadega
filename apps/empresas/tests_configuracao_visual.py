from django.test import TestCase, Client
from django.urls import reverse
from django.core.exceptions import ValidationError

from apps.empresas.models import Empresa, ConfiguracaoVisual
from apps.usuarios.models import Usuario


class ConfiguracaoVisualTestCase(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(
            razao_social="Adega Visual Alpha LTDA",
            nome_fantasia="Adega Alpha",
            cnpj="11223344000199"
        )
        self.empresa_b = Empresa.objects.create(
            razao_social="Adega Visual Beta LTDA",
            nome_fantasia="Adega Beta",
            cnpj="55667788000188"
        )

        self.admin_a = Usuario.objects.create_user(
            username="admin_alpha",
            email="admin_alpha@teste.com",
            password="password123",
            empresa=self.empresa_a,
            cargo='ADMIN'
        )
        self.admin_b = Usuario.objects.create_user(
            username="admin_beta",
            email="admin_beta@teste.com",
            password="password123",
            empresa=self.empresa_b,
            cargo='ADMIN'
        )

        self.client_a = Client()
        self.client_a.force_login(self.admin_a)

        self.client_b = Client()
        self.client_b.force_login(self.admin_b)

    def test_salvar_cores_sistema_persistencia_e_context_processor(self):
        """1. Salvar cores do Sistema via POST: persiste no banco e reflete nas css_variables."""
        dados = {
            'action': 'salvar_tema_cores',
            'aba_origem': 'visual',
            'cor_principal': '#FF5733',
            'cor_secundaria': '#33FF57',
            'cor_destaque': '#3357FF',
            'cor_menu_sidebar': '#111111',
            'cor_fundo': '#F0F0F0',
            'cor_cards': '#FAFAFA',
            'cor_texto': '#222222',
            'cor_texto_secundario': '#555555',
            'cor_botoes': '#FF5733',
            'cor_botoes_acao': '#00AA00',
            'cor_links': '#0000FF',
            'cor_sucesso': '#00FF00',
            'cor_alerta': '#FFAA00',
            'cor_erro': '#FF0000',
        }
        resp = self.client_a.post(reverse('configuracoes'), data=dados, follow=True)
        self.assertEqual(resp.status_code, 200)

        config = ConfiguracaoVisual.objects.get(empresa=self.empresa_a)
        self.assertEqual(config.cor_principal, '#FF5733')
        self.assertEqual(config.cor_menu_sidebar, '#111111')
        self.assertEqual(config.cor_fundo, '#F0F0F0')
        self.assertEqual(config.cor_cards, '#FAFAFA')

        # Verificar css_variables injetadas na resposta
        css_vars = config.to_css_variables()
        self.assertIn('--cor-principal: #FF5733;', css_vars)
        self.assertIn('--cor-menu-sidebar: #111111;', css_vars)
        self.assertContains(resp, '--cor-principal: #FF5733;')

    def test_recarregar_pagina_mantem_valores_selecionados(self):
        """2. Recarregar a página de configurações mantém os valores customizados."""
        config = self.empresa_a.get_configuracao_visual()
        config.cor_principal = '#8A2BE2'
        config.cor_menu_sidebar = '#2F4F4F'
        config.save()

        resp = self.client_a.get(reverse('configuracoes'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'value="#8A2BE2"')
        self.assertContains(resp, 'value="#2F4F4F"')

    def test_salvar_cores_pdv_nao_reseta_cores_sistema(self):
        """3. Salvar configurações do PDV não afeta nem reseta as cores do sistema."""
        # Configura cores personalizadas do sistema primeiro
        config = self.empresa_a.get_configuracao_visual()
        config.cor_principal = '#123456'
        config.cor_cards = '#654321'
        config.save()

        dados_pdv = {
            'action': 'salvar_tema_cores',
            'aba_origem': 'pdv',
            'cor_pdv_fundo': '#1A1A2E',
            'cor_pdv_texto': '#EAEAEA',
            'cor_pdv_preco': '#E94560',
            'cor_pdv_total': '#0F3460',
            'cor_pdv_botao_finalizar': '#16C79A',
            'cor_pdv_botao_cancelar': '#E02401',
            'cor_pdv_botoes_pagamento': '#1B1A17',
            'cor_pdv_botao_pausar': '#F0A500',
            'cor_pdv_botao_espera': '#334756',
            'cor_pdv_botao_divida': '#6A1B9A',
            'tamanho_fonte_preco': '1.5rem',
            'tamanho_fonte_total': '2.5rem',
            'tamanho_fonte_itens': '1.15rem',
            'modo_layout': 'COMPACTO',
            'exibir_painel_produtos_rapidos': 'on'
        }
        resp = self.client_a.post(reverse('configuracoes'), data=dados_pdv, follow=True)
        self.assertEqual(resp.status_code, 200)

        config.refresh_from_db()
        # Cores do PDV atualizadas
        self.assertEqual(config.cor_pdv_fundo, '#1A1A2E')
        self.assertEqual(config.cor_pdv_preco, '#E94560')
        self.assertEqual(config.tamanho_fonte_total, '2.5rem')
        self.assertEqual(config.modo_layout, 'COMPACTO')
        self.assertTrue(config.exibir_painel_produtos_rapidos)

        # Cores do Sistema PRESERVADAS
        self.assertEqual(config.cor_principal, '#123456')
        self.assertEqual(config.cor_cards, '#654321')

    def test_salvar_sistema_nao_reseta_configuracoes_pdv(self):
        """4. Salvar configurações do Sistema não afeta nem reseta as configurações do PDV."""
        # Configurações personalizadas do PDV primeiro
        config = self.empresa_a.get_configuracao_visual()
        config.cor_pdv_fundo = '#050505'
        config.tamanho_fonte_total = '2.5rem'
        config.modo_layout = 'COMPACTO'
        config.exibir_painel_produtos_rapidos = False
        config.save()

        dados_sistema = {
            'action': 'salvar_tema_cores',
            'aba_origem': 'visual',
            'cor_principal': '#990000',
            'cor_secundaria': '#009900',
        }
        resp = self.client_a.post(reverse('configuracoes'), data=dados_sistema, follow=True)
        self.assertEqual(resp.status_code, 200)

        config.refresh_from_db()
        # Cores do Sistema atualizadas
        self.assertEqual(config.cor_principal, '#990000')
        self.assertEqual(config.cor_secundaria, '#009900')

        # Configurações do PDV PRESERVADAS
        self.assertEqual(config.cor_pdv_fundo, '#050505')
        self.assertEqual(config.tamanho_fonte_total, '2.5rem')
        self.assertEqual(config.modo_layout, 'COMPACTO')
        self.assertFalse(config.exibir_painel_produtos_rapidos)

    def test_multi_tenant_isolamento_de_cores(self):
        """5. Empresa A e Empresa B possuem personalizações visuais isoladas sem vazamento."""
        # Empresa A define cor vermelha
        self.client_a.post(reverse('configuracoes'), data={
            'action': 'salvar_tema_cores',
            'aba_origem': 'visual',
            'cor_principal': '#FF0000'
        }, follow=True)

        # Empresa B define cor verde
        self.client_b.post(reverse('configuracoes'), data={
            'action': 'salvar_tema_cores',
            'aba_origem': 'visual',
            'cor_principal': '#00FF00'
        }, follow=True)

        config_a = ConfiguracaoVisual.objects.get(empresa=self.empresa_a)
        config_b = ConfiguracaoVisual.objects.get(empresa=self.empresa_b)

        self.assertEqual(config_a.cor_principal, '#FF0000')
        self.assertEqual(config_b.cor_principal, '#00FF00')

        # Verificar renderização isolada para client A
        resp_a = self.client_a.get(reverse('dashboard'))
        self.assertContains(resp_a, '--cor-principal: #FF0000;')
        self.assertNotContains(resp_a, '--cor-principal: #00FF00;')

        # Verificar renderização isolada para client B
        resp_b = self.client_b.get(reverse('dashboard'))
        self.assertContains(resp_b, '--cor-principal: #00FF00;')
        self.assertNotContains(resp_b, '--cor-principal: #FF0000;')

    def test_restaurar_padroes(self):
        """6. Restaurar padrões redefine todas as cores para o padrão de fábrica."""
        config = self.empresa_a.get_configuracao_visual()
        config.cor_principal = '#000000'
        config.cor_pdv_fundo = '#FFFFFF'
        config.tamanho_fonte_total = '2.5rem'
        config.save()

        resp = self.client_a.post(reverse('configuracoes'), data={'action': 'restaurar_padroes'}, follow=True)
        self.assertEqual(resp.status_code, 200)

        config.refresh_from_db()
        self.assertEqual(config.cor_principal, '#2563eb')
        self.assertEqual(config.cor_pdv_fundo, '#0f172a')
        self.assertEqual(config.tamanho_fonte_total, '2.0rem')
        self.assertEqual(config.modo_layout, 'CONFORTAVEL')

    def test_validacao_hex_invalido(self):
        """7. Envio de código HEX inválido é rejeitado e não salva no banco."""
        config = self.empresa_a.get_configuracao_visual()
        cor_original = config.cor_principal

        dados_invalidos = {
            'action': 'salvar_tema_cores',
            'aba_origem': 'visual',
            'cor_principal': 'INVALIDO_HEX',
        }
        resp = self.client_a.post(reverse('configuracoes'), data=dados_invalidos, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Código de cor inválido")

        config.refresh_from_db()
        self.assertEqual(config.cor_principal, cor_original)
