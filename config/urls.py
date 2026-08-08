from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.accounts.urls")),
    path("", include("apps.validation.urls")),
    path("", include("apps.scheduler.urls")),
    path("", include("apps.rbac.urls")),
    path("auth/graph/", include("apps.msgraph.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = "EDCS-Gate Administration"
admin.site.site_title = "EDCS-Gate Admin"
