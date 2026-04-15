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
from .models import Usuario, Conductor, Vehiculo, MobileTelemetrySnapshot
from .forms import ConductorForm, VehiculoForm, EditConductorForm
from .decorators import check_session_timeout
from django.http import StreamingHttpResponse, JsonResponse
from . import drowsiness
import csv
from django.utils import timezone
from django.http import HttpResponse
from .models import CriticalEvent
from django.contrib.auth import logout as auth_logout
from django.views.decorators.csrf import csrf_exempt
import json


def api_health(request):
    return JsonResponse({'ok': True, 'service': 'eyeguard'})


@csrf_exempt
def mobile_login(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        payload = {}

    username = (payload.get('username') or '').strip()
    password = payload.get('password') or ''
    role = payload.get('role') or 'conductor'

    if not username or not password:
        return JsonResponse({'error': 'username and password are required'}, status=400)

    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({'error': 'Invalid credentials'}, status=401)

    if user.rol != role:
        return JsonResponse({'error': 'Role not allowed for this user'}, status=403)

    login(request, user)
    return JsonResponse({
        'success': True,
        'user': {
            'id': str(user.id),
            'username': user.username,
            'role': user.rol,
        }
    })


@csrf_exempt
@login_required
def mobile_logout(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    auth_logout(request)
    return JsonResponse({'success': True})


@csrf_exempt
def mobile_sync_status(request):
    """Recibe telemetría offline-first desde la app móvil local.

    Espera JSON con documento, fatigue_index, estado y ubicación opcional.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        payload = {}

    documento = str(payload.get('documentNumber') or payload.get('documento') or '').strip()
    if not documento:
        return JsonResponse({'error': 'documentNumber is required'}, status=400)

    try:
        fatigue_index = int(payload.get('fatigueIndex', 100))
    except (TypeError, ValueError):
        fatigue_index = 100
    fatigue_index = max(0, min(100, fatigue_index))

    estado = str(payload.get('status') or 'normal').strip() or 'normal'
    face_detected = bool(payload.get('faceDetected', True))
    nombre = str(payload.get('fullName') or '').strip()
    document_issue_date = str(payload.get('documentIssueDate') or '').strip()
    placa = str(payload.get('vehiclePlate') or '').strip().upper()

    lat_raw = payload.get('latitude')
    lon_raw = payload.get('longitude')
    latitude = None
    longitude = None
    try:
        if lat_raw is not None and lon_raw is not None:
            latitude = float(lat_raw)
            longitude = float(lon_raw)
    except (TypeError, ValueError):
        latitude = None
        longitude = None

    conductor = Conductor.objects.filter(documento=documento).first()

    snapshot, _ = MobileTelemetrySnapshot.objects.update_or_create(
        documento=documento,
        defaults={
            'conductor': conductor,
            'nombre_conductor': nombre,
            'document_issue_date': document_issue_date,
            'placa': placa,
            'fatigue_index': fatigue_index,
            'estado': estado,
            'face_detected': face_detected,
            'latitude': latitude,
            'longitude': longitude,
            'source': 'mobile_local',
            'last_seen_at': timezone.now(),
        },
    )

    if conductor is not None:
        conductor.estado_fatiga = fatigue_index / 100.0
        conductor.autenticado = True
        conductor.save(update_fields=['estado_fatiga', 'autenticado'])

        drowsiness.update_mobile_state_for(
            conductor,
            score=fatigue_index,
            status=estado,
            face_detected=face_detected,
            lat=latitude,
            lon=longitude,
        )

        if fatigue_index < 40:
            vehiculo = conductor.vehiculos.first()
            CriticalEvent.objects.create(
                conductor=conductor,
                vehiculo=vehiculo,
                score=fatigue_index,
                note='Alta fatiga reportada desde app móvil local',
            )

    return JsonResponse({
        'success': True,
        'linked_conductor': conductor is not None,
        'documento': snapshot.documento,
        'fatigue_index': snapshot.fatigue_index,
        'last_seen_at': snapshot.last_seen_at.isoformat(),
    })


@login_required
def mobile_latest_states(request):
    """Lista el último estado móvil recibido para mostrar soporte en dashboard."""
    snapshots = MobileTelemetrySnapshot.objects.select_related('conductor').all()[:100]
    data = []
    for item in snapshots:
        data.append({
            'documento': item.documento,
            'conductor_id': str(item.conductor.id) if item.conductor else None,
            'nombre_conductor': item.nombre_conductor,
            'document_issue_date': item.document_issue_date,
            'placa': item.placa,
            'fatigue_index': item.fatigue_index,
            'estado': item.estado,
            'face_detected': item.face_detected,
            'latitude': item.latitude,
            'longitude': item.longitude,
            'last_seen_at': item.last_seen_at.isoformat(),
        })
    return JsonResponse({'states': data})

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
    mobile_registered_count = MobileTelemetrySnapshot.objects.exclude(documento='').values('documento').distinct().count()
    
    context = {
        'conductor_form': conductor_form,
        'vehiculo_form': vehiculo_form,
        'conductores': conductores,
        'vehiculos': vehiculos,
        'mobile_registered_count': mobile_registered_count,
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
        
        # Actualizar ubicación si viene en el POST
        lat = request.POST.get('lat')
        lon = request.POST.get('lon')
        if lat and lon:
            try:
                drowsiness.update_location_for(conductor, lat, lon)
            except Exception:
                pass

        # Procesar con el detector de somnolencia
        score, face_detected = drowsiness.process_frame_for_conductor(conductor, frame)
        
        # Actualizar el estado del conductor
        conductor.estado_fatiga = score / 100.0  # Convertir a decimal
        conductor.autenticado = True
        conductor.save()
        
        # Si el score es crítico (valor bajo), guardar evento
        if score < 40:
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
            'face_detected': face_detected,
            'status': 'normal' if score >= 70 else 'warning' if score >= 40 else 'critical'
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


@login_required
def conductores_ubicaciones(request):
    """Retorna las ubicaciones en memoria de los conductores que hayan enviado coordenadas."""
    snapshot = drowsiness.get_locations_snapshot()
    # Filtrar solo conductores autenticados activos para evitar basura antigua
    activos_ids = set(str(cid) for cid in Conductor.objects.filter(autenticado=True).values_list('id', flat=True))
    ubicaciones = {}
    for cid, loc in snapshot.items():
        if cid in activos_ids:
            ubicaciones[cid] = loc
    return JsonResponse({'ubicaciones': ubicaciones})


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