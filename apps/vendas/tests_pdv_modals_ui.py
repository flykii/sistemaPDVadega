import os
from decimal import Decimal
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.produtos.models import Produto, Categoria

class PDVModalsUITests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        
        try:
            cls.selenium = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            cls.selenium.implicitly_wait(2)
        except Exception as e:
            print("Could not start Selenium:", e)
            cls.selenium = None

    @classmethod
    def tearDownClass(cls):
        if cls.selenium:
            cls.selenium.quit()
        super().tearDownClass()

    def setUp(self):
        if not self.selenium:
            self.skipTest("Selenium not available")
        
        # Criar dados basicos
        self.empresa = Empresa.objects.create(nome="Empresa Teste", cnpj="12345678901234")
        self.user = Usuario.objects.create_user(username="testuser", password="password123", empresa=self.empresa)
        self.categoria = Categoria.objects.create(nome="Geral", empresa=self.empresa)
        self.produto1 = Produto.objects.create(
            nome="Produto Teste", 
            preco_venda=Decimal('3.00'), 
            codigo_barras="12345", 
            categoria=self.categoria,
            empresa=self.empresa
        )
        self.produto2 = Produto.objects.create(
            nome="Produto Decimal", 
            preco_venda=Decimal('0.08'), 
            codigo_barras="54321", 
            categoria=self.categoria,
            empresa=self.empresa
        )

    def login(self):
        self.selenium.get(f"{self.live_server_url}/login/")
        self.selenium.find_element(By.NAME, "username").send_keys("testuser")
        self.selenium.find_element(By.NAME, "password").send_keys("password123")
        self.selenium.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(self.selenium, 5).until(lambda driver: "Dashboard" in driver.title or "Caixa" in driver.page_source)

    def test_modal_pagamento_parcial_nao_deve_apagar_pagamentos(self):
        # 1. Login
        self.login()
        # Ensure caixa is open
        self.selenium.get(f"{self.live_server_url}/caixas/abrir/")
        try:
            saldo_input = self.selenium.find_element(By.NAME, "saldo_inicial")
            saldo_input.clear()
            saldo_input.send_keys("0")
            self.selenium.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        except:
            pass # might be already open
            
        # 2. Go to PDV
        self.selenium.get(f"{self.live_server_url}/vendas/pdv/")
        
        # Wait for PDV to load
        wait = WebDriverWait(self.selenium, 5)
        
        # Simulate adding product
        # For simplicity, we just inject directly into JS object or type barcode
        barcode_input = wait.until(EC.presence_of_element_located((By.ID, "barcode-scanner")))
        barcode_input.send_keys("12345")
        
        # trigger enter
        barcode_input.send_keys("\n")
        
        # Wait for cart
        wait.until(EC.text_to_be_present_in_element((By.ID, "summary-total"), "3,00"))
        
        # Open payment F4 (id btn-finalizar-venda)
        self.selenium.find_element(By.ID, "btn-finalizar-venda").click()
        
        # Wait for payment modal
        wait.until(EC.visibility_of_element_located((By.ID, "paymentModal")))
        
        # Enter partial payment: R$ 2.00
        pay_valor = self.selenium.find_element(By.ID, "modal-pay-valor")
        pay_valor.clear()
        pay_valor.send_keys("2.00")
        
        # Add payment
        self.selenium.find_element(By.ID, "modal-btn-add-payment").click()
        
        # Now click Finalizar
        self.selenium.find_element(By.ID, "modal-btn-finalizar").click()
        
        # Should transition to confirmSaleModal
        wait.until(EC.visibility_of_element_located((By.ID, "confirmSaleModal")))
        
        # Verify the error box is shown in confirmSaleModal
        error_box = self.selenium.find_element(By.ID, "confirm-modal-error-box")
        self.assertNotIn("d-none", error_box.get_attribute("class"))
        
        error_text = self.selenium.find_element(By.ID, "confirm-modal-error-text").text
        self.assertIn("Ainda resta um saldo de R$ 1,00", error_text)
        
        # The confirm button should be disabled
        confirm_btn = self.selenium.find_element(By.ID, "btn-efetivar-confirmacao")
        self.assertEqual(confirm_btn.get_attribute("disabled"), "true")
        
        # Cancel confirm modal
        self.selenium.find_element(By.CSS_SELECTOR, "#confirmSaleModal .btn-outline-secondary").click()
        
        # Wait for payment modal to be back
        wait.until(EC.visibility_of_element_located((By.ID, "paymentModal")))
        
        # Check that payments are preserved! Total paid should be 2.00
        total_pago = self.selenium.find_element(By.ID, "modal-display-pago").text
        self.assertIn("2,00", total_pago)
        
        # Add the remaining 1.00
        pay_valor = wait.until(EC.element_to_be_clickable((By.ID, "modal-pay-valor")))
        pay_valor.clear()
        pay_valor.send_keys("1.00")
        self.selenium.find_element(By.ID, "modal-btn-add-payment").click()
        
        # Now click Finalizar again
        self.selenium.find_element(By.ID, "modal-btn-finalizar").click()
        
        # Wait for confirm modal
        wait.until(EC.visibility_of_element_located((By.ID, "confirmSaleModal")))
        
        # Error box should be hidden now
        error_box = self.selenium.find_element(By.ID, "confirm-modal-error-box")
        self.assertIn("d-none", error_box.get_attribute("class"))
        
        # Button enabled
        confirm_btn = self.selenium.find_element(By.ID, "btn-efetivar-confirmacao")
        self.assertIsNone(confirm_btn.get_attribute("disabled"))
        
        # Efetivar venda
        confirm_btn.click()
        
        # Assert success (maybe redirect to receipt or clean cart)
        wait.until(lambda d: "R$ 0,00" in d.find_element(By.ID, "summary-total").text)
