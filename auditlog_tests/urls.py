from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
    url(r'^grappelli/', include('grappelli.urls')),
]
