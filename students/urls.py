from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'students'

router = DefaultRouter()
router.register(r'', views.StudentViewSet, basename='student-vs')

urlpatterns = [
    path('verify/', views.StudentVerifyView.as_view(), name='student-verify'),
    path('verify/status/', views.StudentVerifyStatusView.as_view(), name='student-verify-status'),
    path('verify/logout/', views.StudentVerifyLogoutView.as_view(), name='student-verify-logout'),
    path('', views.StudentListCreateView.as_view(), name='student-list-create'),
    path('<str:student_id>/', views.StudentDetailView.as_view(), name='student-detail'),
    path('<str:student_id>/profile/', views.StudentProfileView.as_view(), name='student-profile'),
    path('<str:student_id>/fees/', views.StudentFeesView.as_view(), name='student-fees'),
    path('<str:student_id>/payments/', views.StudentPaymentListView.as_view(), name='student-payments'),
    path('<str:student_id>/payments/start/', views.StudentPaymentStartView.as_view(), name='student-payment-start'),
    path('<str:student_id>/payments/<uuid:transaction_id>/', views.StudentPaymentDetailView.as_view(), name='student-payment-detail'),
    path('', include(router.urls)),
]
