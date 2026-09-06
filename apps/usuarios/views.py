from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from apps.empresas.models import Empresa
from apps.core.models import AuditService
from .models import Usuario
from .permissions import cargo_required


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            if not user.is_active:
                messages.error(request, "Este usuário está inativo. Entre em contato com o administrador.")
                return render(request, 'usuarios/login.html')

            if not user.empresa:
                # Se superuser sem empresa, vincula à primeira empresa ou cria padrão
                empresa = Empresa.objects.first()
                if not empresa:
                    empresa = Empresa.objects.create(
                        razao_social="Empresa Demonstração LTDA",
                        nome_fantasia="Minha Loja PDV",
                        cnpj="00.000.000/0001-00"
                    )
                user.empresa = empresa
                user.save()

            login(request, user)
            messages.success(request, f"Bem-vindo ao PDV, {user.get_full_name() or user.username}!")
            return redirect('dashboard')
        else:
            messages.error(request, "Usuário ou senha inválidos.")

    return render(request, 'usuarios/login.html')


def logout_view(request):
    logout(request)
    messages.info(request, "Sessão encerrada com sucesso.")
    return redirect('login')


def cadastro_empresa_view(request):
    """
    Fluxo de criação de nova empresa com seu primeiro usuário administrador.
    A nova empresa inicia totalmente isolada, sem dados compartilhados com outras empresas.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        nome_fantasia = request.POST.get('nome_fantasia', '').strip()
        razao_social = request.POST.get('razao_social', '').strip()
        cnpj = request.POST.get('cnpj', '').strip()
        nome_admin = request.POST.get('nome_admin', '').strip()
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirmar_senha = request.POST.get('confirmar_senha', '')

        if not nome_fantasia:
            messages.error(request, "O Nome Fantasia da empresa é obrigatório.")
            return render(request, 'usuarios/cadastro_empresa.html')

        if not cnpj:
            messages.error(request, "O CNPJ é obrigatório.")
            return render(request, 'usuarios/cadastro_empresa.html')

        if Empresa.objects.filter(cnpj=cnpj).exists():
            messages.error(request, f"Já existe uma empresa cadastrada com o CNPJ '{cnpj}'.")
            return render(request, 'usuarios/cadastro_empresa.html')

        if not username or not password:
            messages.error(request, "Login e Senha do Administrador são obrigatórios.")
            return render(request, 'usuarios/cadastro_empresa.html')

        if Usuario.objects.filter(username=username).exists():
            messages.error(request, f"O nome de usuário '{username}' já está em uso.")
            return render(request, 'usuarios/cadastro_empresa.html')

        if len(password) < 6:
            messages.error(request, "A senha deve ter no mínimo 6 caracteres.")
            return render(request, 'usuarios/cadastro_empresa.html')

        if password != confirmar_senha:
            messages.error(request, "As senhas digitadas não coincidem.")
            return render(request, 'usuarios/cadastro_empresa.html')

        try:
            with transaction.atomic():
                # 1. Cria a Empresa isolada
                empresa = Empresa.objects.create(
                    nome_fantasia=nome_fantasia,
                    razao_social=razao_social,
                    cnpj=cnpj,
                    email=email
                )

                # 2. Cria o Usuário Administrador vinculado à Empresa
                user = Usuario(
                    username=username,
                    email=email,
                    first_name=nome_admin,
                    empresa=empresa,
                    cargo='ADMIN',
                    is_active=True
                )
                user.set_password(password)
                user.save()

                # 3. Trilha de Auditoria
                AuditService.registrar(
                    empresa=empresa,
                    usuario=user,
                    acao='USUARIO_ALTERADO',
                    entidade='Empresa',
                    entidade_id=empresa.id,
                    descricao=f"Nova empresa '{empresa.nome_fantasia}' cadastrada com administrador '{user.username}'."
                )

            # Efetua login automático
            login(request, user)
            messages.success(request, f"Empresa '{empresa.nome_fantasia}' cadastrada com sucesso! Bem-vindo ao sistema!")
            return redirect('dashboard')
        except Exception as e:
            messages.error(request, f"Erro ao criar empresa: {str(e)}")

    return render(request, 'usuarios/cadastro_empresa.html')


# =========================================================================
# GESTÃO DE USUÁRIOS (ADMINISTRADOR) COM ISOLAMENTO ESTRITO POR TENANT
# =========================================================================

@login_required
@cargo_required('ADMIN')
def usuarios_list_view(request):
    """
    Listagem de usuários pertencentes EXCLUSIVAMENTE à empresa do administrador logado.
    """
    empresa = request.tenant or request.user.empresa
    usuarios = Usuario.objects.filter(empresa=empresa).order_by('-is_active', 'first_name', 'username')

    return render(request, 'usuarios/list.html', {
        'usuarios': usuarios,
        'empresa': empresa,
    })


@login_required
@cargo_required('ADMIN')
def usuario_create_view(request):
    """
    Criação de novos usuários vinculados AUTOMATICAMENTE à empresa do administrador.
    O backend ignora qualquer tentativa de manipulação de empresa_id.
    """
    empresa = request.tenant or request.user.empresa
    cargos = Usuario.CARGO_CHOICES

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        cargo = request.POST.get('cargo', 'OPERADOR')
        password = request.POST.get('password', '')
        confirmar_senha = request.POST.get('confirmar_senha', '')
        pin_caixa = request.POST.get('pin_caixa', '').strip()
        telefone = request.POST.get('telefone', '').strip()
        limite_desconto_raw = request.POST.get('limite_desconto_pct', '0.00').strip().replace(',', '.')
        is_active = request.POST.get('is_active') in ['on', 'true', '1']

        try:
            limite_desconto_pct = Decimal(limite_desconto_raw) if limite_desconto_raw else Decimal('0.00')
        except Exception:
            limite_desconto_pct = Decimal('0.00')

        if not username:
            messages.error(request, "O nome de usuário (login) é obrigatório.")
            return render(request, 'usuarios/form.html', {'cargos': cargos})

        if Usuario.objects.filter(username=username).exists():
            messages.error(request, f"O nome de usuário '{username}' já está em uso no sistema.")
            return render(request, 'usuarios/form.html', {'cargos': cargos})

        if not password:
            messages.error(request, "A senha é obrigatória.")
            return render(request, 'usuarios/form.html', {'cargos': cargos})

        if len(password) < 6:
            messages.error(request, "A senha deve conter no mínimo 6 caracteres.")
            return render(request, 'usuarios/form.html', {'cargos': cargos})

        if password != confirmar_senha:
            messages.error(request, "As senhas digitadas não coincidem.")
            return render(request, 'usuarios/form.html', {'cargos': cargos})

        cargos_validos = [c[0] for c in cargos]
        if cargo not in cargos_validos:
            cargo = 'OPERADOR'

        try:
            with transaction.atomic():
                novo_user = Usuario(
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    cargo=cargo,
                    pin_caixa=pin_caixa,
                    telefone=telefone,
                    limite_desconto_pct=limite_desconto_pct,
                    is_active=is_active,
                    # VÍNCULO AUTOMÁTICO ESTRITO:
                    empresa=empresa
                )
                novo_user.set_password(password)
                novo_user.save()

                AuditService.registrar(
                    empresa=empresa,
                    usuario=request.user,
                    acao='USUARIO_ALTERADO',
                    entidade='Usuario',
                    entidade_id=novo_user.id,
                    descricao=f"Usuário '{novo_user.username}' ({novo_user.get_cargo_display()}) cadastrado por '{request.user.username}'."
                )

            messages.success(request, f"Usuário '{novo_user.username}' cadastrado com sucesso na empresa '{empresa.nome_fantasia}'!")
            return redirect('usuarios_list')
        except Exception as e:
            messages.error(request, f"Erro ao cadastrar usuário: {str(e)}")

    return render(request, 'usuarios/form.html', {
        'cargos': cargos,
        'usuario_obj': None,
    })


@login_required
@cargo_required('ADMIN')
def usuario_edit_view(request, pk):
    """
    Edição de usuário existente com isolamento de tenant.
    Não permite alterar a empresa do usuário nem transferir para outra empresa.
    """
    empresa = request.tenant or request.user.empresa
    usuario_obj = get_object_or_404(Usuario, pk=pk, empresa=empresa)
    cargos = Usuario.CARGO_CHOICES

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        cargo = request.POST.get('cargo', usuario_obj.cargo)
        pin_caixa = request.POST.get('pin_caixa', '').strip()
        telefone = request.POST.get('telefone', '').strip()
        limite_desconto_raw = request.POST.get('limite_desconto_pct', '0.00').strip().replace(',', '.')
        is_active = request.POST.get('is_active') in ['on', 'true', '1']

        try:
            limite_desconto_pct = Decimal(limite_desconto_raw) if limite_desconto_raw else Decimal('0.00')
        except Exception:
            limite_desconto_pct = Decimal('0.00')

        # Regra de proteção: Não permitir auto-desativação do próprio administrador logado
        if usuario_obj.id == request.user.id and not is_active:
            messages.error(request, "Você não pode desativar seu próprio usuário logado.")
            is_active = True

        cargos_validos = [c[0] for c in cargos]
        if cargo in cargos_validos:
            # Não permitir que o único admin da empresa se rebaixe
            if usuario_obj.id == request.user.id and cargo != 'ADMIN':
                total_admins = Usuario.objects.filter(empresa=empresa, cargo='ADMIN', is_active=True).exclude(id=usuario_obj.id).count()
                if total_admins == 0:
                    messages.error(request, "Você não pode alterar seu cargo pois é o único Administrador ativo da empresa.")
                    cargo = 'ADMIN'
            usuario_obj.cargo = cargo

        usuario_obj.first_name = first_name
        usuario_obj.last_name = last_name
        usuario_obj.email = email
        usuario_obj.pin_caixa = pin_caixa
        usuario_obj.telefone = telefone
        usuario_obj.limite_desconto_pct = limite_desconto_pct
        usuario_obj.is_active = is_active
        # Garante que a empresa permanece inalterada
        usuario_obj.empresa = empresa

        try:
            usuario_obj.save()
            AuditService.registrar(
                empresa=empresa,
                usuario=request.user,
                acao='USUARIO_ALTERADO',
                entidade='Usuario',
                entidade_id=usuario_obj.id,
                descricao=f"Usuário '{usuario_obj.username}' atualizado por '{request.user.username}'."
            )
            messages.success(request, f"Usuário '{usuario_obj.username}' atualizado com sucesso!")
            return redirect('usuarios_list')
        except Exception as e:
            messages.error(request, f"Erro ao atualizar usuário: {str(e)}")

    return render(request, 'usuarios/form.html', {
        'usuario_obj': usuario_obj,
        'cargos': cargos,
    })


@login_required
@cargo_required('ADMIN')
def usuario_toggle_ativo_view(request, pk):
    """
    Ativa ou inativa um usuário da empresa com segurança.
    """
    empresa = request.tenant or request.user.empresa
    usuario_obj = get_object_or_404(Usuario, pk=pk, empresa=empresa)

    if usuario_obj.id == request.user.id:
        messages.error(request, "Você não pode desativar seu próprio usuário.")
        return redirect('usuarios_list')

    usuario_obj.is_active = not usuario_obj.is_active
    usuario_obj.save()

    status_str = "ativado" if usuario_obj.is_active else "inativado"
    AuditService.registrar(
        empresa=empresa,
        usuario=request.user,
        acao='USUARIO_ALTERADO',
        entidade='Usuario',
        entidade_id=usuario_obj.id,
        descricao=f"Usuário '{usuario_obj.username}' foi {status_str} por '{request.user.username}'."
    )

    messages.success(request, f"Usuário '{usuario_obj.username}' {status_str} com sucesso!")
    return redirect('usuarios_list')


@login_required
@cargo_required('ADMIN')
def usuario_redefinir_senha_view(request, pk):
    """
    Redefinição de senha de um usuário da própria empresa por um Administrador.
    """
    empresa = request.tenant or request.user.empresa
    usuario_obj = get_object_or_404(Usuario, pk=pk, empresa=empresa)

    if request.method == 'POST':
        nova_senha = request.POST.get('nova_senha', '')
        confirmar_senha = request.POST.get('confirmar_senha', '')

        if not nova_senha or len(nova_senha) < 6:
            messages.error(request, "A nova senha deve ter no mínimo 6 caracteres.")
            return render(request, 'usuarios/redefinir_senha.html', {'usuario_obj': usuario_obj})

        if nova_senha != confirmar_senha:
            messages.error(request, "As senhas digitadas não coincidem.")
            return render(request, 'usuarios/redefinir_senha.html', {'usuario_obj': usuario_obj})

        usuario_obj.set_password(nova_senha)
        usuario_obj.save()

        AuditService.registrar(
            empresa=empresa,
            usuario=request.user,
            acao='USUARIO_ALTERADO',
            entidade='Usuario',
            entidade_id=usuario_obj.id,
            descricao=f"Senha do usuário '{usuario_obj.username}' foi redefinida por '{request.user.username}'."
        )

        messages.success(request, f"Senha do usuário '{usuario_obj.username}' redefinida com sucesso!")
        return redirect('usuarios_list')

    return render(request, 'usuarios/redefinir_senha.html', {
        'usuario_obj': usuario_obj
    })
