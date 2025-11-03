from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone
from django.conf import settings
import datetime
from functools import wraps

def check_session_timeout(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if request.user.is_authenticated:
            last_activity = request.session.get('last_activity')
            if last_activity:
                last_activity = datetime.datetime.fromisoformat(last_activity)
                time_elapsed = timezone.now() - last_activity
                
                if time_elapsed.total_seconds() > settings.SESSION_IDLE_TIMEOUT:
                    logout(request)
                    if 'last_activity' in request.session:
                        del request.session['last_activity']
                    return redirect('login')
            
            request.session['last_activity'] = timezone.now().isoformat()
        return view_func(request, *args, **kwargs)
    return wrapped