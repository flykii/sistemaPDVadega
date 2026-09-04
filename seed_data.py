import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pdv_core.settings')
django.setup()

from decimal import Decimal
from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.caixas.models import Caixa, SessaoCaixa
from apps.produtos.models import Categoria, Produto
from apps.clientes.models import Cliente, Fornecedor
from apps.core.pricing import calculate_sale_price

def populate():
    print("Iniciando povoamento do banco de dados do PDV...")

    # 1. Empresa
    empresa, created = Empresa.objects.get_or_create(
        cnpj="12.345.678/0001-99",
        defaults={
            'razao_social': "Adega & Comercial PDV LTDA",
            'nome_fantasia': "Adega & Conveniência Express",
            'telefone': "(11) 98765-4321",
            'email': "contato@adegapdv.com.br",
            'endereco': "Av. Principal, 1000 - Centro"
        }
    )
    print(f"Empresa criada/encontrada: {empresa.nome_fantasia}")

    # 2. Usuário Administrador (admin / admin123)
    user = Usuario.objects.filter(username='admin').first()
    if not user:
        user = Usuario.objects.create_superuser(
            username='admin',
            email='admin@adegapdv.com.br',
            password='admin123',
            first_name='Gerente',
            last_name='Principal',
            empresa=empresa,
            cargo='ADMIN',
            pin_caixa='1234'
        )
        print("Usuário Admin criado: admin / admin123")
    else:
        user.empresa = empresa
        user.save()

    # 3. Caixa Principal
    caixa, _ = Caixa.objects.get_or_create(
        empresa=empresa,
        codigo_identificador="CX-01",
        defaults={'nome': "Caixa Principal 01", 'status': 'FECHADO'}
    )
    print(f"Caixa criado: {caixa.nome}")

    # 4. Categorias
    cat_bebidas, _ = Categoria.objects.get_or_create(empresa=empresa, nome="Bebidas")
    cat_mercearia, _ = Categoria.objects.get_or_create(empresa=empresa, nome="Mercearia")
    cat_snacks, _ = Categoria.objects.get_or_create(empresa=empresa, nome="Snacks & Petiscos")

    # 5. Produtos (Demonstrando a regra de precificação do usuário: 2.00 / 0.7 = 2.85)
    p1, _ = Produto.objects.get_or_create(
        empresa=empresa,
        codigo_barras="7891234567890",
        defaults={
            'nome': "Cerveja Pilsen Lata 350ml",
            'sku': "CERV-350",
            'categoria': cat_bebidas,
            'preco_custo': Decimal('2.00'),
            'margem_lucro': Decimal('30.00'),
            'preco_venda': Decimal('2.85'),
            'estoque_atual': Decimal('100.000'),
            'estoque_minimo': Decimal('10.000'),
            'unidade_medida': 'UN'
        }
    )

    p2, _ = Produto.objects.get_or_create(
        empresa=empresa,
        codigo_barras="7899876543210",
        defaults={
            'nome': "Refrigerante Cola 2 Litros",
            'sku': "REF-2L",
            'categoria': cat_bebidas,
            'preco_custo': Decimal('5.00'),
            'margem_lucro': Decimal('30.00'),
            'preco_venda': Decimal('7.14'),
            'estoque_atual': Decimal('50.000'),
            'estoque_minimo': Decimal('5.000'),
            'unidade_medida': 'UN'
        }
    )

    p3, _ = Produto.objects.get_or_create(
        empresa=empresa,
        codigo_barras="7891111222233",
        defaults={
            'nome': "Água Mineral Sem Gás 500ml",
            'sku': "AGUA-500",
            'categoria': cat_bebidas,
            'preco_custo': Decimal('1.00'),
            'margem_lucro': Decimal('50.00'),
            'preco_venda': Decimal('2.00'),
            'estoque_atual': Decimal('200.000'),
            'estoque_minimo': Decimal('20.000'),
            'unidade_medida': 'UN'
        }
    )

    p4, _ = Produto.objects.get_or_create(
        empresa=empresa,
        codigo_barras="7894444555566",
        defaults={
            'nome': "Batata Palha 120g",
            'sku': "BAT-120",
            'categoria': cat_snacks,
            'preco_custo': Decimal('3.50'),
            'margem_lucro': Decimal('35.00'),
            'preco_venda': Decimal('5.38'),
            'estoque_atual': Decimal('3.000'), # Alerta estoque baixo!
            'estoque_minimo': Decimal('10.000'),
            'unidade_medida': 'UN'
        }
    )

    print(f"Produtos criados com sucesso! Exemplo p1: Custo R$ {p1.preco_custo} | Margem {p1.margem_lucro}% -> Venda R$ {p1.preco_venda} | Lucro Real R$ {p1.lucro_real}")

    # 6. Cliente & Fornecedor
    cliente, _ = Cliente.objects.get_or_create(
        empresa=empresa,
        nome="João da Silva (Cliente Frequente)",
        defaults={
            'cpf_cnpj': "111.222.333-44",
            'telefone': "(11) 97777-8888",
            'email': "joao@email.com",
            'limite_credito': Decimal('500.00'),
            'saldo_devedor': Decimal('0.00')
        }
    )

    fornecedor, _ = Fornecedor.objects.get_or_create(
        empresa=empresa,
        razao_social="Distribuidora de Bebidas Brasil S/A",
        defaults={
            'nome_fantasia': "Distribuidora Bebidas Brasil",
            'cnpj': "99.888.777/0001-11",
            'telefone': "(11) 3333-4444",
            'email': "pedidos@bebidasbrasil.com"
        }
    )

    print("Banco de dados do PDV povoado com dados iniciais com sucesso!")

if __name__ == '__main__':
    populate()
