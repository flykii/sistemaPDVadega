from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from apps.empresas.models import Empresa
from .models import Usuario

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            if not user.empresa:
                # Se superuser sem empresa, vincula à primeira empresa
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
