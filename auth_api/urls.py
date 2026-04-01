from django.urls import path
from . import views

app_name = "auth_api"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("whoami/", views.WhoAmIView.as_view(), name="whoami"),
]
