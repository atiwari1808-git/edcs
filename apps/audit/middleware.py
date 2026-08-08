from .models import AuditLog

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
SKIP_PREFIXES = ("/static/", "/media/")


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            if (request.method in MUTATING
                    and not request.path.startswith(SKIP_PREFIXES)
                    and getattr(request, "user", None)
                    and request.user.is_authenticated):
                AuditLog.objects.create(
                    actor=request.user, method=request.method,
                    path=request.path[:300], status_code=response.status_code,
                    ip=request.META.get("REMOTE_ADDR"))
        except Exception:  # auditing must never break the request
            pass
        return response
