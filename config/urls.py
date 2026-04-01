# from django.contrib import admin
# from django.urls import path, include

# urlpatterns = [
#     path('admin/', admin.site.urls),
#     path('api/students/', include('students.urls')),
#     path('api/payments/', include(('payments.urls', 'payments'), namespace='payments')),
# ]

# from django.urls import path, include

# urlpatterns = [
#     # ... أي routes تانية
#     path('ai-agent/', include('ai_agent.urls')),
# ]



from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('auth_api.urls')),
    path('api/students/', include('students.urls')),
    path('api/payments/', include(('payments.urls', 'payments'), namespace='payments')),
    path('api/ai-agent/', include('ai_agent.urls')),
]
