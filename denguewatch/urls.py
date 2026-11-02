from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.views import serve as serve_static_file


urlpatterns = [

    path(
        'admin/',
        admin.site.urls
    ),

    path(
        '',
        include('monitoring.urls')
    ),

]


if settings.DEBUG:

    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )

# The local runserver is used for the website even when DEBUG is disabled in
# .env. Serve only files found by Django's staticfiles finders; set
# DJANGO_SERVE_STATIC_FILES=False when a production web server serves assets.
if settings.SERVE_STATIC_FILES and not settings.DEBUG:
    urlpatterns += [
        path('static/<path:path>', serve_static_file, {'insecure': True}),
    ]
