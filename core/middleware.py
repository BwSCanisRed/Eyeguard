from django.conf import settings
from django.contrib.auth import logout
from django.utils import timezone
from django.shortcuts import redirect
from django.urls import reverse
import datetime

class SessionTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            current_datetime = timezone.now()
            
            # Obtener la última actividad del usuario
            last_activity = request.session.get('last_activity')
            
            if last_activity:
                last_activity = datetime.datetime.fromisoformat(last_activity)
                time_elapsed = current_datetime - last_activity
                
                # Si el tiempo transcurrido es mayor que el timeout, cerrar sesión
                if time_elapsed.total_seconds() > settings.SESSION_IDLE_TIMEOUT:
                    logout(request)
                    # Eliminar la última actividad
                    if 'last_activity' in request.session:
                        del request.session['last_activity']
                    return redirect('login')
            
            # Actualizar el tiempo de última actividad
            request.session['last_activity'] = current_datetime.isoformat()

        response = self.get_response(request)
        return response