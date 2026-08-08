"""View decorator enforcing RBAC. This is the actual security boundary —
the UI hides buttons/links a user lacks permission for, but every mutating
endpoint calls through this decorator independently, so a hand-crafted API
request without the right permission is rejected the same way regardless
of what the UI showed."""
import functools

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render

from .permissions import user_has_permission


def require_permission(codename: str):
    def decorator(view_func):
        @functools.wraps(view_func)
        @login_required
        def wrapped(request, *args, **kwargs):
            if not user_has_permission(request.user, codename):
                if request.path.startswith("/api/"):
                    return JsonResponse(
                        {"error": f"Forbidden: missing permission '{codename}'."},
                        status=403)
                return render(request, "403.html",
                             {"codename": codename}, status=403)
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator
