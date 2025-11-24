from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required  
from django.http import HttpResponse
from django.utils import translation
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages

def set_language(request):
    """Vista para cambiar el idioma de la aplicación"""
    if request.method == 'POST':
        language = request.POST.get('language')
        next_url = request.POST.get('next', '/')
        if language:
            translation.activate(language)
            response = redirect(next_url)
            response.set_cookie(
                'django_language',
                language,
                max_age=365 * 24 * 60 * 60,  # 1 año
                path='/',
                samesite='Lax'
            )
            return response
    return redirect('home')

def home(request):
    # Mostrar la landing page principal del proyecto en la raíz.
    # Si el usuario está autenticado y queremos redirigirle automáticamente
    # a su dashboard según rol, podemos mantener esa lógica en el login.
    return render(request, 'core/home.html')

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.crypto import get_random_string
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
                # mostrar errores cuando la edición falla
                errors = {
                    'conductor_errors': conductor_form.errors,
                    'vehiculo_errors': vehiculo_form.errors,
                }
                # registrar en consola para depuración
                print('Edit conductor errors:', errors)
                messages.error(request, 'Errores en el formulario al actualizar. Revisa los campos.')
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
                # cuando la creación falla, mostrar y registrar errores para ayudar al debugging
                errors = {
                    'conductor_errors': conductor_form.errors,
                    'vehiculo_errors': vehiculo_form.errors,
                }
                print('Create conductor errors:', errors)
                # Mostrar un mensaje genérico y dejar los errores por campo en la plantilla
                messages.error(request, 'No se pudo crear el conductor. Revisa los errores en el formulario.')
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


@login_required
def conductor_send_frame(request):
    """
    Recibe frames individuales desde el navegador del conductor
    y los procesa para detectar somnolencia.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    if not hasattr(request.user, 'perfil_conductor'):
        return JsonResponse({'error': 'User is not a conductor'}, status=403)
    
    conductor = request.user.perfil_conductor
    
    # Obtener el frame del request
    frame_file = request.FILES.get('frame')
    if not frame_file:
        return JsonResponse({'error': 'No frame provided'}, status=400)
    
    try:
        # Procesar el frame con el módulo de drowsiness
        import cv2
        import numpy as np
        from io import BytesIO
        
        # Leer el frame como imagen
        file_bytes = np.asarray(bytearray(frame_file.read()), dtype=np.uint8)
        frame = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
        
        if frame is None:
            return JsonResponse({'error': 'Invalid frame'}, status=400)
        
        # Procesar con el detector de somnolencia
        score = drowsiness.process_frame_for_conductor(conductor, frame)
        
        # Actualizar el estado del conductor
        conductor.estado_fatiga = score / 100.0  # Convertir a decimal
        conductor.autenticado = True
        conductor.save()
        
        # Si el score es crítico, guardar evento
        if score >= 70:
            from .models import CriticalEvent
            vehiculo = conductor.vehiculos.first()
            CriticalEvent.objects.create(
                conductor=conductor,
                vehiculo=vehiculo,
                score=score,
                note=f"Alta fatiga detectada desde navegador del conductor"
            )
        
        return JsonResponse({
            'success': True,
            'score': score,
            'status': 'normal' if score < 30 else 'warning' if score < 70 else 'critical'
        })
        
    except Exception as e:
        print(f"Error processing frame: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def conductor_stop_stream(request):
    """
    Notifica que el conductor ha detenido la transmisión
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    if not hasattr(request.user, 'perfil_conductor'):
        return JsonResponse({'error': 'User is not a conductor'}, status=403)
    
    conductor = request.user.perfil_conductor
    conductor.autenticado = False
    conductor.save()
    
    # Limpiar el stream del conductor
    drowsiness.stop_stream_for(conductor)
    
    return JsonResponse({'success': True})


@login_required
def conductores_activos(request):
    """
    Retorna la lista de IDs de conductores que están transmitiendo actualmente
    """
    conductores_streaming = Conductor.objects.filter(autenticado=True).values_list('id', flat=True)
    return JsonResponse({
        'conductores_activos': [str(c_id) for c_id in conductores_streaming]
    })


def password_reset(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            user = Usuario.objects.get(email=email)
            # Generar contraseña temporal
            temp_password = get_random_string(12)
            user.set_password(temp_password)
            user.save()
            
            # Enviar correo con la contraseña temporal
            subject = 'Recuperación de contraseña - EyeGuard'
            message = f"""
            Hola {user.username},
            
            Se ha solicitado un restablecimiento de contraseña para tu cuenta.
            Tu contraseña temporal es: {temp_password}
            
            Por favor, ingresa al sistema con esta contraseña y cámbiala inmediatamente por una nueva.
            
            Si no solicitaste este cambio, por favor contacta al administrador.
            
            Saludos,
            Equipo EyeGuard
            """
            
            try:
                send_mail(
                    subject,
                    message,
                    'noreply@eyeguard.com',  # Remitente
                    [email],  # Destinatario
                    fail_silently=False,
                )
                messages.success(request, 'Se ha enviado un correo con las instrucciones para recuperar tu contraseña.')
            except Exception as e:
                messages.error(request, 'Error al enviar el correo. Por favor, contacta al administrador.')
                print(f"Error sending email: {e}")
                
        except Usuario.DoesNotExist:
            messages.error(request, 'No existe una cuenta registrada con ese correo electrónico.')
        
    return render(request, 'core/password_reset.html')