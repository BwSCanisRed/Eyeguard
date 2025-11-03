from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required  
from django.http import HttpResponse

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages

def home(request):
    # Mostrar la landing page principal del proyecto en la raíz.
    # Si el usuario está autenticado y queremos redirigirle automáticamente
    # a su dashboard según rol, podemos mantener esa lógica en el login.
    return render(request, 'core/home.html')

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Usuario, Conductor, Vehiculo
from .forms import ConductorForm, VehiculoForm, EditConductorForm
from .decorators import check_session_timeout
from django.http import StreamingHttpResponse, JsonResponse
from . import drowsiness
import csv
from django.utils import timezone
from django.http import HttpResponse
from .models import CriticalEvent
from django.contrib.auth import logout as auth_logout

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        selected_role = request.POST.get('role')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            # Verificar si el rol seleccionado coincide con el rol del usuario
            if user.rol == selected_role:
                login(request, user)
                if user.rol == 'admin':
                    return redirect('admin_dashboard')
                elif user.rol == 'conductor':
                    return redirect('conductor_dashboard')
            else:
                messages.error(request, "No tienes permiso para acceder como " + 
                             dict(Usuario.ROLES).get(selected_role, selected_role))
        else:
            messages.error(request, "Usuario o contraseña incorrectos")
    
    # Pasar las opciones de roles al template
    context = {
        'roles': Usuario.ROLES
    }
    return render(request, 'core/login.html', context)

@login_required
@check_session_timeout
def admin_dashboard(request):
    conductor_seleccionado = None
    conductor_id = request.GET.get('conductor_id')
    
    if conductor_id:
        conductor_seleccionado = Conductor.objects.filter(id=conductor_id).first()
        if conductor_seleccionado:
            conductor_form = EditConductorForm(instance=conductor_seleccionado)
            vehiculo = conductor_seleccionado.vehiculos.first()
            vehiculo_form = VehiculoForm(instance=vehiculo) if vehiculo else VehiculoForm()
    
    if request.method == 'POST':
        if 'editar_conductor' in request.POST:
            conductor_form = EditConductorForm(request.POST, instance=conductor_seleccionado)
            vehiculo = conductor_seleccionado.vehiculos.first() if conductor_seleccionado else None
            vehiculo_form = VehiculoForm(request.POST, instance=vehiculo)
            
            if conductor_form.is_valid() and vehiculo_form.is_valid():
                conductor = conductor_form.save()
                vehiculo = vehiculo_form.save(commit=False)
                vehiculo.conductor_asignado = conductor
                vehiculo.save()
                messages.success(request, "Conductor y vehículo actualizados exitosamente")
                return redirect('admin_dashboard')
        else:
            conductor_form = ConductorForm(request.POST)
            vehiculo_form = VehiculoForm(request.POST)
            
            if conductor_form.is_valid() and vehiculo_form.is_valid():
                conductor = conductor_form.save()
                vehiculo = vehiculo_form.save(commit=False)
                vehiculo.conductor_asignado = conductor
                vehiculo.save()
                messages.success(request, "Conductor y vehículo registrados exitosamente")
                return redirect('admin_dashboard')
    else:
        if not conductor_seleccionado:
            conductor_form = ConductorForm()
            vehiculo_form = VehiculoForm()

    conductores = Conductor.objects.all()
    vehiculos = Vehiculo.objects.all()
    
    context = {
        'conductor_form': conductor_form,
        'vehiculo_form': vehiculo_form,
        'conductores': conductores,
        'vehiculos': vehiculos,
        'conductor_seleccionado': conductor_seleccionado,
    }
    return render(request, 'core/admin_dashboard.html', context)

@login_required
@check_session_timeout
def edit_conductor(request, conductor_id):
    conductor = get_object_or_404(Conductor, id=conductor_id)
    if request.method == 'POST':
        form = EditConductorForm(request.POST, instance=conductor)
        if form.is_valid():
            form.save()
            messages.success(request, 'Datos del conductor actualizados correctamente.')
            return redirect('admin_dashboard')
        else:
            messages.error(request, 'Por favor corrija los errores en el formulario.')
    return redirect('admin_dashboard')

@login_required
def monitor_conductores(request):
    # Usado por vista dedicada (no necesaria si usamos admin_dashboard)
    conductores = Conductor.objects.all()
    context = {
        'conductores': conductores
    }
    return render(request, 'core/monitor_conductores.html', context)


@login_required
def stream_mjpeg(request, conductor_id):
    conductor = get_object_or_404(Conductor, id=conductor_id)
    gen = drowsiness.mjpeg_generator_for(conductor)
    return StreamingHttpResponse(gen, content_type='multipart/x-mixed-replace; boundary=frame')


@login_required
def stream_score(request, conductor_id):
    conductor = get_object_or_404(Conductor, id=conductor_id)
    score = drowsiness.get_score_for(conductor)
    return JsonResponse({'score': score})


@login_required
@check_session_timeout
def delete_conductor(request, conductor_id):
    conductor = get_object_or_404(Conductor, id=conductor_id)
    # Solo permitir POST para eliminar
    if request.method == 'POST':
        username = conductor.usuario.username if conductor.usuario else None
        # eliminar primero el perfil-conductor y luego el usuario
        try:
            if conductor.usuario:
                # eliminar usuario (también eliminará conductor por cascada si está relacionado)
                conductor.usuario.delete()
            else:
                conductor.delete()
            messages.success(request, f'Conductor {username or conductor_id} eliminado correctamente.')
        except Exception as e:
            messages.error(request, f'Error al eliminar conductor: {e}')
    else:
        messages.error(request, 'Solicitud inválida para eliminar conductor.')
    return redirect('admin_dashboard')


@login_required
@check_session_timeout
def export_critical_events(request):
    # opcional: ?from=YYYY-MM-DD&to=YYYY-MM-DD
    qs = CriticalEvent.objects.select_related('conductor', 'vehiculo').all()
    from_str = request.GET.get('from')
    to_str = request.GET.get('to')
    if from_str:
        try:
            from_dt = timezone.datetime.fromisoformat(from_str)
            qs = qs.filter(timestamp__gte=from_dt)
        except Exception:
            pass
    if to_str:
        try:
            to_dt = timezone.datetime.fromisoformat(to_str)
            qs = qs.filter(timestamp__lte=to_dt)
        except Exception:
            pass

    # generar CSV
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="critical_events.csv"'
    writer = csv.writer(response)
    writer.writerow(['timestamp', 'conductor', 'documento', 'vehiculo', 'score', 'note'])
    for ev in qs:
        writer.writerow([
            ev.timestamp.isoformat(),
            ev.conductor.nombre_completo() if ev.conductor else '',
            ev.conductor.documento if ev.conductor else '',
            ev.vehiculo.placa if ev.vehiculo else '',
            ev.score,
            ev.note,
        ])
    return response


@login_required
def logout_view(request):
    if request.method == 'POST':
        auth_logout(request)
        messages.success(request, 'Has cerrado sesión correctamente.')
    return redirect('login')

@login_required
@check_session_timeout
def conductor_dashboard(request):
    return render(request, 'core/conductor_dashboard.html')